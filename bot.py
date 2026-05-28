#!/usr/bin/env python3
"""
AI Log Monitor & Analyzer Bot - Entrypoint (Async Edition)
------------------------------------------
Imports modules from the `src` package and starts the polling loop asynchronously.

Author: snchz
"""

import sys
import asyncio
from src.logger import logger
from src.config import Config
from src.monitor import LogMonitor

async def main():
    config = Config()
    monitor = LogMonitor(config)
    await monitor.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as e:
        logger.critical(f"Error de configuración al arrancar el bot: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario (KeyboardInterrupt). Saliendo...")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Error catastrófico al iniciar la aplicación: {e}", exc_info=True)
        sys.exit(1)
