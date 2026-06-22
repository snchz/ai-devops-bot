import os
import json
import urllib.parse
import asyncio
from typing import Dict, Any, List, Optional
from src.logger import logger, METRICS
from src.database import Database
from src.config import Config
from src.loki import LokiClient

class WebServer:
    """Lightweight, fully asynchronous, dependency-free HTTP server for metrics, healthcheck, and Web UI REST APIs."""
    
    def __init__(self, config: Config, db: Database):
        self.config = config
        self.port = config.healthcheck_port
        self.db = db
        self.loki = LokiClient(config)
        
        # Absolute path to the web folder
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.web_dir = os.path.join(base_dir, "web")
        
    def _make_response(self, status: int, status_text: str, content_type: str, body: bytes) -> bytes:
        """Helper to create standardized HTTP responses with CORS enabled."""
        headers = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: {content_type}; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS\r\n"
            "Access-Control-Allow-Headers: Content-Type\r\n\r\n"
        )
        return headers.encode("utf-8") + body

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Processes an incoming HTTP connection asynchronously."""
        try:
            header_data = b""
            # Read request headers (delimited by double CRLF)
            while True:
                line = await reader.readline()
                if not line:
                    break
                header_data += line
                if b"\r\n\r\n" in header_data or len(header_data) > 8192:
                    break
                    
            if not header_data:
                return
                
            request_text = header_data.decode("utf-8", errors="ignore")
            lines = request_text.split("\r\n")
            if not lines:
                return
                
            req_line = lines[0]
            parts = req_line.split(" ")
            if len(parts) < 2:
                return
                
            method, raw_path = parts[0], parts[1]
            method = method.upper()
            
            # Parse path and query parameters
            path = raw_path
            query_params = {}
            if "?" in raw_path:
                path, query_str = raw_path.split("?", 1)
                for pair in query_str.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        query_params[urllib.parse.unquote(k)] = urllib.parse.unquote(v)
            
            # Parse Content-Length for body reading
            content_length = 0
            for line in lines:
                if line.lower().startswith("content-length:"):
                    try:
                        content_length = int(line.split(":")[1].strip())
                        # Safety limit to prevent memory overflow (OOM)
                        if content_length > 2 * 1024 * 1024:
                            content_length = 2 * 1024 * 1024
                    except ValueError:
                        pass
                        
            # Read body if content length exists
            body = b""
            if content_length > 0:
                try:
                    body = await reader.readexactly(content_length)
                except Exception as body_err:
                    logger.error(f"Error al leer el cuerpo de la petición: {body_err}")
            
            # Handle CORS preflight
            if method == "OPTIONS":
                writer.write(self._make_response(204, "No Content", "text/plain", b""))
                await writer.drain()
                return

            # Route requests
            await self.route_request(writer, method, path, query_params, body)
            
        except Exception as e:
            logger.error(f"Error procesando petición web: {e}", exc_info=True)
            # Fallback error response
            try:
                err_res = self._make_response(500, "Internal Server Error", "application/json", b'{"error": "Internal Server Error"}')
                writer.write(err_res)
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def route_request(self, writer: asyncio.StreamWriter, method: str, path: str, query_params: Dict[str, str], body: bytes):
        """Asynchronous router for files and APIs."""
        
        # 1. Healthcheck & Metrics (100% backward compatible)
        if path == "/healthz" and method == "GET":
            resp_body = b'{"status": "healthy"}'
            writer.write(self._make_response(200, "OK", "application/json", resp_body))
            await writer.drain()
            return
            
        elif path == "/metrics" and method == "GET":
            metrics_lines = [
                "# HELP ai_devops_bot_cycles_total Total polling cycles completed",
                "# TYPE ai_devops_bot_cycles_total counter",
                f"ai_devops_bot_cycles_total {METRICS['cycles']}",
                "# HELP ai_devops_bot_errors_detected_total Total raw error logs fetched",
                "# TYPE ai_devops_bot_errors_detected_total counter",
                f"ai_devops_bot_errors_detected_total {METRICS['errors_detected']}",
                "# HELP ai_devops_bot_alerts_sent_total Total alerts successfully generated",
                "# TYPE ai_devops_bot_alerts_sent_total counter",
                f"ai_devops_bot_alerts_sent_total {METRICS['alerts_sent']}",
                "# HELP ai_devops_bot_commands_executed_total Total commands executed via Web UI buttons",
                "# TYPE ai_devops_bot_commands_executed_total counter",
                f"ai_devops_bot_commands_executed_total {METRICS['commands_executed']}"
            ]
            resp_body = ("\n".join(metrics_lines) + "\n").encode("utf-8")
            writer.write(self._make_response(200, "OK", "text/plain; version=0.0.4", resp_body))
            await writer.drain()
            return
            
        elif path == "/api/version" and method == "GET":
            # Attempt to read VERSION file in root directory
            version = "unknown"
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            version_path = os.path.join(root_dir, "VERSION")
            if os.path.exists(version_path):
                try:
                    with open(version_path, "r") as f:
                        version = f.read().strip()
                except Exception:
                    pass
            resp_body = json.dumps({"version": version}, ensure_ascii=False).encode("utf-8")
            writer.write(self._make_response(200, "OK", "application/json", resp_body))
            await writer.drain()
            return
            
        # 2. REST API: INCIDENTS HISTORY
        elif path == "/api/incidents" and method == "GET":
            limit = int(query_params.get("limit", "100"))
            incidents = await asyncio.to_thread(self.db.get_incidents, limit)
            resp_body = json.dumps(incidents, ensure_ascii=False).encode("utf-8")
            writer.write(self._make_response(200, "OK", "application/json", resp_body))
            await writer.drain()
            return
            
        elif path.startswith("/api/incidents/") and path.endswith("/context") and method == "GET":
            try:
                incident_id = int(path.split("/")[-2])
                incident = await asyncio.to_thread(self.db.get_incident, incident_id)
                
                if not incident:
                    resp_body = b'{"error": "Incident not found"}'
                    writer.write(self._make_response(404, "Not Found", "application/json", resp_body))
                else:
                    app_name = incident["apps"][0] if incident["apps"] else ""
                    # Try to extract the actual timestamp of the log event from the stored logs dictionary
                    target_ts_ns = None
                    if isinstance(incident.get("logs"), dict):
                        # Try first with the main app name
                        if app_name and app_name in incident["logs"]:
                            app_logs = incident["logs"][app_name]
                            if isinstance(app_logs, list) and len(app_logs) > 0 and isinstance(app_logs[0], dict):
                                target_ts_ns = app_logs[0].get("timestamp_ns")
                        # Fallback to any app log timestamp in the dictionary
                        if target_ts_ns is None:
                            for logs_list in incident["logs"].values():
                                if isinstance(logs_list, list) and len(logs_list) > 0 and isinstance(logs_list[0], dict):
                                    target_ts_ns = logs_list[0].get("timestamp_ns")
                                    if target_ts_ns is not None:
                                        break
                    
                    if target_ts_ns is None:
                        # Fallback to created_at timestamp
                        target_ts_ns = int(incident["created_at"]) * 1_000_000_000
                    
                    logs = await self.loki.fetch_context_logs(app_name, target_ts_ns, window_minutes=5)
                    resp_body = json.dumps(logs, ensure_ascii=False).encode("utf-8")
                    writer.write(self._make_response(200, "OK", "application/json", resp_body))
            except ValueError:
                resp_body = b'{"error": "Invalid incident ID"}'
                writer.write(self._make_response(400, "Bad Request", "application/json", resp_body))
            except Exception as ex:
                resp_body = f'{{"error": "{str(ex)}"}}'.encode("utf-8")
                writer.write(self._make_response(500, "Internal Server Error", "application/json", resp_body))
            await writer.drain()
            return
            
        elif path.startswith("/api/incidents/") and path.endswith("/resolve") and method == "POST":
            # Resolve incident endpoint
            try:
                incident_id = int(path.split("/")[-2])
                payload = json.loads(body.decode("utf-8"))
                
                kb_rule = payload.get("kb_rule")
                if not kb_rule:
                    pattern = payload.get("kb_pattern", "")
                    rules = await asyncio.to_thread(self.db.get_kb_rules)
                    kb_rule = next((r for r in rules if r["pattern"].lower() == pattern.lower()), None)
                    
                if not kb_rule:
                    resp_body = b'{"error": "Knowledge Base rule not found"}'
                    writer.write(self._make_response(404, "Not Found", "application/json", resp_body))
                    await writer.drain()
                    return
                    
                success = await asyncio.to_thread(self.db.resolve_incident, incident_id, kb_rule)
                if success:
                    resp_body = b'{"success": true}'
                    writer.write(self._make_response(200, "OK", "application/json", resp_body))
                else:
                    resp_body = b'{"error": "Incident not found"}'
                    writer.write(self._make_response(404, "Not Found", "application/json", resp_body))
            except ValueError:
                resp_body = b'{"error": "Invalid incident ID"}'
                writer.write(self._make_response(400, "Bad Request", "application/json", resp_body))
            except Exception as ex:
                resp_body = f'{{"error": "{str(ex)}"}}'.encode("utf-8")
                writer.write(self._make_response(500, "Internal Server Error", "application/json", resp_body))
            await writer.drain()
            return
            
        elif path.startswith("/api/incidents/") and method == "DELETE":
            # Check if deleting all
            if path == "/api/incidents/all":
                success = await asyncio.to_thread(self.db.delete_all_incidents)
                if success:
                    resp_body = b'{"success": true}'
                    writer.write(self._make_response(200, "OK", "application/json", resp_body))
                else:
                    resp_body = b'{"error": "Failed to delete all incidents"}'
                    writer.write(self._make_response(500, "Internal Server Error", "application/json", resp_body))
                await writer.drain()
                return

            # Extract Incident ID
            try:
                incident_id = int(path.split("/")[-1])
                success = await asyncio.to_thread(self.db.delete_incident, incident_id)
                if success:
                    resp_body = b'{"success": true}'
                    writer.write(self._make_response(200, "OK", "application/json", resp_body))
                else:
                    resp_body = b'{"error": "Incident not found"}'
                    writer.write(self._make_response(404, "Not Found", "application/json", resp_body))
            except ValueError:
                resp_body = b'{"error": "Invalid incident ID"}'
                writer.write(self._make_response(400, "Bad Request", "application/json", resp_body))
            await writer.drain()
            return

        # 3. REST API: SETTINGS
        elif path == "/api/settings" and method == "GET":
            # Return specific configuration values
            settings = {
                "poll_interval_minutes": float(await asyncio.to_thread(self.db.get_setting, "poll_interval_minutes", "5.0"))
            }
            resp_body = json.dumps(settings, ensure_ascii=False).encode("utf-8")
            writer.write(self._make_response(200, "OK", "application/json", resp_body))
            await writer.drain()
            return
            
        elif path == "/api/settings" and method == "POST":
            try:
                payload = json.loads(body.decode("utf-8"))
                for key, value in payload.items():
                    await asyncio.to_thread(self.db.set_setting, key, str(value))
                resp_body = b'{"success": true}'
                writer.write(self._make_response(200, "OK", "application/json", resp_body))
            except Exception as ex:
                logger.error(f"Error procesando guardado de settings: {ex}")
                resp_body = f'{{"error": "{str(ex)}"}}'.encode("utf-8")
                writer.write(self._make_response(500, "Internal Server Error", "application/json", resp_body))
            await writer.drain()
            return

        # 4. REST API: KNOWLEDGE BASE RULES (Consolidated SQLite CRUD)
        elif path == "/api/kb" and method == "GET":
            rules = await asyncio.to_thread(self.db.get_kb_rules)
            resp_body = json.dumps(rules, ensure_ascii=False).encode("utf-8")
            writer.write(self._make_response(200, "OK", "application/json", resp_body))
            await writer.drain()
            return
            
        elif path == "/api/kb" and method == "POST":
            try:
                payload = json.loads(body.decode("utf-8"))
                pattern = payload.get("pattern", "").strip()
                description = payload.get("description", "").strip()
                cause = payload.get("cause", "").strip()
                solution = payload.get("solution", "").strip()
                commands = payload.get("commands", "").strip()
                action = payload.get("action", "ALERT").strip().upper()
                original_pattern = payload.get("original_pattern", "").strip()
                is_regex = bool(payload.get("is_regex", False))
                
                if not pattern or not solution:
                    resp_body = b'{"error": "pattern and solution are required"}'
                    writer.write(self._make_response(400, "Bad Request", "application/json", resp_body))
                    await writer.drain()
                    return
                    
                success = await asyncio.to_thread(self.db.save_kb_rule, pattern, description, cause, solution, commands, action, original_pattern, is_regex)
                if success:
                    resp_body = b'{"success": true}'
                    writer.write(self._make_response(200, "OK", "application/json", resp_body))
                else:
                    resp_body = b'{"error": "Database operation failed"}'
                    writer.write(self._make_response(500, "Internal Server Error", "application/json", resp_body))
            except Exception as ex:
                logger.error(f"Error procesando guardado de KB: {ex}")
                resp_body = f'{{"error": "{str(ex)}"}}'.encode("utf-8")
                writer.write(self._make_response(500, "Internal Server Error", "application/json", resp_body))
            await writer.drain()
            return
            
        elif path == "/api/kb" and method == "DELETE":
            # Extract target pattern from query params
            pattern_to_del = query_params.get("pattern", "").strip()
            if not pattern_to_del:
                resp_body = b'{"error": "pattern parameter is required"}'
                writer.write(self._make_response(400, "Bad Request", "application/json", resp_body))
                await writer.drain()
                return
                
            success = await asyncio.to_thread(self.db.delete_kb_rule, pattern_to_del)
            if success:
                resp_body = b'{"success": true}'
                writer.write(self._make_response(200, "OK", "application/json", resp_body))
            else:
                resp_body = b'{"error": "Pattern not found"}'
                writer.write(self._make_response(404, "Not Found", "application/json", resp_body))
            await writer.drain()
            return

        # 4. STATIC FILE WEB SERVER
        else:
            file_path_rel = path.lstrip("/")
            if not file_path_rel or file_path_rel == "":
                file_path_rel = "index.html"
                
            # Sanitize to prevent directory traversal
            clean_path = os.path.normpath(file_path_rel)
            if clean_path.startswith("..") or os.path.isabs(clean_path):
                writer.write(self._make_response(403, "Forbidden", "text/plain", b"Access Forbidden"))
                await writer.drain()
                return
                
            full_file_path = os.path.join(self.web_dir, clean_path)
            
            if os.path.exists(full_file_path) and os.path.isfile(full_file_path):
                ext = os.path.splitext(full_file_path)[1].lower()
                content_types = {
                    ".html": "text/html",
                    ".css": "text/css",
                    ".js": "application/javascript",
                    ".json": "application/json",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".svg": "image/svg+xml",
                    ".ico": "image/x-icon"
                }
                c_type = content_types.get(ext, "application/octet-stream")
                
                try:
                    with open(full_file_path, "rb") as f:
                        file_content = f.read()
                    writer.write(self._make_response(200, "OK", c_type, file_content))
                except Exception as file_err:
                    logger.error(f"Error leyendo archivo estático {clean_path}: {file_err}")
                    writer.write(self._make_response(500, "Internal Server Error", "text/plain", b"Error reading file"))
            else:
                writer.write(self._make_response(404, "Not Found", "text/plain", b"File Not Found"))
            await writer.drain()
            return

    async def start(self):
        """Starts the server listener on the specified port."""
        try:
            if not os.path.exists(self.web_dir):
                os.makedirs(self.web_dir, exist_ok=True)
                
            server = await asyncio.start_server(self.handle_client, "0.0.0.0", self.port)
            logger.info(f"🌐 Servidor Web asíncrono y API corriendo activamente en: http://0.0.0.0:{self.port}")
            async with server:
                await server.serve_forever()
        except Exception as e:
            logger.error(f"❌ No se pudo iniciar el Servidor Web en el puerto {self.port}: {e}", exc_info=True)
