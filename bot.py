#!/usr/bin/env python3
"""
AI Log Monitor & Analyzer Bot - Entrypoint
------------------------------------------
Imports modules from the `src` package and starts the polling loop.

Author: snchz
"""

import sys
from src.logger import logger
from src.config import Config
from src.monitor import LogMonitor

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
