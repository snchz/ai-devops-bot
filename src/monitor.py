import re
import time
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from src.config import Config
from src.loki import LokiClient
from src.knowledge_base import KnowledgeBase
from src.gemini import GeminiClient
from src.database import Database
from src.web_server import WebServer
from src.logger import logger, METRICS

class LogMonitor:
    """Orchestrator to poll Loki, process logs, and get suggestions asynchronously."""
    
    def __init__(self, config: Config):
        self.config = config
        self.loki = LokiClient(config)
        self.gemini = GeminiClient(config)
        self.db = Database(config.db_path)
        self.kb = KnowledgeBase(self.db)
        self.last_processed_timestamp_ns: Optional[int] = None
        self.sent_alerts = {}  # In-memory mapping of alert_key -> timestamp


    def _is_ignored_level(self, log: Dict[str, Any]) -> bool:
        """
        Determines if a log item has an informational/debug/trace level and should be ignored,
        even if it matched the LOKI_QUERY (e.g. contains 'Error' in another context like 'Error: <nil>').
        """
        message = log.get("message", "")
        labels = log.get("labels", {})

        # 1. Check labels for level/severity/loglevel
        for k, v in labels.items():
            if k.lower() in ("level", "severity", "loglevel"):
                if v.lower() in ("info", "debug", "trace", "informational"):
                    return True

        # 2. Check message content for explicit level indicators
        # Logfmt style: level=info, level="info", severity=info, loglevel=info
        logfmt_pattern = r'\b(level|severity|loglevel)\s*=\s*[\'"]?(info|debug|trace|informational)[\'"]?\b'
        if re.search(logfmt_pattern, message, re.IGNORECASE):
            # To avoid dropping an error that was nested in an info log,
            # check if there's also an explicit level=error/warn in the message.
            has_error_level = re.search(r'\b(level|severity|loglevel)\s*=\s*[\'"]?(error|warn|warning|fatal|panic|crit|critical|emerg|emergency)[\'"]?\b', message, re.IGNORECASE)
            has_bracket_error = re.search(r'\[(error|warn|warning|fatal|panic|crit|critical|emerg|emergency)\]', message, re.IGNORECASE)
            if not (has_error_level or has_bracket_error):
                return True

        # JSON style: "level": "info", "severity": "info"
        json_pattern = r'"(level|severity|loglevel)"\s*:\s*[\'"]?(info|debug|trace|informational)[\'"]?'
        if re.search(json_pattern, message, re.IGNORECASE):
            has_error_json = re.search(r'"(level|severity|loglevel)"\s*:\s*[\'"]?(error|warn|warning|fatal|panic|crit|critical|emerg|emergency)[\'"]?', message, re.IGNORECASE)
            if not has_error_json:
                return True

        # Bracket style: [INFO], [DEBUG], [TRACE]
        bracket_pattern = r'\[(info|debug|trace|informational)\]'
        if re.search(bracket_pattern, message, re.IGNORECASE):
            has_error_bracket = re.search(r'\[(error|warn|warning|fatal|panic|crit|critical|emerg|emergency)\]', message, re.IGNORECASE)
            if not has_error_bracket:
                return True

        # Standard prefix/colon style: INFO: or DEBUG: or TRACE:
        prefix_pattern = r'\b(info|debug|trace)\s*:\s+'
        if re.search(prefix_pattern, message, re.IGNORECASE):
            has_error_prefix = re.search(r'\b(error|warn|warning|fatal|panic|crit|critical)\s*:\s+', message, re.IGNORECASE)
            if not has_error_prefix:
                return True

        return False

    async def establish_baseline(self):
        """Queries Loki for the last 5 minutes to find the most recent log timestamp to avoid historical spam."""
        logger.info("Estableciendo línea base de logs para evitar falsos positivos históricos...")
        
        lookback_ns = 5 * 60 * 1_000_000_000
        start_time_ns = (time.time_ns()) - lookback_ns
        
        logs = await self.loki.fetch_logs(start_ns=start_time_ns, limit=1000)
        
        if logs:
            max_ts = max(log["timestamp_ns"] for log in logs)
            self.last_processed_timestamp_ns = max_ts
            dt_str = datetime.fromtimestamp(max_ts / 1_000_000_000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            logger.info(f"Línea base establecida. Ignorando logs anteriores a: {dt_str} (TS: {max_ts})")
        else:
            self.last_processed_timestamp_ns = time.time_ns()
            logger.info(f"No se encontraron logs recientes. Línea base fijada al tiempo actual del sistema: {self.last_processed_timestamp_ns}")

    def group_and_deduplicate(self, logs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Groups retrieved raw log items by container or job name.
        Combines logs that occur within 2 seconds of each other into a single block
        (useful for tracebacks), and counts exact duplications.
        """
        grouped = {}
        for log in logs:
            # Group by container_name first (standard for docker driver), fallback to job name
            app = log["labels"].get("container_name", log["labels"].get("job", "sistema"))
            
            if app not in grouped:
                grouped[app] = []
                
            msg = log["message"]
            log_time = log.get("timestamp_ns", 0)
            
            # Check for exact duplicate in current list
            found_exact = False
            for item in grouped[app]:
                if item["message"] == msg:
                    item["count"] += 1
                    item["datetime"] = log["datetime"]  # Update to latest datetime seen
                    item["timestamp_ns"] = max(item.get("timestamp_ns", 0), log_time)
                    found_exact = True
                    break
                    
            if not found_exact:
                # Check for time proximity (within 2 seconds) to group into an existing block
                added_to_block = False
                for item in grouped[app]:
                    if abs(item.get("timestamp_ns", 0) - log_time) <= 2_000_000_000:
                        # Append the new message line to the existing block
                        item["message"] += "\n" + msg
                        # Update the block's time to the latest log's time
                        item["datetime"] = log["datetime"]
                        item["timestamp_ns"] = max(item.get("timestamp_ns", 0), log_time)
                        added_to_block = True
                        break
                        
                if not added_to_block:
                    grouped[app].append({
                        "message": msg,
                        "datetime": log["datetime"],
                        "timestamp_ns": log_time,
                        "count": 1,
                        "labels": log["labels"]
                    })
        return grouped

    async def run_poll_cycle(self):
        """Runs a single polling and processing cycle asynchronously."""
        logger.info("Iniciando ciclo de sondeo en Grafana Loki...")
        METRICS["cycles"] += 1
        
        # 0. Perform auto-closure check for inactive open/resolved incidents (older than 1 week)
        await asyncio.to_thread(self.db.auto_close_inactive_incidents)
        
        safety_window_ns = 2 * 60 * 1_000_000_000
        query_start_ns = self.last_processed_timestamp_ns - safety_window_ns
        
        fetched_logs = await self.loki.fetch_logs(start_ns=query_start_ns)
        
        total_fetched = len(fetched_logs) if fetched_logs else 0
        logger.info(f"Sondeo de Loki completado. Logs recuperados en el búfer temporal: {total_fetched}")
        
        if not fetched_logs:
            logger.info("No se recibieron logs de Loki en este ciclo.")
            return

        new_logs = []
        for log in fetched_logs:
            if log["timestamp_ns"] <= self.last_processed_timestamp_ns:
                continue
            if self._is_ignored_level(log):
                logger.debug(f"Ignorando log informativo/debug: {log['message'][:80]}")
                continue
            new_logs.append(log)
        
        if not new_logs:
            logger.info("No hay nuevos logs de error/alerta desde la última iteración.")
            return
            
        logger.info(f"Detectados {len(new_logs)} nuevos logs de error.")
        METRICS["errors_detected"] += len(new_logs)
        
        # 1. Group and deduplicate in memory
        grouped_logs = self.group_and_deduplicate(new_logs)
        
        # 2. Filter out logs under cooldown to prevent alert fatigue
        now = time.time()
        filtered_grouped_logs = {}
        skipped_count = 0
        
        for app, items in grouped_logs.items():
            filtered_items = []
            for item in items:
                # Snippet of message to identify log type without variable stamps
                msg_snippet = item["message"][:80].strip()
                cooldown_key = f"{app}:{msg_snippet}"
                
                last_sent = self.sent_alerts.get(cooldown_key, 0.0)
                if now - last_sent < self.config.cooldown_seconds:
                    skipped_count += item["count"]
                    logger.info(f"🔕 [Cooldown] Alerta omitida para {app}: '{msg_snippet[:50]}...' (En periodo de enfriamiento).")
                    continue
                
                # Register send timestamp and append
                self.sent_alerts[cooldown_key] = now
                filtered_items.append(item)
                
            if filtered_items:
                filtered_grouped_logs[app] = filtered_items
                
        # Clean up expired cooldowns to save memory
        self.sent_alerts = {k: ts for k, ts in self.sent_alerts.items() if now - ts < self.config.cooldown_seconds}
        
        if not filtered_grouped_logs:
            logger.info(f"Todos los nuevos logs ({len(new_logs)}) están en enfriamiento. Ciclo omitido.")
            max_ts = max(log["timestamp_ns"] for log in new_logs)
            self.last_processed_timestamp_ns = max_ts
            return
            
        if skipped_count > 0:
            logger.info(f"Silenciadas {skipped_count} repeticiones de error en este ciclo por políticas de fatiga de alertas.")
            
        # Compile a flat list of unique items for Knowledge Base matching
        flat_unique_logs = []
        for items in filtered_grouped_logs.values():
            flat_unique_logs.extend(items)
            
        # 3. Match unique logs with local RAG Knowledge Base rules
        matched_rules = self.kb.match_logs(flat_unique_logs)
        
        # 4. Analyze logs in batch, injecting custom solutions if rules were matched
        try:
            analysis = await self.gemini.analyze_logs(filtered_grouped_logs, matched_rules)
        except Exception as ai_err:
            logger.error(f"Excepción al invocar el proveedor de IA: {ai_err}")
            analysis = None
        
        if not analysis:
            logger.warning("No se pudo obtener el análisis de la IA. Registrando incidente con propuesta de fallback.")
            analysis = (
                "⚠️ **[ERROR DE PROVEEDOR DE IA]**\n\n"
                "El bot no pudo obtener un diagnóstico automatizado del proveedor de Inteligencia Artificial seleccionado "
                "(verifica tu `AI_PROVIDER` y `API_KEY` en la configuración del archivo `.env`).\n\n"
                "Puedes consultar el detalle del error en los logs originales del contenedor mostrados arriba."
            )
        else:
            METRICS["alerts_sent"] += 1
            
        # Save incident to database (register or update recurrence of each unique error in the database)
        for app, items in filtered_grouped_logs.items():
            for item in items:
                await asyncio.to_thread(self.db.register_or_recur_incident, app, item, matched_rules, analysis)
            
        # Update last processed timestamp to the latest log seen
        max_ts = max(log["timestamp_ns"] for log in new_logs)
        self.last_processed_timestamp_ns = max_ts
        logger.info(f"Ciclo completado. Último timestamp actualizado a: {max_ts}")

    async def polling_loop(self):
        """Infinite polling cycle task."""
        while True:
            try:
                await self.run_poll_cycle()
            except Exception as e:
                logger.error(f"Excepción crítica no controlada en el ciclo de monitoreo: {e}", exc_info=True)
                
            # Leer el intervalo de revisión (en minutos) desde la base de datos (con fallback a config)
            poll_interval_minutes = await asyncio.to_thread(
                self.db.get_setting, 
                "poll_interval_minutes", 
                str(self.config.poll_interval / 60.0)
            )
            try:
                poll_interval_seconds = int(float(poll_interval_minutes) * 60)
            except ValueError:
                poll_interval_seconds = self.config.poll_interval
                
            logger.info(f"Durmiendo el proceso durante {poll_interval_seconds} segundos ({(poll_interval_seconds/60.0):.2f} min)...")
            await asyncio.sleep(poll_interval_seconds)

    async def start(self):
        """Starts all concurrent background tasks using asyncio."""
        logger.info(f"Iniciando Bot de Monitoreo de Logs con {self.config.ai_provider}...")
        
        try:
            await self.establish_baseline()
        except Exception as e:
            logger.error(f"Error crítico al establecer la línea base en el arranque: {e}")
            self.last_processed_timestamp_ns = time.time_ns()
            logger.info(f"Fijando timestamp de seguridad al tiempo actual por fallo: {self.last_processed_timestamp_ns}")
            
        polling_task = asyncio.create_task(self.polling_loop())
        tasks = [polling_task]
        
        if self.config.healthcheck_port:
            web_server = WebServer(self.config, self.db)
            web_task = asyncio.create_task(web_server.start())
            tasks.append(web_task)
            
        await asyncio.gather(*tasks)
