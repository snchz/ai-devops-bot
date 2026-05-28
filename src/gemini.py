import httpx
from typing import Dict, List, Any, Optional
from src.config import Config
from src.logger import logger

class GeminiClient:
    """Client to interact with AI Providers (Groq, Google Gemini, Ollama) asynchronously."""
    
    def __init__(self, config: Config):
        self.ai_provider = config.ai_provider
        
        # Groq Config
        self.groq_api_key = config.groq_api_key
        self.groq_model = config.groq_model
        
        # Gemini Config
        self.gemini_api_key = config.gemini_api_key
        self.gemini_model = config.gemini_model
        
        # Ollama Config
        self.ollama_url = config.ollama_url
        self.ollama_model = config.ollama_model
        
        # System instructions to configure LLM as an expert DevOps/sysadmin
        self.system_instruction = (
            "Actúa como un Ingeniero DevOps y Administrador de Sistemas Linux/Kubernetes Senior "
            "altamente experimentado. Tu tarea es analizar logs de error, diagnosticar causas probables "
            "y ofrecer soluciones técnicas rápidas, precisas y eficientes.\n\n"
            "Reglas críticas para tus respuestas:\n"
            "1. Sé extremadamente directo y conciso. Ve al grano.\n"
            "2. Proporciona la 'Causa Probable' en 1 o 2 frases claras.\n"
            "3. Proporciona la 'Solución' paso a paso.\n"
            "4. Proporciona comandos de consola listos para ejecutar bajo bloques de código bash.\n"
            "5. Usa emojis apropiados y formatea la salida únicamente en Markdown estándar.\n\n"
            "Estructura obligatoria de tu respuesta:\n"
            "⚠️ **ANÁLISIS DE ERROR**\n"
            "- **Causa Probable**: [Explicación corta]\n"
            "- **Solución**: [Instrucciones claras]\n"
            "- **Comandos de Solución**:\n"
            "```bash\n"
            "[Comandos para diagnosticar o reparar]\n"
            "```"
        )
        logger.info(f"Cliente de Inteligencia Artificial inicializado con el proveedor '{self.ai_provider}'.")

    async def analyze_logs(self, grouped_logs: Dict[str, List[Dict[str, Any]]], matched_rules: List[Dict[str, Any]]) -> Optional[str]:
        """Sends grouped logs and custom injected solutions to selected AI provider for analysis."""
        # Format the log collection into a clean, structured prompt
        prompt_lines = [
            "Se han detectado los siguientes logs de error agrupados por contenedor en el sistema:\n"
        ]
        
        for app, items in grouped_logs.items():
            prompt_lines.append(f"📦 [Contenedor / App: {app}]")
            for idx, item in enumerate(items, 1):
                prompt_lines.append(
                    f"  Log #{idx} (ocurrencias en este ciclo: {item['count']}):\n"
                    f"  Fecha: {item['datetime']}\n"
                    f"  Mensaje original:\n  {item['message']}\n"
                )
            prompt_lines.append("-" * 30 + "\n")
            
        # Inject custom knowledge rules if found
        if matched_rules:
            prompt_lines.append(
                "🚨 [NOTAS DE CONOCIMIENTO PREVIO DEL ADMINISTRADOR - PRIORIDAD MÁXIMA]\n"
                "Para algunos de los errores encontrados, ya conocemos el diagnóstico exacto y la solución preferida del Administrador. "
                "Por favor, INCORPORA estas soluciones y comandos de forma prioritaria en tu respuesta final:\n"
            )
            for rule in matched_rules:
                prompt_lines.append(
                    f"• Patrón coincidente: '{rule['pattern']}'\n"
                    f"  - Diagnóstico conocido: {rule.get('cause', 'N/A')}\n"
                    f"  - Solución recomendada por el Admin: {rule.get('solution', 'N/A')}\n"
                    f"  - Comandos exactos a sugerir: \n  ```bash\n  {rule.get('commands', '')}\n  ```\n"
                )
            prompt_lines.append("\nPor favor, respeta estrictamente estas notas e incorpóralas en el bloque de comandos y solución.")
            
        prompt_lines.append(
            "\nAnaliza estos logs. Si los errores están correlacionados, proporciona una solución conjunta. "
            "Limítate estrictamente al formato solicitado."
        )
        
        prompt = "\n".join(prompt_lines)
        
        # Route to the appropriate provider
        if self.ai_provider == "groq":
            return await self._analyze_groq(prompt)
        elif self.ai_provider == "gemini":
            return await self._analyze_gemini(prompt)
        elif self.ai_provider == "ollama":
            return await self._analyze_ollama(prompt)
        else:
            logger.error(f"AI Provider no soportado: {self.ai_provider}")
            return None

    async def _analyze_groq(self, prompt: str) -> Optional[str]:
        if not self.groq_api_key:
            logger.error("API Key de Groq vacía. Saltando análisis.")
            return None
            
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt}
            ]
        }
        
        try:
            logger.info(f"Enviando lote de logs a Groq ({self.groq_model}) para su diagnóstico...")
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code != 200:
                logger.error(f"Error devuelto por la API de Groq ({response.status_code}): {response.text}")
                return None
                
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                logger.error(f"Respuesta inesperada de Groq (sin choices): {data}")
                return None
                
            analysis = choices[0].get("message", {}).get("content", "")
            return analysis
            
        except httpx.RequestError as e:
            logger.error(f"Error de red al conectar con Groq: {e}")
            return None
        except Exception as e:
            logger.error(f"Excepción inesperada al invocar Groq: {e}")
            return None

    async def _analyze_gemini(self, prompt: str) -> Optional[str]:
        if not self.gemini_api_key:
            logger.error("API Key de Gemini vacía. Saltando análisis.")
            return None
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": self.system_instruction}]
            },
            "generationConfig": {
                "temperature": 0.2
            }
        }
        
        try:
            logger.info(f"Enviando lote de logs a Google Gemini ({self.gemini_model}) para su diagnóstico...")
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(url, headers=headers, json=payload)
                
            if response.status_code != 200:
                logger.error(f"Error devuelto por la API de Gemini ({response.status_code}): {response.text}")
                return None
                
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                logger.error(f"Respuesta inesperada de Gemini (sin candidates): {data}")
                return None
                
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                logger.error(f"Respuesta inesperada de Gemini (sin parts en el candidate): {data}")
                return None
                
            analysis = parts[0].get("text", "")
            return analysis
            
        except httpx.RequestError as e:
            logger.error(f"Error de red al conectar con Gemini: {e}")
            return None
        except Exception as e:
            logger.error(f"Excepción inesperada al invocar Gemini: {e}")
            return None

    async def _analyze_ollama(self, prompt: str) -> Optional[str]:
        url = f"{self.ollama_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }
        
        try:
            logger.info(f"Enviando lote de logs a Ollama ({self.ollama_model}) en {self.ollama_url} para su diagnóstico...")
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(url, headers=headers, json=payload)
                
            if response.status_code != 200:
                logger.error(f"Error devuelto por la API de Ollama ({response.status_code}): {response.text}")
                return None
                
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                logger.error(f"Respuesta inesperada de Ollama (sin choices): {data}")
                return None
                
            analysis = choices[0].get("message", {}).get("content", "")
            return analysis
            
        except httpx.RequestError as e:
            logger.error(f"Error de red al conectar con Ollama: {e}")
            return None
        except Exception as e:
            logger.error(f"Excepción inesperada al invocar Ollama: {e}")
            return None
        
