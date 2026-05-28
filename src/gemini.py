import requests
from typing import Dict, List, Any, Optional
from src.config import Config
from src.logger import logger

class GeminiClient:
    """Client to interact with Groq API using Llama 3.3 70B with RAG capabilities."""
    
    def __init__(self, config: Config):
        self.api_key = config.groq_api_key
        self.model_name = config.groq_model
        
        # System instructions to configure Llama as an expert DevOps/sysadmin
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
        logger.info(f"Cliente de Inteligencia Artificial (Groq) inicializado con el modelo {self.model_name}.")

    def analyze_logs(self, grouped_logs: Dict[str, List[Dict[str, Any]]], matched_rules: List[Dict[str, Any]]) -> Optional[str]:
        """Sends grouped logs and custom injected solutions to Groq for analysis."""
        if not self.api_key:
            logger.error("API Key de Groq vacía. Saltando análisis.")
            return None
            
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
        
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt}
            ]
        }
        
        try:
            logger.info(f"Enviando lote de logs a Groq ({self.model_name}) para su diagnóstico...")
            response = requests.post(url, headers=headers, json=payload, timeout=40)
            
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
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de red al conectar con Groq: {e}")
            return None
        except Exception as e:
            logger.error(f"Excepción inesperada en GeminiClient: {e}")
            return None
        
