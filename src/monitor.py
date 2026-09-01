import re
import json
import time
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from src.config import Config
from src.docker_client import DockerClient
from src.knowledge_base import KnowledgeBase
from src.gemini import GeminiClient
from src.database import Database
from src.web_server import WebServer
from src.logger import logger, METRICS

class LogMonitor:
    """Orchestrator to poll Docker container logs, process errors, and get AI suggestions asynchronously."""
    
    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.db_path)
        self.kb = KnowledgeBase(self.db)
        self.gemini = GeminiClient(config)
        self.log_client = DockerClient(config)
        self.last_processed_timestamp_ns: Optional[int] = None
        self.sent_alerts = {}  # In-memory mapping of alert_key -> timestamp

    def _is_ignored_level(self, log: Dict[str, Any]) -> bool:
        """Determines if a log item has an informational/debug level and should be ignored."""
        message = log.get("message", "").strip()
        labels = log.get("labels", {})

        info_levels = {"info", "debug", "trace", "informational"}
        error_levels = {"error", "warn", "warning", "fatal", "panic", "crit", "critical", "emerg", "emergency"}

        # 1. Check labels
        for k, v in labels.items():
            if k.lower() in ("level", "severity", "loglevel"):
                v_lower = str(v).lower()
                if v_lower in info_levels:
                    return True
                if v_lower in error_levels:
                    return False

        # 2. Try JSON parsing
        try:
            parsed_json = json.loads(message)
            if isinstance(parsed_json, dict):
                for key in ("level", "severity", "loglevel"):
                    if key in parsed_json:
                        val = str(parsed_json[key]).lower()
                        if val in error_levels:
                            return False
                        if val in info_levels:
                            return True
        except json.JSONDecodeError:
            pass

        # 3. Logfmt parsing
        logfmt_pattern = r'([a-zA-Z0-9_.-]+)=((?:[^\s"\']+)|\"[^\"]*\"|\'[^\']*\')'
        logfmt_matches = dict(re.findall(logfmt_pattern, message))
        for key in ("level", "severity", "loglevel"):
            if key in logfmt_matches:
                val = logfmt_matches[key].strip("'\"").lower()
                if val in error_levels:
                    return False
                if val in info_levels:
                    return True

        # 4. Bracket style: [INFO], [DEBUG]
        bracket_pattern = r'\[(info|debug|trace|informational)\]'
        if re.search(bracket_pattern, message, re.IGNORECASE):
            has_error_bracket = re.search(r'\[(error|warn|warning|fatal|panic|crit|critical|emerg|emergency)\]', message, re.IGNORECASE)
            if not has_error_bracket:
                return True

        # 5. Standard prefix style: INFO: or DEBUG:
        prefix_pattern = r'\b(info|debug|trace)\s*:\s+'
        if re.search(prefix_pattern, message, re.IGNORECASE):
            has_error_prefix = re.search(r'\b(error|warn|warning|fatal|panic|crit|critical)\s*:\s+', message, re.IGNORECASE)
            if not has_error_prefix:
                return True

        return False

    async def establish_baseline(self):
        """Initializes the baseline timestamp to the current time to avoid historical spam."""
        logger.info("Estableciendo línea base de logs para evitar falsos positivos históricos...")
        lookback_ns = 2 * 60 * 1_000_000_000  # 2 minutes lookback
        start_time_ns = time.time_ns() - lookback_ns
        
        try:
            logs = await self.log_client.fetch_logs(start_ns=start_time_ns, limit=200)
            if logs:
                max_ts = max(log["timestamp_ns"] for log in logs)
                self.last_processed_timestamp_ns = max_ts
                dt_str = datetime.fromtimestamp(max_ts / 1_000_000_000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                logger.info(f"Línea base establecida. Ignorando logs anteriores a: {dt_str}")
            else:
                self.last_processed_timestamp_ns = time.time_ns()
                logger.info("No se encontraron logs recientes. Línea base fijada al tiempo actual.")
        except Exception as e:
            logger.error(f"Error al establecer línea base: {e}")
            self.last_processed_timestamp_ns = time.time_ns()

    def group_and_deduplicate(self, logs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Groups logs by container and combines identical messages."""
        grouped = {}
        for log in logs:
            app = log["labels"].get("container_name", "sistema")
            if app not in grouped:
                grouped[app] = []
                
            msg = log["message"]
            log_time = log.get("timestamp_ns", 0)
            
            found_exact = False
            for item in grouped[app]:
                if item["message"] == msg:
                    item["count"] += 1
                    item["datetime"] = log["datetime"]
                    item["timestamp_ns"] = max(item.get("timestamp_ns", 0), log_time)
                    found_exact = True
                    break
                    
            if not found_exact:
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
        logger.info("Iniciando ciclo de sondeo de logs en Docker...")
        METRICS["cycles"] += 1
        
        # Auto-closure and auto-purge check for inactive incidents
        await asyncio.to_thread(self.db.auto_close_inactive_incidents)
        
        query_start_ns = self.last_processed_timestamp_ns or (time.time_ns() - 60 * 1_000_000_000)
        fetched_logs = await self.log_client.fetch_logs(start_ns=query_start_ns)
        
        total_fetched = len(fetched_logs) if fetched_logs else 0
        logger.info(f"Sondeo completado. Logs recuperados en el búfer temporal: {total_fetched}")
        
        if not fetched_logs:
            return

        new_logs = []
        for log in fetched_logs:
            if log["timestamp_ns"] <= self.last_processed_timestamp_ns:
                continue
            if self._is_ignored_level(log):
                continue
            new_logs.append(log)
        
        if not new_logs:
            logger.info("No hay nuevos logs de error/alerta desde la última iteración.")
            return
            
        logger.info(f"Detectados {len(new_logs)} nuevos logs de error.")
        METRICS["errors_detected"] += len(new_logs)
        
        # 1. Group and deduplicate in memory
        grouped_logs = self.group_and_deduplicate(new_logs)
        
        # 2. Filter out logs under cooldown
        now = time.time()
        filtered_grouped_logs = {}
        skipped_count = 0
        
        for app, items in grouped_logs.items():
            filtered_items = []
            for item in items:
                msg_snippet = item["message"][:80].strip()
                cooldown_key = f"{app}:{msg_snippet}"
                
                last_sent = self.sent_alerts.get(cooldown_key, 0.0)
                if now - last_sent < self.config.cooldown_seconds:
                    skipped_count += item["count"]
                    logger.info(f"🔕 [Cooldown] Alerta omitida para {app}: '{msg_snippet[:40]}...' (En enfriamiento).")
                    continue
                
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
            
        # 3. Match unique logs with local Knowledge Base rules
        logs_for_ai = {}
        ignored_logs_to_save = []
        matched_rules_for_ai = []
        
        rules = self.kb.load_rules()
        
        for app, items in filtered_grouped_logs.items():
            for item in items:
                msg_lower = item["message"].lower()
                item_matched_rules = []
                is_ignored = False
                
                for rule in rules:
                    pattern = rule.get("pattern", "").lower()
                    if pattern and pattern in msg_lower:
                        item_matched_rules.append(rule)
                        if rule.get("action", "ALERT").upper() == "IGNORE":
                            is_ignored = True
                            
                if is_ignored:
                    ignored_logs_to_save.append((app, item, item_matched_rules))
                else:
                    if app not in logs_for_ai:
                        logs_for_ai[app] = []
                    logs_for_ai[app].append(item)
                    for r in item_matched_rules:
                        if r not in matched_rules_for_ai:
                            matched_rules_for_ai.append(r)
                            
        # 4. Analyze logs with AI
        analysis = None
        if logs_for_ai:
            try:
                analysis = await self.gemini.analyze_logs(logs_for_ai, matched_rules_for_ai)
            except Exception as ai_err:
                logger.error(f"Excepción al invocar el proveedor de IA: {ai_err}")
                analysis = None
            
            if not analysis:
                analysis = (
                    "⚠️ **[ERROR DE PROVEEDOR DE IA]**\n\n"
                    "El bot no pudo obtener un diagnóstico automatizado de la IA.\n"
                    "Verifica tu `AI_PROVIDER` y `GROQ_API_KEY` o `GEMINI_API_KEY` en el archivo `.env`."
                )
            else:
                METRICS["alerts_sent"] += 1
            
        # 5. Save incidents to database
        for app, items in logs_for_ai.items():
            for item in items:
                await asyncio.to_thread(self.db.register_or_recur_incident, app, item, matched_rules_for_ai, analysis)
                
        for app, item, item_rules in ignored_logs_to_save:
            ignore_analysis = "🔇 **[AUTO-RESUELTO]**\n\nIncidencia silenciada automáticamente por Regla de Conocimiento (Acción: Ignorar)."
            await asyncio.to_thread(self.db.register_or_recur_incident, app, item, item_rules, ignore_analysis)
            
        max_ts = max(log["timestamp_ns"] for log in new_logs)
        self.last_processed_timestamp_ns = max_ts
        logger.info(f"Ciclo completado. Último timestamp: {max_ts}")

    async def polling_loop(self):
        """Infinite polling cycle task."""
        while True:
            try:
                await self.run_poll_cycle()
            except Exception as e:
                logger.error(f"Excepción en ciclo de monitoreo: {e}", exc_info=True)
                
            poll_interval_minutes = await asyncio.to_thread(self.db.get_setting, "poll_interval_minutes", "5.0")
            try:
                poll_interval_seconds = int(float(poll_interval_minutes) * 60)
            except ValueError:
                poll_interval_seconds = 300
                
            logger.info(f"Durmiendo el proceso durante {poll_interval_seconds} segundos ({(poll_interval_seconds/60.0):.2f} min)...")
            await asyncio.sleep(poll_interval_seconds)

    async def start(self):
        """Starts all concurrent background tasks using asyncio."""
        logger.info(f"Iniciando Bot de Monitoreo de Logs de Docker con {self.config.ai_provider}...")
        
        await self.establish_baseline()
            
        polling_task = asyncio.create_task(self.polling_loop())
        tasks = [polling_task]
        
        if self.config.healthcheck_port:
            web_server = WebServer(self.config, self.db, self.log_client)
            web_task = asyncio.create_task(web_server.start())
            tasks.append(web_task)
            
        await asyncio.gather(*tasks)
