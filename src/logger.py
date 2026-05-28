import os
import sys
import logging
import json
from dotenv import load_dotenv

# Setup logging dynamically based on environment
load_dotenv()
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)
log_format = os.getenv("LOG_FORMAT", "TEXT").upper().strip()

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
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
logger = logging.getLogger("LogAnalyzerBot")

# Global thread-safe metrics dictionary for health/metrics server
METRICS = {
    "cycles": 0,
    "errors_detected": 0,
    "alerts_sent": 0,
    "commands_executed": 0
}

