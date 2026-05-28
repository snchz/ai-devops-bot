import requests
from typing import Dict, List, Any
from src.config import Config
from src.logger import logger

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
