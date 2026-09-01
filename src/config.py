import os
from pathlib import Path
from typing import List, Optional, Final
from dotenv import load_dotenv
from src.logger import logger

DEFAULT_SOCKET: Final[str] = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
DEFAULT_IGNORED: Final[str] = "ai-devops-bot,dozzle,cadvisor,node-exporter,homepage,dockge-dockge-1"


class Config:
    """Manages and validates configuration loaded from environment variables."""

    def __init__(self) -> None:
        load_dotenv()
        self.docker_socket: str = DEFAULT_SOCKET
        self.docker_url: str = os.getenv("DOCKER_URL", "").rstrip("/")
        self.ignored_containers: List[str] = self._parse_ignored()
        self.log_format: str = os.getenv("LOG_FORMAT", "TEXT").upper().strip()

        self._init_ai_config()
        self._init_operational_config()
        self._init_database_config()

    @staticmethod
    def _parse_ignored() -> List[str]:
        raw: str = os.getenv("IGNORED_CONTAINERS", DEFAULT_IGNORED)
        return [c.strip() for c in raw.split(",") if c.strip()]

    def _init_ai_config(self) -> None:
        provider: str = os.getenv("AI_PROVIDER", "groq").lower().strip()
        if provider not in ("groq", "gemini", "ollama"):
            logger.warning(f"AI_PROVIDER '{provider}' no es válido. Usando 'groq' por defecto.")
            provider = "groq"
        self.ai_provider: str = provider

        # Groq
        self.groq_api_key: str = os.getenv("GROQ_API_KEY", os.getenv("GEMINI_API_KEY", ""))
        model: str = os.getenv("GEMINI_MODEL", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
        if "gemini" in model or "google/" in model:
            model = "llama-3.3-70b-versatile"
        self.groq_model: str = model

        # Gemini
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", os.getenv("GROQ_API_KEY", ""))
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # Ollama
        self.ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3")

        self._validate_ai_keys()

    def _validate_ai_keys(self) -> None:
        if self.ai_provider == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY es obligatorio para el proveedor 'groq'.")
        if self.ai_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY es obligatorio para el proveedor 'gemini'.")

    def _init_operational_config(self) -> None:
        try:
            self.cooldown_seconds: int = int(os.getenv("COOLDOWN_MINUTES", "15")) * 60
        except ValueError:
            logger.warning("COOLDOWN_MINUTES no es un número válido. Usando valor por defecto: 15m")
            self.cooldown_seconds = 15 * 60

        try:
            self.healthcheck_port: int = int(os.getenv("HEALTHCHECK_PORT", "8000"))
        except ValueError:
            logger.warning("HEALTHCHECK_PORT no es un número válido. Usando valor por defecto: 8000")
            self.healthcheck_port = 8000

        try:
            self.poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
        except ValueError:
            self.poll_interval_seconds = 30

    def _init_database_config(self) -> None:
        self.db_path: str = os.getenv("DATABASE_PATH", "data/history.db")
        db_path_obj = Path(self.db_path)
        if db_path_obj.parent:
            db_path_obj.parent.mkdir(parents=True, exist_ok=True)
