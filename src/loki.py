import re
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from src.config import Config
from src.logger import logger

class LokiClient:
    """Client to query Grafana Loki HTTP API."""
    
    def __init__(self, config: Config):
        self.base_url = config.loki_url
        self.query = config.loki_query
        self.auth = None
        if config.loki_user and config.loki_password:
            self.auth = (config.loki_user, config.loki_password)
            
    def fetch_logs(self, start_ns: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
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
                        
                        # Strip ANSI color escape codes to make it readable and allow perfect deduplication
                        clean_message = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', log_message.strip())
                        
                        all_logs.append({
                            "timestamp_ns": ts_ns,
                            "labels": stream_labels,
                            "message": clean_message,
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
