import os
from dotenv import load_dotenv
from src.logger import logger

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
        # Excludes the bot itself, Loki, and duplicate internal_logs to prevent duplicate logging
        self.loki_query = os.getenv("LOKI_QUERY", '{job=~".+", container_name!="ai-devops-bot", container_name!="loki", container_name!="internal_logs", job!="internal_logs"} |~ "(?i)(error|fatal|panic)" !~ "LogAnalyzerBot"')
        
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
