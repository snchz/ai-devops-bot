import os
import json
import urllib.parse
import asyncio
from typing import Dict, Any, List, Optional
from src.logger import logger, METRICS
from src.database import Database

class WebServer:
    """Lightweight, fully asynchronous, dependency-free HTTP server for metrics, healthcheck, and Web UI REST APIs."""
    
    def __init__(self, port: int, db: Database, kb_path: str):
        self.port = port
        self.db = db
        self.kb_path = kb_path
        
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
                "# HELP ai_devops_bot_alerts_sent_total Total alerts successfully sent to Telegram",
                "# TYPE ai_devops_bot_alerts_sent_total counter",
                f"ai_devops_bot_alerts_sent_total {METRICS['alerts_sent']}",
                "# HELP ai_devops_bot_commands_executed_total Total commands executed via Telegram buttons",
                "# TYPE ai_devops_bot_commands_executed_total counter",
                f"ai_devops_bot_commands_executed_total {METRICS['commands_executed']}"
            ]
            resp_body = ("\n".join(metrics_lines) + "\n").encode("utf-8")
            writer.write(self._make_response(200, "OK", "text/plain; version=0.0.4", resp_body))
            await writer.drain()
            return
            
        # 2. REST API: INCIDENTS HISTORY
        elif path == "/api/incidents" and method == "GET":
            limit = int(query_params.get("limit", "100"))
            incidents = self.db.get_incidents(limit)
            resp_body = json.dumps(incidents, ensure_ascii=False).encode("utf-8")
            writer.write(self._make_response(200, "OK", "application/json", resp_body))
            await writer.drain()
            return
            
        elif path.startswith("/api/incidents/") and method == "DELETE":
            # Extract Incident ID
            try:
                incident_id = int(path.split("/")[-1])
                success = self.db.delete_incident(incident_id)
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

        # 3. REST API: KNOWLEDGE BASE RULES
        elif path == "/api/kb" and method == "GET":
            rules = []
            if os.path.exists(self.kb_path):
                try:
                    with open(self.kb_path, "r", encoding="utf-8") as f:
                        rules = json.load(f)
                except Exception as e:
                    logger.error(f"Error al leer base de conocimientos en API: {e}")
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
                
                # Check for editing a rule (we pass `original_pattern` in payload if we are editing)
                original_pattern = payload.get("original_pattern", "").strip()
                
                if not pattern or not solution:
                    resp_body = b'{"error": "pattern and solution are required"}'
                    writer.write(self._make_response(400, "Bad Request", "application/json", resp_body))
                    await writer.drain()
                    return
                    
                rules = []
                if os.path.exists(self.kb_path):
                    try:
                        with open(self.kb_path, "r", encoding="utf-8") as f:
                            rules = json.load(f)
                    except Exception:
                        pass
                
                updated = False
                
                # If we are editing, look for the original pattern
                search_pattern = original_pattern if original_pattern else pattern
                
                for rule in rules:
                    if rule.get("pattern", "").lower() == search_pattern.lower():
                        # Update fields
                        rule["pattern"] = pattern
                        rule["description"] = description
                        rule["cause"] = cause
                        rule["solution"] = solution
                        rule["commands"] = commands
                        updated = True
                        break
                        
                if not updated:
                    # Append new rule
                    rules.append({
                        "pattern": pattern,
                        "description": description,
                        "cause": cause,
                        "solution": solution,
                        "commands": commands
                    })
                    
                # Write back safely
                with open(self.kb_path, "w", encoding="utf-8") as f:
                    json.dump(rules, f, indent=2, ensure_ascii=False)
                    
                logger.info(f"💾 Regla de conocimiento guardada vía Web UI: '{pattern}'")
                resp_body = b'{"success": true}'
                writer.write(self._make_response(200, "OK", "application/json", resp_body))
                
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
                
            rules = []
            if os.path.exists(self.kb_path):
                try:
                    with open(self.kb_path, "r", encoding="utf-8") as f:
                        rules = json.load(f)
                except Exception:
                    pass
                    
            original_len = len(rules)
            rules = [r for r in rules if r.get("pattern", "").lower() != pattern_to_del.lower()]
            
            if len(rules) < original_len:
                with open(self.kb_path, "w", encoding="utf-8") as f:
                    json.dump(rules, f, indent=2, ensure_ascii=False)
                logger.info(f"🗑️ Regla de conocimiento eliminada vía Web UI: '{pattern_to_del}'")
                resp_body = b'{"success": true}'
                writer.write(self._make_response(200, "OK", "application/json", resp_body))
            else:
                resp_body = b'{"error": "Pattern not found"}'
                writer.write(self._make_response(404, "Not Found", "application/json", resp_body))
            await writer.drain()
            return

        # 4. STATIC FILE WEB SERVER
        else:
            # Map '/' to '/index.html'
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
                # Guess content type
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
                    # Async read in standard loop thread
                    with open(full_file_path, "rb") as f:
                        file_content = f.read()
                    writer.write(self._make_response(200, "OK", c_type, file_content))
                except Exception as file_err:
                    logger.error(f"Error leyendo archivo estático {clean_path}: {file_err}")
                    writer.write(self._make_response(500, "Internal Server Error", "text/plain", b"Error reading file"))
            else:
                # File not found
                writer.write(self._make_response(404, "Not Found", "text/plain", b"File Not Found"))
            await writer.drain()
            return

    async def start(self):
        """Starts the server listener on the specified port."""
        try:
            # Create web folder if it doesn't exist (to avoid server crashing)
            if not os.path.exists(self.web_dir):
                os.makedirs(self.web_dir, exist_ok=True)
                
            server = await asyncio.start_server(self.handle_client, "0.0.0.0", self.port)
            logger.info(f"🌐 Servidor Web asíncrono y API corriendo activamente en: http://0.0.0.0:{self.port}")
            async with server:
                await server.serve_forever()
        except Exception as e:
            logger.error(f"❌ No se pudo iniciar el Servidor Web en el puerto {self.port}: {e}", exc_info=True)
