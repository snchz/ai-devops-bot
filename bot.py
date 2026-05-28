#!/usr/bin/env python3
"""
AI Log Monitor & Analyzer Bot
------------------------------
Monitors Grafana Loki for errors, analyzes them with Meta Llama 3.3 (70B)
via Groq (EU-compatible, 100% free), and sends actionable solutions to Telegram.

Features:
- Application-based grouping and log deduplication with repetition counters (xN).
- Real-time Knowledge Base RAG (knowledge_base.json) for custom troubleshooting injection.
- Complete try-except resiliency to network and API drops.

Author: Senior DevOps & Python Developer
Language: Python 3.11+
"""

import os
import time
import logging
import sys
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests
from dotenv import load_dotenv

# Setup logging dynamically based on environment
load_dotenv()
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("LogAnalyzerBot")


class Config:
    """Manages and validates configuration loaded from environment variables."""
    
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Loki Configuration
        self.loki_url = os.getenv("LOKI_URL", "").rstrip("/")
        if not self.loki_url:
            raise ValueError("LOKI_URL es obligatorio en la configuración.")
            
        self.loki_user = os.getenv("LOKI_USER", None)
        self.loki_password = os.getenv("LOKI_PASSWORD", None)
        
        # Loki Query: default matches errors, fatals, and panics across non-empty jobs
        # Intelligent default ignores the bot's own logs and Loki's internal metric logs to prevent self-loops
        self.loki_query = os.getenv("LOKI_QUERY", '{job=~".+", container_name!="ai-devops-bot", container_name!="loki"} |~ "(?i)(error|fatal|panic)" !~ "LogAnalyzerBot"')
        
        # IA (Groq) Configuration
        self.groq_api_key = os.getenv("GROQ_API_KEY", os.getenv("GEMINI_API_KEY", ""))
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY (o GEMINI_API_KEY con tu clave gsk_ de Groq) es obligatorio.")
            
        model = os.getenv("GEMINI_MODEL", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
        # Auto-map Gemini model strings to standard Groq Llama model for seamless migration
        if "gemini" in model or "google/" in model:
            model = "llama-3.3-70b-versatile"
        self.groq_model = model
        
        # Telegram Configuration
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN es obligatorio en la configuración.")
            
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not self.telegram_chat_id:
            raise ValueError("TELEGRAM_CHAT_ID es obligatorio en la configuración.")
            
        # Polling Configuration (Default 60 seconds)
        try:
            self.poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
        except ValueError:
            logger.warning("POLL_INTERVAL_SECONDS no es un número válido. Usando valor por defecto: 60s")
            self.poll_interval = 60

        # Knowledge Base path
        self.kb_path = os.getenv("KNOWLEDGE_BASE_PATH", "knowledge_base.json")


class LokiClient:
    """Client to query Grafana Loki HTTP API."""
    
    def __init__(self, config: Config):
        self.base_url = config.loki_url
        self.query = config.loki_query
        self.auth = None
        if config.loki_user and config.loki_password:
            self.auth = (config.loki_user, config.loki_password)
            
    def fetch_logs(self, start_ns: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
        """Queries /loki/api/v1/query_range."""
        url = f"{self.base_url}/loki/api/v1/query_range"
        
        params: Dict[str, Any] = {
            "query": self.query,
            "limit": limit
        }
        
        if start_ns:
            params["start"] = str(start_ns)
            
        try:
            logger.debug(f"Consultando Loki a través de: {url} con start={start_ns}")
            response = requests.get(url, params=params, auth=self.auth, timeout=15)
            
            if response.status_code != 200:
                logger.error(f"Error devuelto por Loki ({response.status_code}): {response.text}")
                return []
                
            data = response.json()
            if data.get("status") != "success":
                logger.error(f"Loki reportó estado no-exitoso en la respuesta: {data}")
                return []
                
            all_logs = []
            results = data.get("data", {}).get("result", [])
            
            for res in results:
                stream_labels = res.get("stream", {})
                values = res.get("values", [])
                
                for val in values:
                    try:
                        timestamp_str, log_message = val[0], val[1]
                        ts_ns = int(timestamp_str)
                        ts_sec = ts_ns / 1_000_000_000
                        dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
                        
                        all_logs.append({
                            "timestamp_ns": ts_ns,
                            "labels": stream_labels,
                            "message": log_message.strip(),
                            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                        })
                    except (ValueError, IndexError) as err:
                        logger.warning(f"Error procesando valor de log de Loki: {err}")
                        continue
                        
            all_logs.sort(key=lambda x: x["timestamp_ns"])
            return all_logs
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de red al conectar con Loki en {url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Excepción inesperada en LokiClient: {e}")
            return []


class KnowledgeBase:
    """Manages local RAG rules loaded dynamically from a JSON file."""
    
    def __init__(self, path: str):
        self.path = path
        
    def load_rules(self) -> List[Dict[str, Any]]:
        """Loads and returns troubleshooting rules from JSON file in real-time."""
        if not os.path.exists(self.path):
            logger.debug(f"Base de conocimientos {self.path} no encontrada. Retornando lista vacía.")
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error al leer base de conocimientos en {self.path}: {e}")
            return []
            
    def match_logs(self, unique_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Matches unique error log messages against active patterns.
        Returns a list of matched rule definitions.
        """
        rules = self.load_rules()
        if not rules:
            return []
            
        matched_rules = []
        matched_patterns = set()
        
        for log in unique_logs:
            msg_lower = log["message"].lower()
            for rule in rules:
                pattern = rule.get("pattern", "").lower()
                if not pattern:
                    continue
                # If substring matches and hasn't been matched yet in this cycle
                if pattern in msg_lower and pattern not in matched_patterns:
                    matched_rules.append(rule)
                    matched_patterns.add(pattern)
                    logger.info(f"💡 [CONOCIMIENTO ENCONTRADO] El log coincide con el patrón: '{rule['pattern']}'")
                    
        return matched_rules


class GeminiClient:
    """Client to interact with Groq API using Llama 3.3 70B with RAG capabilities."""
    
    def __init__(self, config: Config):
        self.api_key = config.groq_api_key
        self.model_name = config.groq_model
        
        # System instructions to configure Llama as an expert DevOps/sysadmin
        self.system_instruction = (
            "Actúa como un Ingeniero DevOps y Administrador de Sistemas Linux/Kubernetes Senior "
            "altamente experimentado. Tu tarea es analizar logs de error, diagnosticar causas probables "
            "y ofrecer soluciones técnicas rápidas, precisas y eficientes.\n\n"
            "Reglas críticas para tus respuestas:\n"
            "1. Sé extremadamente directo y conciso. Ve al grano.\n"
            "2. Proporciona la 'Causa Probable' en 1 o 2 frases claras.\n"
            "3. Proporciona la 'Solución' paso a paso.\n"
            "4. Proporciona comandos de consola listos para ejecutar bajo bloques de código bash.\n"
            "5. Usa emojis apropiados y formatea la salida únicamente en Markdown estándar.\n\n"
            "Estructura obligatoria de tu respuesta:\n"
            "⚠️ **ANÁLISIS DE ERROR**\n"
            "- **Causa Probable**: [Explicación corta]\n"
            "- **Solución**: [Instrucciones claras]\n"
            "- **Comandos de Solución**:\n"
            "```bash\n"
            "[Comandos para diagnosticar o reparar]\n"
            "```"
        )
        logger.info(f"Cliente de Inteligencia Artificial (Groq) inicializado con el modelo {self.model_name}.")

    def analyze_logs(self, grouped_logs: Dict[str, List[Dict[str, Any]]], matched_rules: List[Dict[str, Any]]) -> Optional[str]:
        """Sends grouped logs and custom injected solutions to Groq for analysis."""
        if not self.api_key:
            logger.error("API Key de Groq vacía. Saltando análisis.")
            return None
            
        # Format the log collection into a clean, structured prompt
        prompt_lines = [
            "Se han detectado los siguientes logs de error agrupados por contenedor en el sistema:\n"
        ]
        
        for app, items in grouped_logs.items():
            prompt_lines.append(f"📦 [Contenedor / App: {app}]")
            for idx, item in enumerate(items, 1):
                prompt_lines.append(
                    f"  Log #{idx} (ocurrencias en este ciclo: {item['count']}):\n"
                    f"  Fecha: {item['datetime']}\n"
                    f"  Mensaje original:\n  {item['message']}\n"
                )
            prompt_lines.append("-" * 30 + "\n")
            
        # Inject custom knowledge rules if found
        if matched_rules:
            prompt_lines.append(
                "🚨 [NOTAS DE CONOCIMIENTO PREVIO DEL ADMINISTRADOR - PRIORIDAD MÁXIMA]\n"
                "Para algunos de los errores encontrados, ya conocemos el diagnóstico exacto y la solución preferida del Administrador. "
                "Por favor, INCORPORA estas soluciones y comandos de forma prioritaria en tu respuesta final:\n"
            )
            for rule in matched_rules:
                prompt_lines.append(
                    f"• Patrón coincidente: '{rule['pattern']}'\n"
                    f"  - Diagnóstico conocido: {rule.get('cause', 'N/A')}\n"
                    f"  - Solución recomendada por el Admin: {rule.get('solution', 'N/A')}\n"
                    f"  - Comandos exactos a sugerir: \n  ```bash\n  {rule.get('commands', '')}\n  ```\n"
                )
            prompt_lines.append("\nPor favor, respeta estrictamente estas notas e incorpóralas en el bloque de comandos y solución.")
            
        prompt_lines.append(
            "\nAnaliza estos logs. Si los errores están correlacionados, proporciona una solución conjunta. "
            "Limítate estrictamente al formato solicitado."
        )
        
        prompt = "\n".join(prompt_lines)
        
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt}
            ]
        }
        
        try:
            logger.info(f"Enviando lote de logs a Groq ({self.model_name}) para su diagnóstico...")
            response = requests.post(url, headers=headers, json=payload, timeout=40)
            
            if response.status_code != 200:
                logger.error(f"Error devuelto por la API de Groq ({response.status_code}): {response.text}")
                return None
                
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                logger.error(f"Respuesta inesperada de Groq (sin choices): {data}")
                return None
                
            analysis = choices[0].get("message", {}).get("content", "")
            return analysis
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de red al conectar con Groq: {e}")
            return None
        except Exception as e:
            logger.error(f"Excepción inesperada en GeminiClient: {e}")
            return None


class TelegramClient:
    """Client to send notifications to Telegram API."""
    
    def __init__(self, config: Config):
        self.token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        
    def send_alert(self, grouped_logs: Dict[str, List[Dict[str, Any]]], matched_rules: List[Dict[str, Any]], analysis: str) -> bool:
        """Formats and sends an aggregated markdown alert message grouped by application."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
        # Build grouped logs section
        summary_lines = []
        for app, items in grouped_logs.items():
            summary_lines.append(f"📦 *Aplicación:* `{app}`")
            # Show up to 3 unique logs per application to avoid humongous messages
            for item in items[:3]:
                count_str = f" _(x{item['count']})_" if item['count'] > 1 else ""
                short_message = item["message"][:120] + "..." if len(item["message"]) > 120 else item["message"]
                summary_lines.append(f"  • `{short_message}`{count_str}")
            if len(items) > 3:
                summary_lines.append(f"  • _y {len(items) - 3} logs de error únicos adicionales..._")
            summary_lines.append("")
            
        logs_summary = "\n".join(summary_lines)
        
        # Add Knowledge Base Badge
        kb_badge = ""
        if matched_rules:
            patterns = ", ".join(f"`{r['pattern']}`" for r in matched_rules)
            kb_badge = f"💡 *[Solución Personalizada Aplicada para: {patterns}]*\n\n"
        
        # Build the premium Telegram message
        message = (
            f"🚨 **ALERTAS DE LOG DETECTADAS** 🚨\n\n"
            f"{logs_summary}"
            f"{kb_badge}"
            f"{analysis}"
        )
        
        if len(message) > 4000:
            message = message[:3900] + "\n\n*(Alerta truncada por límite de tamaño de Telegram)*"
            
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        try:
            logger.info("Enviando reporte de diagnóstico a Telegram...")
            response = requests.post(url, json=payload, timeout=12)
            
            if response.status_code == 200:
                logger.info("Mensaje enviado exitosamente a Telegram.")
                return True
            else:
                logger.error(
                    f"Fallo al enviar mensaje a Telegram (Código {response.status_code}): {response.text}"
                )
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de red al conectar con la API de Telegram: {e}")
            return False
        except Exception as e:
            logger.error(f"Excepción inesperada al enviar alerta a Telegram: {e}")
            return False


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


if __name__ == "__main__":
    try:
        config = Config()
        monitor = LogMonitor(config)
        monitor.start()
    except ValueError as e:
        logger.critical(f"Error de configuración al arrancar el bot: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario (KeyboardInterrupt). Saliendo...")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Error catastrófico al iniciar la aplicación: {e}", exc_info=True)
        sys.exit(1)
