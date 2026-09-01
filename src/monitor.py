import re
import json
import time
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Final
from src.config import Config
from src.docker_client import DockerClient
from src.knowledge_base import KnowledgeBase
from src.gemini import GeminiClient
from src.database import Database
from src.web_server import WebServer
from src.logger import logger, METRICS

INFO_LEVELS: Final[set] = {"info", "debug", "trace", "informational"}
ERROR_LEVELS: Final[set] = {"error", "warn", "warning", "fatal", "panic", "crit", "critical", "emerg", "emergency"}


class LogMonitor:
    """Orchestrator to poll Docker container logs, process errors, and get AI suggestions asynchronously."""

    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self.db: Database = Database(config.db_path)
        self.kb: KnowledgeBase = KnowledgeBase(self.db)
        self.gemini: GeminiClient = GeminiClient(config)
        self.log_client: DockerClient = DockerClient(config)
        self.last_processed_timestamp_ns: Optional[int] = None
        self.sent_alerts: Dict[str, float] = {}

    def _is_ignored_level(self, log: Dict[str, Any]) -> bool:
        """Determines if a log item has an informational/debug level and should be ignored."""
        message: str = log.get("message", "").strip()
        labels: Dict[str, Any] = log.get("labels", {})

        # 1. Check labels
        for k, v in labels.items():
            if k.lower() in ("level", "severity", "loglevel"):
                v_lower = str(v).lower()
                if v_lower in INFO_LEVELS:
                    return True
                if v_lower in ERROR_LEVELS:
                    return False

        # 2. Try JSON parsing
        try:
            parsed_json = json.loads(message)
            if isinstance(parsed_json, dict):
                for key in ("level", "severity", "loglevel"):
                    if key in parsed_json:
                        val = str(parsed_json[key]).lower()
                        if val in ERROR_LEVELS:
                            return False
                        if val in INFO_LEVELS:
                            return True
        except json.JSONDecodeError:
            pass

        # 3. Logfmt parsing
        logfmt_pattern = r'([a-zA-Z0-9_.-]+)=((?:[^\s"\']+)|\"[^\"]*\"|\'[^\']*\')'
        logfmt_matches = dict(re.findall(logfmt_pattern, message))
        for key in ("level", "severity", "loglevel"):
            if key in logfmt_matches:
                val = logfmt_matches[key].strip("'\"").lower()
                if val in ERROR_LEVELS:
                    return False
                if val in INFO_LEVELS:
                    return True

        # 4. Bracket style: [INFO], [DEBUG]
        if re.search(r'\[(info|debug|trace|informational)\]', message, re.IGNORECASE):
            has_error = re.search(r'\[(error|warn|warning|fatal|panic|crit|critical|emerg|emergency)\]', message, re.IGNORECASE)
            if not has_error:
                return True

        # 5. Standard prefix style: INFO: or DEBUG:
        if re.search(r'\b(info|debug|trace)\s*:\s+', message, re.IGNORECASE):
            has_error_prefix = re.search(r'\b(error|warn|warning|fatal|panic|crit|critical)\s*:\s+', message, re.IGNORECASE)
            if not has_error_prefix:
                return True

        return False

    async def establish_baseline(self) -> None:
        """Initializes the baseline timestamp to the current time to avoid historical spam."""
        logger.info("Estableciendo línea base de logs para evitar falsos positivos históricos...")
        lookback_ns: int = 2 * 60 * 1_000_000_000
        start_time_ns: int = time.time_ns() - lookback_ns

        try:
            logs = await self.log_client.fetch_logs(start_ns=start_time_ns, limit=200)
            if logs:
                max_ts: int = max(log["timestamp_ns"] for log in logs)
                self.last_processed_timestamp_ns = max_ts
                dt_str: str = datetime.fromtimestamp(max_ts / 1_000_000_000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                logger.info(f"Línea base establecida. Ignorando logs anteriores a: {dt_str}")
            else:
                self.last_processed_timestamp_ns = time.time_ns()
                logger.info("No se encontraron logs recientes. Línea base fijada al tiempo actual.")
        except Exception as e:
            logger.error(f"Error al establecer línea base: {e}")
            self.last_processed_timestamp_ns = time.time_ns()

    def group_and_deduplicate(self, logs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Groups logs by container and combines identical messages."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
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

    async def run_poll_cycle(self) -> None:
        """Runs a single polling and processing cycle asynchronously."""
        logger.info("Iniciando ciclo de sondeo de logs en Docker...")
        METRICS["cycles"] += 1

        await asyncio.to_thread(self.db.auto_close_inactive_incidents)
        new_logs = await self._fetch_new_candidate_logs()
        if not new_logs:
            return

        filtered_groups = self._apply_cooldown_filter(self.group_and_deduplicate(new_logs))
        if not filtered_groups:
            self._advance_baseline(new_logs)
            return

        logs_for_ai, ignored_logs, matched_rules = self._match_rules_and_classify(filtered_groups)
        await self._process_and_save_incidents(logs_for_ai, ignored_logs, matched_rules)
        self._advance_baseline(new_logs)

    async def _fetch_new_candidate_logs(self) -> List[Dict[str, Any]]:
        query_start_ns = self.last_processed_timestamp_ns or (time.time_ns() - 60 * 1_000_000_000)
        fetched = await self.log_client.fetch_logs(start_ns=query_start_ns)
        if not fetched:
            return []

        candidates = [
            l for l in fetched
            if (not self.last_processed_timestamp_ns or l["timestamp_ns"] > self.last_processed_timestamp_ns)
            and not self._is_ignored_level(l)
        ]
        if candidates:
            logger.info(f"Detectados {len(candidates)} nuevos logs de error.")
            METRICS["errors_detected"] += len(candidates)
        return candidates

    def _apply_cooldown_filter(
        self,
        grouped_logs: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        now: float = time.time()
        filtered: Dict[str, List[Dict[str, Any]]] = {}

        for app, items in grouped_logs.items():
            valid_items = []
            for item in items:
                key = f"{app}:{item['message'][:80].strip()}"
                last_sent = self.sent_alerts.get(key, 0.0)
                if now - last_sent < self.config.cooldown_seconds:
                    logger.info(f"🔕 [Cooldown] Alerta omitida para {app} (En enfriamiento).")
                    continue
                self.sent_alerts[key] = now
                valid_items.append(item)
            if valid_items:
                filtered[app] = valid_items

        self.sent_alerts = {k: ts for k, ts in self.sent_alerts.items() if now - ts < self.config.cooldown_seconds}
        return filtered

    def _match_rules_and_classify(
        self,
        filtered_groups: Dict[str, List[Dict[str, Any]]]
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]], List[Dict[str, Any]]]:
        logs_for_ai: Dict[str, List[Dict[str, Any]]] = {}
        ignored_logs: List[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]] = []
        matched_rules: List[Dict[str, Any]] = []
        rules = self.kb.load_rules()

        for app, items in filtered_groups.items():
            for item in items:
                msg_lower = item["message"].lower()
                matched = [r for r in rules if r.get("pattern", "").lower() in msg_lower and r.get("pattern")]
                is_ignored = any(r.get("action", "ALERT").upper() == "IGNORE" for r in matched)

                if is_ignored:
                    ignored_logs.append((app, item, matched))
                else:
                    logs_for_ai.setdefault(app, []).append(item)
                    for r in matched:
                        if r not in matched_rules:
                            matched_rules.append(r)

        return logs_for_ai, ignored_logs, matched_rules

    async def _process_and_save_incidents(
        self,
        logs_for_ai: Dict[str, List[Dict[str, Any]]],
        ignored_logs: List[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]],
        matched_rules: List[Dict[str, Any]]
    ) -> None:
        analysis: Optional[str] = None
        if logs_for_ai:
            try:
                analysis = await self.gemini.analyze_logs(logs_for_ai, matched_rules)
            except Exception as ai_err:
                logger.error(f"Excepción al invocar el proveedor de IA: {ai_err}")

            if not analysis:
                analysis = "⚠️ **[ERROR DE PROVEEDOR DE IA]**\n\nNo se pudo obtener diagnóstico automatizado."
            else:
                METRICS["alerts_sent"] += 1

            for app, items in logs_for_ai.items():
                for item in items:
                    await asyncio.to_thread(self.db.register_or_recur_incident, app, item, matched_rules, analysis)

        for app, item, item_rules in ignored_logs:
            ignore_note = "🔇 **[AUTO-RESUELTO]**\n\nIncidencia silenciada automáticamente por Regla de Conocimiento."
            await asyncio.to_thread(self.db.register_or_recur_incident, app, item, item_rules, ignore_note)

    def _advance_baseline(self, logs: List[Dict[str, Any]]) -> None:
        if logs:
            max_ts = max(log["timestamp_ns"] for log in logs)
            self.last_processed_timestamp_ns = max_ts

    async def polling_loop(self) -> None:
        """Infinite polling cycle task."""
        while True:
            try:
                await self.run_poll_cycle()
            except Exception as e:
                logger.error(f"Excepción en ciclo de monitoreo: {e}", exc_info=True)

            logger.info(f"Esperando {self.config.poll_interval_seconds} segundos antes del siguiente ciclo de sondeo...")
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def start(self) -> None:
        """Starts background tasks for logging, web server, and telemetry."""
        logger.info("Iniciando Log Analyzer & DevOps Bot...")
        await self.establish_baseline()

        server = WebServer(self.config, self.db, self.log_client)
        server_task = asyncio.create_task(server.start())
        monitor_task = asyncio.create_task(self.polling_loop())

        try:
            await asyncio.gather(server_task, monitor_task)
        finally:
            await self.log_client.close()
            await self.gemini.close()
