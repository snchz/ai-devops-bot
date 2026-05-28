import httpx
import asyncio
import uuid
from typing import Dict, List, Any, Optional
from src.config import Config
from src.logger import logger, METRICS

class TelegramClient:
    """Client to send notifications and handle bidirectional updates from Telegram asynchronously."""
    
    def __init__(self, config: Config):
        self.token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        self.telegram_allowed_user_ids = config.telegram_allowed_user_ids
        self.command_registry = {}  # In-memory mapping of cmd_id -> command/metadata

    async def send_alert(self, grouped_logs: Dict[str, List[Dict[str, Any]]], matched_rules: List[Dict[str, Any]], analysis: str) -> bool:
        """Formats and sends an aggregated markdown alert message grouped by application asynchronously."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
        # Build grouped logs section
        summary_lines = []
        for app, items in grouped_logs.items():
            summary_lines.append(f"📦 *Aplicación:* `{app}`")
            # Show up to 3 unique logs per application to avoid humongous messages
            for item in items[:3]:
                count_str = f" _(x{item['count']})_" if item['count'] > 1 else ""
                short_message = item["message"][:120] + "..." if len(item["message"]) > 120 else item["message"]
                summary_lines.append(f"  • `{short_message}`{count_str}")
            if len(items) > 3:
                summary_lines.append(f"  • _y {len(items) - 3} logs de error únicos adicionales..._")
            summary_lines.append("")
            
        logs_summary = "\n".join(summary_lines)
        
        # Add Knowledge Base Badge
        kb_badge = ""
        if matched_rules:
            patterns = ", ".join(f"`{r['pattern']}`" for r in matched_rules)
            kb_badge = f"💡 *[Solución Personalizada Aplicada para: {patterns}]*\n\n"
        
        # Build the premium Telegram message
        message = (
            f"🚨 **ALERTAS DE LOG DETECTADAS** 🚨\n\n"
            f"{logs_summary}"
            f"{kb_badge}"
            f"{analysis}"
        )
        
        if len(message) > 4000:
            message = message[:3900] + "\n\n*(Alerta truncada por límite de tamaño de Telegram)*"
            
        inline_keyboard = []
        for rule in matched_rules:
            cmd = rule.get("commands", "").strip()
            if cmd:
                cmd_id = str(uuid.uuid4())[:8]
                self.command_registry[cmd_id] = {
                    "command": cmd,
                    "pattern": rule.get("pattern", "Desconocido"),
                    "description": rule.get("description", "")
                }
                
                # Prevent memory leak by capping registry size
                if len(self.command_registry) > 100:
                    old_keys = list(self.command_registry.keys())[:-50]
                    for k in old_keys:
                        self.command_registry.pop(k, None)
                        
                inline_keyboard.append([
                    {"text": f"Ejecutar Solución ({rule['pattern']}) ⚡", "callback_data": f"exec:{cmd_id}"}
                ])
                
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
            
        try:
            logger.info("Enviando reporte de diagnóstico a Telegram...")
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                logger.info("Mensaje enviado exitosamente a Telegram.")
                METRICS["alerts_sent"] += 1
                return True
            else:
                logger.error(
                    f"Fallo al enviar mensaje a Telegram (Código {response.status_code}): {response.text}"
                )
                return False
                
        except httpx.RequestError as e:
            logger.error(f"Error de red al conectar con la API de Telegram: {e}")
            return False
        except Exception as e:
            logger.error(f"Excepción inesperada al enviar alerta a Telegram: {e}")
            return False

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> bool:
        """Edits an existing text message on Telegram."""
        url = f"https://api.telegram.org/bot{self.token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
            
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=payload)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error de red al editar mensaje en Telegram: {e}")
            return False

    async def answer_callback(self, query_id: str, text: str, show_alert: bool = False) -> bool:
        """Answers an inline callback query to dismiss loading state or show alert popups."""
        url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
        payload = {
            "callback_query_id": query_id,
            "text": text,
            "show_alert": show_alert
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=payload)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error al responder callback en Telegram: {e}")
            return False

    async def poll_updates(self):
        """Asynchronously polls Telegram for callback updates to execute interactive self-healing."""
        logger.info("Iniciando servicio de long polling para recibir interacciones de Telegram...")
        offset = 0
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        
        while True:
            try:
                params = {
                    "offset": offset,
                    "timeout": 10,
                    "allowed_updates": ["callback_query"]
                }
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(url, params=params)
                    
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        updates = data.get("result", [])
                        for update in updates:
                            offset = update["update_id"] + 1
                            if "callback_query" in update:
                                await self.handle_callback_query(update["callback_query"])
                elif response.status_code == 409:
                    # Occurs if another bot instance starts polling or webhook is set
                    logger.warning("Conflicto de Telegram Polling (409). Reintentando en 5s...")
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Error al obtener actualizaciones de Telegram ({response.status_code}): {response.text}")
                    await asyncio.sleep(5)
                    
            except httpx.RequestError as e:
                # Expected periodically on long polling timeouts
                logger.debug(f"Timeout o latencia de red en Telegram getUpdates: {e}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error crítico en el bucle de polling de Telegram: {e}", exc_info=True)
                await asyncio.sleep(2)

    async def handle_callback_query(self, query: Dict[str, Any]):
        """Processes authorized callback clicks to trigger remote commands in subprocesses securely."""
        query_id = query["id"]
        callback_data = query.get("data", "")
        message = query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        text = message.get("text", "")
        user = query.get("from", {})
        user_id = user.get("id")
        username = user.get("username", str(user_id))
        
        # Command Security Check
        if not self.telegram_allowed_user_ids:
            logger.warning("Intento de ejecución remoto cancelado: TELEGRAM_ALLOWED_USER_IDS no está configurada en el servidor.")
            await self.answer_callback(
                query_id, 
                "⚠️ Ejecución deshabilitada: Falta configurar TELEGRAM_ALLOWED_USER_IDS en el servidor.",
                show_alert=True
            )
            return
            
        if user_id not in self.telegram_allowed_user_ids:
            logger.warning(f"Intento de ejecución NO AUTORIZADO de @{username} (ID: {user_id}).")
            await self.answer_callback(
                query_id, 
                "❌ Acceso denegado: No estás autorizado para ejecutar comandos en este servidor.",
                show_alert=True
            )
            return
            
        if callback_data.startswith("exec:"):
            cmd_id = callback_data.split("exec:", 1)[1]
            cmd_info = self.command_registry.get(cmd_id)
            
            if not cmd_info:
                logger.warning(f"ID de comando solicitado no encontrado o expirado de memoria: {cmd_id}")
                await self.answer_callback(query_id, "⚠️ El comando solicitado ya no está en la memoria del bot.", show_alert=True)
                await self.edit_message_text(chat_id, message_id, text, reply_markup={"inline_keyboard": []})
                return
                
            command = cmd_info["command"]
            pattern = cmd_info["pattern"]
            
            logger.info(f"⚡ [Self-Healing] Iniciando ejecución de comando remoto para '{pattern}' solicitado por @{username}: '{command}'")
            METRICS["commands_executed"] += 1
            
            # Dismiss Telegram loading overlay
            await self.answer_callback(query_id, f"⚡ Ejecutando solución para '{pattern}'...")
            
            # Edit original message to show running state
            loading_text = text + f"\n\n⏳ *[Self-Healing]* Ejecutando comando en el servidor...\n`$ {command}`"
            await self.edit_message_text(chat_id, message_id, loading_text, reply_markup={"inline_keyboard": []})
            
            # Execute shell command safely under async subprocess
            try:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
                stdout_str = stdout.decode("utf-8", errors="ignore").strip()
                stderr_str = stderr.decode("utf-8", errors="ignore").strip()
                exit_code = process.returncode
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                stdout_str = ""
                stderr_str = "Error: El comando superó el límite de tiempo de 30 segundos."
                exit_code = -1
            except Exception as e:
                stdout_str = ""
                stderr_str = f"Error al ejecutar el comando en el servidor: {e}"
                exit_code = -2
                
            # Construct execution telemetry result block
            result_section = (
                f"\n\n⚡ **[RESULTADO DE EJECUCIÓN]** ⚡\n"
                f"👤 *Operador:* @{username}\n"
                f"💻 *Comando:* `{command}`\n"
                f"🔢 *Código de Salida:* `{exit_code}`\n"
            )
            
            if stdout_str:
                truncated_out = stdout_str[:600] + "..." if len(stdout_str) > 600 else stdout_str
                result_section += f"📥 *Salida Estándar (stdout):*\n```text\n{truncated_out}\n```\n"
            if stderr_str:
                truncated_err = stderr_str[:600] + "..." if len(stderr_str) > 600 else stderr_str
                result_section += f"⚠️ *Errores (stderr):*\n```text\n{truncated_err}\n```\n"
                
            final_text = text + result_section
            if len(final_text) > 4000:
                final_text = final_text[:3900] + "\n\n*(Salida de ejecución truncada por límite de tamaño)*"
                
            await self.edit_message_text(chat_id, message_id, final_text, reply_markup={"inline_keyboard": []})
