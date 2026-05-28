#!/usr/bin/env python3
"""
AI Log Monitor & Analyzer Bot
------------------------------
Monitors Grafana Loki for errors, analyzes them with Meta Llama 3.3 (70B)
via the ultra-fast Groq API (100% free and EU-compatible), and alerts Telegram.

Author: Senior DevOps & Python Developer
Language: Python 3.11+
"""

import os
import time
import logging
import sys
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
        self.loki_query = os.getenv("LOKI_QUERY", '{job=~".+"} |~ "(?i)(error|fatal|panic)"')
        
        # IA (Groq) Configuration
        # Backwards compatible: load from GROQ_API_KEY or fallback to GEMINI_API_KEY to avoid forcing .env renames
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


class LokiClient:
    """Client to query Grafana Loki HTTP API."""
    
    def __init__(self, config: Config):
        self.base_url = config.loki_url
        self.query = config.loki_query
        self.auth = None
        if config.loki_user and config.loki_password:
            self.auth = (config.loki_user, config.loki_password)
            
    def fetch_logs(self, start_ns: Optional[int] = None, limit: int = 250) -> List[Dict[str, Any]]:
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


class GeminiClient:
    """Client to interact with Groq API using Llama 3.3 70B."""
    
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

    def analyze_logs(self, logs: List[Dict[str, Any]]) -> Optional[str]:
        """Sends logs to Groq for diagnostic analysis."""
        if not self.api_key:
            logger.error("API Key de Groq vacía. Saltando análisis.")
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
            logger.info(f"Enviando {len(logs)} logs a Groq ({self.model_name}) para su diagnóstico...")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
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
        
    def send_alert(self, logs: List[Dict[str, Any]], analysis: str) -> bool:
        """Formats and sends a markdown alert message containing the errors and the Gemini diagnostic."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
        logs_summary_lines = []
        for idx, log in enumerate(logs[:5], 1):
            job = log["labels"].get("job", "desconocido")
            short_message = log["message"][:120] + "..." if len(log["message"]) > 120 else log["message"]
            logs_summary_lines.append(f"• *Job:* `{job}` | `{short_message}`")
            
        if len(logs) > 5:
            logs_summary_lines.append(f"• _y {len(logs) - 5} logs de error adicionales..._")
            
        logs_summary = "\n".join(logs_summary_lines)
        
        message = (
            f"🚨 **ALERTAS DE LOG DETECTADAS** 🚨\n\n"
            f"Se han agrupado *{len(logs)}* errores nuevos en esta iteración:\n"
            f"{logs_summary}\n\n"
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
        self.last_processed_timestamp_ns: Optional[int] = None

    def establish_baseline(self):
        """Queries Loki for the last 5 minutes to find the most recent log timestamp to avoid historical spam."""
        logger.info("Estableciendo línea base de logs para evitar falsos positivos históricos...")
        
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
        logger.info("Iniciando ciclo de son sondeo en Grafana Loki...")
        
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
        
        analysis = self.gemini.analyze_logs(new_logs)
        
        if not analysis:
            logger.error("No se pudo obtener el análisis de Gemini. Se reintentará en el próximo ciclo.")
            return
            
        telegram_sent = self.telegram.send_alert(new_logs, analysis)
        
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
