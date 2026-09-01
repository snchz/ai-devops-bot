import os
import sys
import logging
import json
from typing import Dict, Any
from dotenv import load_dotenv

# Setup logging dynamically based on environment
load_dotenv()
log_level_str: str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level: int = getattr(logging, log_level_str, logging.INFO)
log_format: str = os.getenv("LOG_FORMAT", "TEXT").upper().strip()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


handler = logging.StreamHandler(sys.stdout)
if log_format == "JSON":
    handler.setFormatter(JsonFormatter())
else:
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

logging.basicConfig(
    level=log_level,
    handlers=[handler]
)
logger: logging.Logger = logging.getLogger("LogAnalyzerBot")

# Silence verbose background HTTP polling from the httpx library
logging.getLogger("httpx").setLevel(logging.WARNING)

# Global metrics dictionary for health/metrics server
METRICS: Dict[str, int] = {
    "cycles": 0,
    "errors_detected": 0,
    "alerts_sent": 0,
    "commands_executed": 0
}
