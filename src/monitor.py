import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from src.config import Config
from src.loki import LokiClient
from src.knowledge_base import KnowledgeBase
from src.gemini import GeminiClient
from src.telegram import TelegramClient
from src.logger import logger

class LogMonitor:
    """Orchestrator to poll Loki, process logs, get suggestions, and alert via Telegram."""
    
    def __init__(self, config: Config):
        self.config = config
        self.loki = LokiClient(config)
        self.gemini = GeminiClient(config)
        self.telegram = TelegramClient(config)
        self.kb = KnowledgeBase(config.kb_path)
        self.last_processed_timestamp_ns: Optional[int] = None

    def establish_baseline(self):
        """Queries Loki for the last 5 minutes to find the most recent log timestamp to avoid historical spam."""
        logger.info("Estableciendo línea base de logs para evitar falsos positivos históricos...")
        
        lookback_ns = 5 * 60 * 1_000_000_000
        start_time_ns = (time.time_ns()) - lookback_ns
        
        logs = self.loki.fetch_logs(start_ns=start_time_ns, limit=1000)
        
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
        Groups retrieved raw log items by container or job name and collapses
        identical message strings to count duplications.
        """
        grouped = {}
        for log in logs:
            # Group by container_name first (standard for docker driver), fallback to job name
            app = log["labels"].get("container_name", log["labels"].get("job", "sistema"))
            
            if app not in grouped:
                grouped[app] = []
                
            msg = log["message"]
            
            # Check for exact duplicate in current list
            found = False
            for item in grouped[app]:
                if item["message"] == msg:
                    item["count"] += 1
                    item["datetime"] = log["datetime"]  # Update to latest datetime seen
                    found = True
                    break
                    
            if not found:
                grouped[app].append({
                    "message": msg,
                    "datetime": log["datetime"],
                    "count": 1,
                    "labels": log["labels"]
                })
        return grouped

    def run_poll_cycle(self):
        """Runs a single polling and processing cycle."""
        logger.info("Iniciando ciclo de sondeo en Grafana Loki...")
        
        safety_window_ns = 2 * 60 * 1_000_000_000
        query_start_ns = self.last_processed_timestamp_ns - safety_window_ns
        
        fetched_logs = self.loki.fetch_logs(start_ns=query_start_ns)
        
        total_fetched = len(fetched_logs) if fetched_logs else 0
        logger.info(f"Sondeo de Loki completado. Logs recuperados en el búfer temporal: {total_fetched}")
        
        if not fetched_logs:
            logger.info("No se recibieron logs de Loki en este ciclo.")
            return

        new_logs = [log for log in fetched_logs if log["timestamp_ns"] > self.last_processed_timestamp_ns]
        
        if not new_logs:
            logger.info("No hay nuevos logs de error desde la última iteración.")
            return
            
        logger.info(f"Detectados {len(new_logs)} nuevos logs de error.")
        
        # 1. Group and deduplicate in memory
        grouped_logs = self.group_and_deduplicate(new_logs)
        
        # Compile a flat list of unique items for Knowledge Base matching
        flat_unique_logs = []
        for items in grouped_logs.values():
            flat_unique_logs.extend(items)
            
        # 2. Match unique logs with local RAG Knowledge Base rules
        matched_rules = self.kb.match_logs(flat_unique_logs)
        
        # 3. Analyze logs in batch, injecting custom solutions if rules were matched
        analysis = self.gemini.analyze_logs(grouped_logs, matched_rules)
        
        if not analysis:
            logger.error("No se pudo obtener el análisis de la IA. Se reintentará en el próximo ciclo.")
            return
            
        # 4. Dispatch Telegram report grouped by application
        telegram_sent = self.telegram.send_alert(grouped_logs, matched_rules, analysis)
        
        if telegram_sent:
            max_ts = max(log["timestamp_ns"] for log in new_logs)
            self.last_processed_timestamp_ns = max_ts
            logger.info(f"Ciclo completado. Último timestamp actualizado a: {max_ts}")
        else:
            logger.warning("Fallo el envío a Telegram. No se actualiza el timestamp para reintentar en el próximo ciclo.")

    def start(self):
        """Starts the infinite polling loop."""
        logger.info("Iniciando Bot de Monitoreo de Logs con Groq (Llama 3.3)...")
        
        try:
            self.establish_baseline()
        except Exception as e:
            logger.error(f"Error crítico al establecer la línea base en el arranque: {e}")
            self.last_processed_timestamp_ns = time.time_ns()
            logger.info(f"Fijando timestamp de seguridad al tiempo actual por fallo: {self.last_processed_timestamp_ns}")
            
        while True:
            try:
                self.run_poll_cycle()
            except Exception as e:
                logger.error(f"Excepción crítica no controlada en el ciclo de monitoreo: {e}", exc_info=True)
                
            logger.info(f"Durmiendo el proceso durante {self.config.poll_interval} segundos...")
            time.sleep(self.config.poll_interval)
