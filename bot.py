#!/usr/bin/env python3
"""
AI Log Monitor & Analyzer Bot
------------------------------
Monitors Grafana Loki for errors, analyzes them with Google Gemini (1.5-flash),
and sends actionable solutions to a Telegram chat.

Author: Senior DevOps & Python Developer
Language: Python 3.11+
"""

import os
import time
import logging
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import urllib.parse

import requests
from dotenv import load_dotenv
import google.generativeai as genai

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("LogAnalyzerBot")


class Config:
    """Manages and validates configuration loaded from environment variables."""
    
    def __init__(self):
        # Load environment variables from .env if present
        load_dotenv()
        
        # Loki Configuration
        self.loki_url = os.getenv("LOKI_URL", "").rstrip("/")
        if not self.loki_url:
            raise ValueError("LOKI_URL es obligatorio en la configuración.")
            
        self.loki_user = os.getenv("LOKI_USER", None)
        self.loki_password = os.getenv("LOKI_PASSWORD", None)
        
        # Loki Query: default matches errors, fatals, and panics across all jobs
        self.loki_query = os.getenv("LOKI_QUERY", '{job=~".*"} |~ "(?i)(error|fatal|panic)"')
        
        # Gemini Configuration
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY es obligatorio en la configuración.")
            
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


class LokiClient:
    """Client to query Grafana Loki HTTP API."""
    
    def __init__(self, config: Config):
        self.base_url = config.loki_url
        self.query = config.loki_query
        self.auth = None
        if config.loki_user and config.loki_password:
            self.auth = (config.loki_user, config.loki_password)
            
    def fetch_logs(self, start_ns: Optional[int] = None, limit: int = 250) -> List[Dict[str, Any]]:
        """
        Queries /loki/api/v1/query_range.
        
        Args:
            start_ns: Optional Unix nanosecond timestamp to fetch logs from.
            limit: Max log lines to return in query.
            
        Returns:
            A list of dictionary log objects sorted chronologically:
            [ { 'timestamp_ns': int, 'labels': dict, 'message': str, 'datetime': str }, ... ]
        """
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
                        
            # Sort globally by timestamp (Loki returns grouped streams which may overlap in time)
            all_logs.sort(key=lambda x: x["timestamp_ns"])
            return all_logs
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de red al conectar con Loki en {url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Excepción inesperada en LokiClient: {e}")
            return []


class GeminiClient:
    """Client to interact with Google Generative AI (Gemini)."""
    
    def __init__(self, config: Config):
        genai.configure(api_key=config.gemini_api_key)
        
        # System instructions to configure Gemini as an expert DevOps/sysadmin
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
        
        try:
            self.model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=self.system_instruction
            )
            logger.info("Cliente de Gemini inicializado correctamente con el modelo gemini-1.5-flash.")
        except Exception as e:
            logger.error(f"Error al inicializar el modelo de Gemini: {e}")
            self.model = None

    def analyze_logs(self, logs: List[Dict[str, Any]]) -> Optional[str]:
        """Sends logs to Gemini for diagnostic analysis."""
        if not self.model:
            logger.error("El modelo de Gemini no está inicializado. Saltando análisis.")
            return None
            
        # Format the log collection into a clear, structured prompt
        prompt_lines = [
            f"Se han detectado los siguientes {len(logs)} logs de error en el sistema para tu análisis y resolución:\n"
        ]
        
        for idx, log in enumerate(logs, 1):
            job = log["labels"].get("job", "desconocido")
            prompt_lines.append(
                f"--- ERROR #{idx} ---\n"
                f"Fecha: {log['datetime']}\n"
                f"Trabajo/Job: {job}\n"
                f"Labels: {log['labels']}\n"
                f"Log original:\n{log['message']}\n"
            )
            
        prompt_lines.append(
            "\nAnaliza estos logs. Si los errores están correlacionados, "
            "proporciona una solución conjunta. Limítate estrictamente al formato solicitado."
        )
        
        prompt = "\n".join(prompt_lines)
        
        try:
            logger.info(f"Enviando {len(logs)} logs a Gemini para su diagnóstico...")
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Error al llamar a la API de Gemini: {e}")
            return None


class TelegramClient:
    """Client to send notifications to Telegram API."""
    
    def __init__(self, config: Config):
        self.token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        
    def send_alert(self, logs: List[Dict[str, Any]], analysis: str) -> bool:
        """
        Formats and sends a markdown alert message containing the errors and the Gemini diagnostic.
        
        Args:
            logs: The list of raw logs processed in this batch.
            analysis: The Markdown string response returned by Gemini.
            
        Returns:
            True if sent successfully, False otherwise.
        """
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
        # Create a clean summary of the errors to attach in the Telegram message header
        logs_summary_lines = []
        for idx, log in enumerate(logs[:5], 1):
            job = log["labels"].get("job", "desconocido")
            # Truncate long log messages for visual neatness in Telegram
            short_message = log["message"][:120] + "..." if len(log["message"]) > 120 else log["message"]
            logs_summary_lines.append(f"• *Job:* `{job}` | `{short_message}`")
            
        if len(logs) > 5:
            logs_summary_lines.append(f"• _y {len(logs) - 5} logs de error adicionales..._")
            
        logs_summary = "\n".join(logs_summary_lines)
        
        # Build the final premium message template
        message = (
            f"🚨 **ALERTAS DE LOG DETECTADAS** 🚨\n\n"
            f"Se han agrupado *{len(logs)}* errores nuevos en esta iteración:\n"
            f"{logs_summary}\n\n"
            f"{analysis}"
        )
        
        # Ensure we don't exceed Telegram's message character limit of 4096 bytes
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
    """Orchestrator to poll Loki, process logs, get suggestions from Gemini, and alert via Telegram."""
    
    def __init__(self, config: Config):
        self.config = config
        self.loki = LokiClient(config)
        self.gemini = GeminiClient(config)
        self.telegram = TelegramClient(config)
        
        # In-memory storage for the timestamp of the last processed log (in nanoseconds)
        self.last_processed_timestamp_ns: Optional[int] = None

    def establish_baseline(self):
        """
        Executes on startup. Queries Loki for the last 5 minutes to find the most recent log timestamp.
        This establishes a baseline so we avoid analyzing or spamming historical errors when the bot restarts.
        """
        logger.info("Estableciendo línea base de logs para evitar falsos positivos históricos...")
        
        # Lookback window for baseline: 5 minutes in nanoseconds
        lookback_ns = 5 * 60 * 1_000_000_000
        start_time_ns = (time.time_ns()) - lookback_ns
        
        logs = self.loki.fetch_logs(start_ns=start_time_ns, limit=500)
        
        if logs:
            max_ts = max(log["timestamp_ns"] for log in logs)
            self.last_processed_timestamp_ns = max_ts
            dt_str = datetime.fromtimestamp(max_ts / 1_000_000_000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            logger.info(f"Línea base establecida. Ignorando logs anteriores a: {dt_str} (TS: {max_ts})")
        else:
            self.last_processed_timestamp_ns = time.time_ns()
            logger.info(f"No se encontraron logs recientes. Línea base fijada al tiempo actual del sistema: {self.last_processed_timestamp_ns}")

    def run_poll_cycle(self):
        """Runs a single polling and processing cycle."""
        logger.info("Iniciando ciclo de sondeo en Grafana Loki...")
        
        # Query logs since the last processed timestamp
        # To handle ingestion delays, we query Loki from (last_processed_timestamp_ns - 2 minutes)
        # but filter strictly in memory using (timestamp > last_processed_timestamp_ns)
        safety_window_ns = 2 * 60 * 1_000_000_000
        query_start_ns = self.last_processed_timestamp_ns - safety_window_ns
        
        fetched_logs = self.loki.fetch_logs(start_ns=query_start_ns)
        
        if not fetched_logs:
            logger.info("No se recibieron logs de Loki en este ciclo.")
            return

        # Filtering step: only logs strictly newer than last_processed_timestamp_ns
        new_logs = [log for log in fetched_logs if log["timestamp_ns"] > self.last_processed_timestamp_ns]
        
        if not new_logs:
            logger.info("No hay nuevos logs de error desde la última iteración.")
            return
            
        logger.info(f"Detectados {len(new_logs)} nuevos logs de error.")
        
        # Analyze using Gemini
        analysis = self.gemini.analyze_logs(new_logs)
        
        if not analysis:
            logger.error("No se pudo obtener el análisis de Gemini. Se reintentará en el próximo ciclo.")
            return
            
        # Alert using Telegram
        telegram_sent = self.telegram.send_alert(new_logs, analysis)
        
        if telegram_sent:
            # Update last processed timestamp to prevent reprocessing
            max_ts = max(log["timestamp_ns"] for log in new_logs)
            self.last_processed_timestamp_ns = max_ts
            logger.info(f"Ciclo completado. Último timestamp actualizado a: {max_ts}")
        else:
            logger.warning("Fallo el envío a Telegram. No se actualiza el timestamp para reintentar en el próximo ciclo.")

    def start(self):
        """Starts the infinite polling loop."""
        logger.info("Iniciando Bot de Monitoreo de Logs con Gemini...")
        
        # Establish startup baseline
        try:
            self.establish_baseline()
        except Exception as e:
            logger.error(f"Error crítico al establecer la línea base en el arranque: {e}")
            self.last_processed_timestamp_ns = time.time_ns()
            logger.info(f"Fijando timestamp de seguridad al tiempo actual por fallo: {self.last_processed_timestamp_ns}")
            
        # Infinite Loop with robust error capturing to maintain container health
        while True:
            try:
                self.run_poll_cycle()
            except Exception as e:
                # Catch-all exception so the container/process never crashes on transient faults
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
