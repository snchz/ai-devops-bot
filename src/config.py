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
        # Also filters out level=info and level=debug logs to avoid false positives
        self.loki_query = os.getenv("LOKI_QUERY", r'{job=~".+", container_name!="ai-devops-bot", container_name!="loki", container_name!="internal_logs", job!="internal_logs"} |~ "(?i)(error|fatal|panic)" !~ "LogAnalyzerBot" !~ "(?i)level=\"?info\"?\b" !~ "(?i)level=\"?debug\"?\b"')
        
        # Log Format Configuration
        self.log_format = os.getenv("LOG_FORMAT", "TEXT").upper().strip()
        
        # AI Provider Selection
        self.ai_provider = os.getenv("AI_PROVIDER", "groq").lower().strip()
        if self.ai_provider not in ["groq", "gemini", "ollama"]:
            logger.warning(f"AI_PROVIDER '{self.ai_provider}' no es válido. Usando 'groq' por defecto.")
            self.ai_provider = "groq"

        # IA (Groq) Configuration
        self.groq_api_key = os.getenv("GROQ_API_KEY", os.getenv("GEMINI_API_KEY", ""))
        model = os.getenv("GEMINI_MODEL", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
        # Auto-map Gemini model strings to standard Groq Llama model for seamless migration
        if "gemini" in model or "google/" in model:
            model = "llama-3.3-70b-versatile"
        self.groq_model = model

        # IA (Google Gemini) Configuration
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", os.getenv("GROQ_API_KEY", ""))
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # IA (Ollama) Configuration
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3")

        # Validate AI Key
        if self.ai_provider == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY (o GEMINI_API_KEY) es obligatorio para el proveedor 'groq'.")
        elif self.ai_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY (o GROQ_API_KEY) es obligatorio para el proveedor 'gemini'.")
        

        # Alert Fatigue / Cooldown Configuration (Default 15 minutes)
        try:
            self.cooldown_seconds = int(os.getenv("COOLDOWN_MINUTES", "15")) * 60
        except ValueError:
            logger.warning("COOLDOWN_MINUTES no es un número válido. Usando valor por defecto: 15m")
            self.cooldown_seconds = 15 * 60

        # Healthcheck and Metrics Server Port (Default 8000)
        try:
            self.healthcheck_port = int(os.getenv("HEALTHCHECK_PORT", "8000"))
        except ValueError:
            logger.warning("HEALTHCHECK_PORT no es un número válido. Usando valor por defecto: 8000")
            self.healthcheck_port = 8000

        # Database path
        self.db_path = os.getenv("DATABASE_PATH", "data/history.db")
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)


