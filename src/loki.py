import re
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from src.config import Config
from src.logger import logger

class LokiClient:
    """Client to query Grafana Loki HTTP API asynchronously."""
    
    def __init__(self, config: Config):
        self.base_url = config.loki_url
        self.query = config.loki_query
        self.auth = None
        if config.loki_user and config.loki_password:
            self.auth = httpx.BasicAuth(config.loki_user, config.loki_password)
            
    async def fetch_logs(self, start_ns: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
        """Queries /loki/api/v1/query_range asynchronously."""
        url = f"{self.base_url}/loki/api/v1/query_range"
        
        params: Dict[str, Any] = {
            "query": self.query,
            "limit": limit
        }
        
        if start_ns:
            params["start"] = str(start_ns)
            
        try:
            logger.debug(f"Consultando Loki a través de: {url} con start={start_ns}")
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, params=params, auth=self.auth)
            
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
            
        except httpx.RequestError as e:
            logger.error(f"Error de red al conectar con Loki en {url}: {type(e).__name__} - {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Excepción inesperada en LokiClient: {e}")
            return []

    async def fetch_context_logs(self, app_name: str, target_ts_ns: int, window_minutes: int = 5) -> List[Dict[str, Any]]:
        """Queries /loki/api/v1/query_range for a specific app without error filtering to get the full context."""
        url = f"{self.base_url}/loki/api/v1/query_range"
        
        # Build query for specific container or job
        query = f'{{container_name="{app_name}"}} |~ ".*"'
        
        half_window_ns = int((window_minutes * 60 / 2) * 1_000_000_000)
        start_ns = target_ts_ns - half_window_ns
        end_ns = target_ts_ns + half_window_ns
        
        params: Dict[str, Any] = {
            "query": query,
            "limit": 1000,
            "start": str(start_ns),
            "end": str(end_ns)
        }
        
        try:
            logger.debug(f"Consultando Loki contexto para {app_name} en {url}")
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, params=params, auth=self.auth)
            
            if response.status_code != 200:
                # Fallback to job if container_name doesn't match
                query = f'{{job="{app_name}"}} |~ ".*"'
                params["query"] = query
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(url, params=params, auth=self.auth)
                
                if response.status_code != 200:
                    logger.error(f"Error devolviendo contexto Loki ({response.status_code}): {response.text}")
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
                        
                        clean_message = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', log_message.strip())
                        
                        all_logs.append({
                            "timestamp_ns": ts_ns,
                            "labels": stream_labels,
                            "message": clean_message,
                            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                        })
                    except (ValueError, IndexError):
                        continue
                        
            all_logs.sort(key=lambda x: x["timestamp_ns"])
            return all_logs
            
        except httpx.RequestError as e:
            logger.error(f"Error de red al conectar con Loki en {url}: {type(e).__name__} - {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Excepción inesperada al consultar contexto en LokiClient: {e}")
            return []
