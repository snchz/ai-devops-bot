# AI DevOps Log Monitor & Analyzer Bot 🤖🪵🧠

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Docker Slim](https://img.shields.io/badge/docker-slim--3.11-cyan.svg)](https://hub.docker.com/_/python)
[![IA Groq](https://img.shields.io/badge/AI-Groq%20Llama%203.3-orange.svg)](https://groq.com/)
[![Grafana Loki](https://img.shields.io/badge/Loki-Logs-red.svg)](https://grafana.com/oss/loki/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Alerts-blue.svg)](https://core.telegram.org/bots)

Una herramienta de nivel **Senior DevOps** diseñada para monitorizar de forma inteligente los logs gestionados en **Grafana Loki**, analizar anomalías y errores críticos mediante la inteligencia artificial ultra-rápida de **Meta Llama 3.3 (70B) en Groq**, y enviar diagnósticos precisos junto con soluciones inmediatas y comandos de consola formateados en Markdown directo a tu canal o chat de **Telegram**.

---

## 🏗️ Flujo de Trabajo y Arquitectura CI/CD

```mermaid
graph TD
    A[Local Git Commit & Push] -->|1. Push to main| B[GitHub Actions CI/CD]
    B -->|2. Compila y publica| C[GitHub Container Registry (GHCR)]
    D[Tu Servidor: Watchtower] -->|3. Escanea cambios en GHCR| C
    C -.->|4. Actualiza imagen e inicia| E[Stack de Dockge: ai-devops-bot]
    F[Grafana Loki] -->|5. Sondeo cada X seg| E
    E -->|6. Filtra duplicados y auto-bucles| E
    E -->|7. Diagnóstico en Lote| G[Groq API (Llama 3.3)]
    G -->|8. Solución e instrucciones| E
    E -->|9. Notificación en Markdown| H[Telegram API]
```

1.  **Integración Continua (CI)**: Cada vez que haces un `git push` a `main`, una GitHub Action compila el `Dockerfile` y publica la imagen en `ghcr.io` como pública de forma segura (sin credenciales).
2.  **Despliegue Continuo (CD)**: Tu contenedor **Watchtower** escanea el registro, descarga la nueva imagen al vuelo y reinicia el bot de forma transparente y automática.
3.  **Sondeo Antibucles e Ingestión**: El bot realiza peticiones periódicas a Loki. Aplica un filtro LogQL avanzado para **ignorar sus propios logs y los logs de auditoría de Loki**, evitando bucles de retroalimentación infinita.
4.  **Deduplicación en Memoria**: Mantiene en memoria el timestamp en nanosegundos del último log procesado. Compensa el retraso de ingesta de Loki consultando una ventana de seguridad en el pasado, discriminando duplicados en memoria.
5.  **Análisis por IA de Groq (Llama 3.3)**: Envía los logs agrupados en lotes (batching) a la API ultrarrápida de Groq. El modelo de Llama 3.3 de 70B actúa como un sysadmin experto, formateando la causa, solución paso a paso y comandos listos para copiar.

---

## ✨ Características Principales

*   **Sin dependencias pesadas**: Llamadas HTTP nativas ultraligeras (`requests`).
*   **Prevención de Auto-Alertas**: Filtro anti-bucles inteligente que ignora los logs generados por el bot y las consultas repetitivas del querier de Loki.
*   **Filtro Antispam de Arranque**: Establece una línea base con los logs de los últimos 5 minutos al iniciar para evitar alertas masivas sobre fallos históricos del servidor.
*   **Telemetría Verbosa (`LOG_LEVEL`)**: Configura el nivel de detalle (`INFO` o `DEBUG`) directamente desde el archivo `.env` en Dockge sin modificar el código.
*   **Compatibilidad Hacia Atrás**: Mapea automáticamente variables antiguas de Gemini hacia el motor de Groq de forma transparente.

---

## 📂 Archivos en el Repositorio

El proyecto consta de la siguiente estructura limpia de archivos:

1.  **[`bot.py`](file:///d:/Aplicaciones/ai-devops-bot/bot.py)**: El script principal modular con conector HTTP a Groq, control robusto de errores y deduplicación.
2.  **[`requirements.txt`](file:///d:/Aplicaciones/ai-devops-bot/requirements.txt)**: Lista minimalista de requerimientos para Python (`requests` y `python-dotenv`).
3.  **[`Dockerfile`](file:///d:/Aplicaciones/ai-devops-bot/Dockerfile)**: Dockerfile seguro y optimizado con ejecución no root.
4.  **[`docker-compose.yml`](file:///d:/Aplicaciones/ai-devops-bot/docker-compose.yml)**: Configuración lista para orquestar y desplegar con Dockge o docker-compose.
5.  **[`.github/workflows/docker-publish.yml`](file:///d:/Aplicaciones/ai-devops-bot/.github/workflows/docker-publish.yml)**: Flujo CI/CD automatizado para compilar y subir a GHCR.
6.  **[`.env.example`](file:///d:/Aplicaciones/ai-devops-bot/.env.example)**: Plantilla con los campos de configuración vacíos.
7.  **[`README.md`](file:///d:/Aplicaciones/ai-devops-bot/README.md)**: Esta documentación completa del proyecto.

---

## ⚙️ Configuración (Variables de Entorno)

Crea tu archivo `.env` en Dockge basándote en esta estructura:

```env
# Configuración de Grafana Loki
LOKI_URL=http://192.168.0.5:3100
# Opcional: Credenciales para Basic Auth en Loki (dejar en blanco si no se requiere)
LOKI_USER=
LOKI_PASSWORD=
# Opcional: Query personalizada de Loki (Excluye por defecto al bot y a Loki para evitar bucles)
# LOKI_QUERY={job=~".+", container_name!="ai-devops-bot", container_name!="loki"} |~ "(?i)(error|fatal|panic)" !~ "LogAnalyzerBot"

# Configuración de la Inteligencia Artificial (Groq API)
# Puedes usar tanto GROQ_API_KEY como GEMINI_API_KEY
GROQ_API_KEY=gsk_tu_clave_de_groq_aqui
# Opcional: Modelo de Groq a utilizar (por defecto llama-3.3-70b-versatile)
GROQ_MODEL=llama-3.3-70b-versatile

# Configuración de Telegram Bot
TELEGRAM_BOT_TOKEN=tu_telegram_bot_token_aqui
TELEGRAM_CHAT_ID=tu_telegram_chat_id_o_canal_aqui

# Configuración del Monitor
POLL_INTERVAL_SECONDS=60
# Opcional: Nivel de detalle de logs (INFO o DEBUG)
LOG_LEVEL=INFO
```

---

## 🚀 Guías de Despliegue

### Opción A: Ejecución Local en Desarrollo

1.  **Clonar el repositorio**:
    ```bash
    git clone https://github.com/snchz/ai-devops-bot.git
    cd ai-devops-bot
    ```
2.  **Crear y activar un entorno virtual**:
    ```bash
    python -m venv venv
    # En Windows:
    .\venv\Scripts\activate
    # En Linux/macOS:
    source venv/bin/activate
    ```
3.  **Instalar dependencias y ejecutar**:
    ```bash
    pip install -r requirements.txt
    python bot.py
    ```

---

### Opción B: Despliegue en Dockge (Con compilación Local)

Si deseas compilar la imagen localmente en el servidor:

1.  **Clonar en el directorio de stacks de tu servidor**:
    ```bash
    cd /opt/stacks
    git clone git@github.com:snchz/ai-devops-bot.git ai-devops-bot
    ```

2.  **Configurar docker-compose.yml**:
    ```yaml
    services:
      ai-devops-bot:
        build:
          context: .
          dockerfile: Dockerfile
        container_name: ai-devops-bot
        restart: unless-stopped
        env_file:
          - .env
        volumes:
          - ./knowledge_base.json:/app/knowledge_base.json:ro
    ```

3.  **Iniciar en Dockge**:
    *   Abre la web de **Dockge** y verás el stack `ai-devops-bot` inactivo.
    *   Haz clic en él, pulsa **Edit**, añade tus credenciales en el apartado **`.env`** y haz clic en **Save** y luego en **Active**.

---

### Opción C: Despliegue Profesional de CI/CD (GitHub Actions + Watchtower)

Este es el flujo definitivo automatizado que compila en la nube y se despliega solo:

#### Paso 1: Subir tus archivos a GitHub
Realiza el `git push` de tu repositorio local. Esto disparará automáticamente la GitHub Action configurada en `.github/workflows/docker-publish.yml` que compilará y subirá la imagen a GitHub Packages.
```bash
git add .
git commit -m "feat: add groq and github actions ci-cd"
git push
```

#### Paso 2: Hacer la imagen pública
1.  Ve a tu perfil de GitHub en la web -> **Packages** -> **ai-devops-bot**.
2.  Haz clic en **Package settings** (columna derecha).
3.  Bajo **Change visibility**, selecciónalo como **Public** (Público) y guarda. *(Es seguro ya que las credenciales van en tu `.env` local, no en la imagen).*

#### Paso 3: Configurar en Dockge
Abre **Dockge** y edita tu archivo `docker-compose.yml` para usar la imagen compilada en lugar de construirla localmente:

```yaml
version: "3.8"

services:
  ai-devops-bot:
    image: ghcr.io/snchz/ai-devops-bot:latest
    container_name: ai-devops-bot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./knowledge_base.json:/app/knowledge_base.json:ro
```

Haz clic en **Save** y luego en **Active**. 

#### Paso 4: Dejar que Watchtower trabaje
Dado que tienes **Watchtower** ejecutándose en tu servidor, este revisará periódicamente tu GitHub Packages. En cuanto detecte que has subido un cambio a GitHub, descargará la nueva imagen automáticamente y reiniciará tu contenedor de `ai-devops-bot` de forma transparente.

---

## 📄 Licencia

Este proyecto está bajo la licencia MIT.

Desarrollado y mantenido con 💻 por **[snchz](https://github.com/snchz)**.
