import os
import httpx
from typing import Dict, List, Any, Optional, Final
from src.config import Config
from src.logger import logger

GROQ_API_URL: Final[str] = os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
GEMINI_API_URL_TEMPLATE: Final[str] = os.getenv(
    "GEMINI_API_URL_TEMPLATE",
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)


class GeminiClient:
    """Client to interact with AI Providers (Groq, Google Gemini, Ollama) asynchronously."""

    def __init__(self, config: Config) -> None:
        self.ai_provider: str = config.ai_provider
        self.groq_api_key: Optional[str] = config.groq_api_key
        self.groq_model: str = config.groq_model
        self.gemini_api_key: Optional[str] = config.gemini_api_key
        self.gemini_model: str = config.gemini_model
        self.ollama_url: str = config.ollama_url
        self.ollama_model: str = config.ollama_model
        self.client: httpx.AsyncClient = httpx.AsyncClient(timeout=45.0)

        self.system_instruction: str = (
            "Actúa como un Ingeniero DevOps y Administrador de Sistemas Linux, Docker y Docker Compose Senior "
            "altamente experimentado. Tu tarea es analizar logs de error, diagnosticar causas probables "
            "y ofrecer soluciones técnicas rápidas, precisas y eficientes.\n\n"
            "Reglas críticas para tus respuestas:\n"
            "1. Asume SIEMPRE que el entorno es Linux con Docker, Docker Compose y Dockge. Prioriza SIEMPRE comandos de 'docker', 'docker compose' y herramientas estándar de Linux en lugar de Kubernetes o kubectl, a menos que los logs demuestren explícitamente lo contrario.\n"
            "2. Sé extremadamente directo y conciso. Ve al grano.\n"
            "3. Proporciona la 'Causa Probable' en 1 o 2 frases claras.\n"
            "4. Proporciona la 'Solución' paso a paso.\n"
            "5. Proporciona comandos de consola listos para ejecutar bajo bloques de código bash (ej: 'docker logs', 'docker restart', etc.). Evita marcadores de posición imposibles de rellenar.\n"
            "6. Usa emojis apropiados y formatea la salida únicamente en Markdown estándar.\n\n"
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

    async def analyze_logs(
        self,
        grouped_logs: Dict[str, List[Dict[str, Any]]],
        matched_rules: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Sends grouped logs and custom injected solutions to selected AI provider for analysis."""
        prompt: str = self._build_prompt(grouped_logs, matched_rules)

        if self.ai_provider == "groq":
            return await self._analyze_groq(prompt)
        if self.ai_provider == "gemini":
            return await self._analyze_gemini(prompt)
        if self.ai_provider == "ollama":
            return await self._analyze_ollama(prompt)

        logger.error(f"AI Provider no soportado: {self.ai_provider}")
        return None

    def _build_prompt(
        self,
        grouped_logs: Dict[str, List[Dict[str, Any]]],
        matched_rules: List[Dict[str, Any]]
    ) -> str:
        prompt_lines: List[str] = [
            "Se han detectado los siguientes logs de error agrupados por contenedor en el sistema:\n"
        ]

        for app, items in grouped_logs.items():
            prompt_lines.append(f"📦 [Contenedor / App: {app}]")
            for idx, item in enumerate(items[:5], 1):
                clean_msg = item['message'].strip()
                if len(clean_msg) > 500:
                    clean_msg = clean_msg[:250] + "\n... [TRUNCADO PARA BREVEDAD] ...\n" + clean_msg[-250:]
                prompt_lines.append(
                    f"  Log #{idx} (ocurrencias en este ciclo: {item['count']}):\n"
                    f"  Fecha: {item['datetime']}\n"
                    f"  Mensaje original:\n  {clean_msg}\n"
                )
            prompt_lines.append("-" * 30 + "\n")

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
        return "\n".join(prompt_lines)

    async def _analyze_groq(self, prompt: str) -> Optional[str]:
        if not self.groq_api_key:
            logger.error("API Key de Groq vacía. Saltando análisis.")
            return None

        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload: Dict[str, Any] = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt}
            ]
        }

        try:
            logger.info(f"Enviando lote de logs a Groq ({self.groq_model}) para su diagnóstico...")
            response = await self.client.post(GROQ_API_URL, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"Error devuelto por la API de Groq ({response.status_code}): {response.text}")
                return None

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                logger.error(f"Respuesta inesperada de Groq: {data}")
                return None
            return choices[0].get("message", {}).get("content", "")
        except httpx.RequestError as err:
            logger.error(f"Error de red al conectar con Groq: {err}")
            return None

    async def _analyze_gemini(self, prompt: str) -> Optional[str]:
        if not self.gemini_api_key:
            logger.error("API Key de Gemini vacía. Saltando análisis.")
            return None

        url: str = GEMINI_API_URL_TEMPLATE.format(model=self.gemini_model, key=self.gemini_api_key)
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": self.system_instruction}]},
            "generationConfig": {"temperature": 0.2}
        }

        try:
            logger.info(f"Enviando lote de logs a Google Gemini ({self.gemini_model}) para su diagnóstico...")
            response = await self.client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"Error devuelto por la API de Gemini ({response.status_code}): {response.text}")
                return None

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                logger.error(f"Respuesta inesperada de Gemini: {data}")
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                logger.error(f"Respuesta sin parts en candidate de Gemini: {data}")
                return None
            return parts[0].get("text", "")
        except httpx.RequestError as err:
            logger.error(f"Error de red al conectar con Gemini: {err}")
            return None

    async def _analyze_ollama(self, prompt: str) -> Optional[str]:
        url: str = f"{self.ollama_url}/v1/chat/completions"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        payload: Dict[str, Any] = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }

        try:
            logger.info(f"Enviando lote de logs a Ollama ({self.ollama_model}) en {self.ollama_url}...")
            response = await self.client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"Error devuelto por la API de Ollama ({response.status_code}): {response.text}")
                return None

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                logger.error(f"Respuesta inesperada de Ollama: {data}")
                return None
            return choices[0].get("message", {}).get("content", "")
        except httpx.RequestError as err:
            logger.error(f"Error de red al conectar con Ollama: {err}")
            return None

    async def close(self) -> None:
        """Closes the underlying HTTP client session safely."""
        try:
            await self.client.aclose()
        except httpx.HTTPError as err:
            logger.debug(f"Error closing HTTP client: {err}")
