# AI DevOps Log Monitor & Analyzer Bot 🤖🪵🧠

Choose your language / Selecciona tu idioma:
*   [English Documentation 🇬🇧](#english-documentation)
*   [Documentación en Español 🇪🇸](#documentación-en-español)

---

# English Documentation

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Docker Slim](https://img.shields.io/badge/docker-slim--3.11-cyan.svg)](https://hub.docker.com/_/python)
[![AI Groq](https://img.shields.io/badge/AI-Groq%20Llama%203.3-orange.svg)](https://groq.com/)
[![Grafana Loki](https://img.shields.io/badge/Loki-Logs-red.svg)](https://grafana.com/oss/loki/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Alerts-blue.svg)](https://core.telegram.org/bots)

A **Senior DevOps** production-grade tool designed to intelligently monitor logs managed in **Grafana Loki**, analyze critical errors and anomalies using the ultra-fast **Meta Llama 3.3 (70B) AI via Groq**, and deliver highly precise diagnostics, root-cause analyses, and console-ready resolution commands formatted in Markdown directly to your **Telegram** channel or chat.

---

## 🏗️ Workflow & CI/CD Architecture

```mermaid
graph TD
    A[Local Git Commit & Push] -->|1. Push to main| B[GitHub Actions CI/CD]
    B -->|2. Build & publish| C[GitHub Container Registry (GHCR)]
    D[Your Server: Watchtower] -->|3. Scan changes in GHCR| C
    C -.->|4. Auto-update image & start| E[Dockge Stack: ai-devops-bot]
    F[Grafana Loki] -->|5. Poll every X sec| E
    E -->|6. Filter duplicates & self-loops| E
    E -->|7. Batch Diagnostic Prompt| G[Groq API Llama 3.3]
    G -->|8. Solution & console commands| E
    E -->|9. Markdown Notification| H[Telegram API]
```

1.  **Continuous Integration (CI)**: When you push to the `main` branch, a GitHub Action automatically builds the `Dockerfile` and publishes the image securely (credentials-free) to GitHub Container Registry (GHCR).
2.  **Continuous Deployment (CD)**: Your server's **Watchtower** container scans GHCR, automatically downloads the new image in the background, and restarts the bot with zero manual downtime.
3.  **Anti-Loop LogQL Filtering**: The bot queries `/loki/api/v1/query_range` periodically. It applies an advanced LogQL filter to **ignore its own container logs and Loki's internal metric queries**, preventing infinite self-matching alert loops.
4.  **In-Memory Deduplication & Cleaning**: It tracks the nanosecond-level timestamp of the last processed log. To prevent data loss from Loki ingestion pipeline delays, it polls a overlapping 2-minute safety window and dedupes duplicates in memory.
5.  **ANSI Code Stripping**: Automatically strips ANSI console color escape sequences (`\x1b\[[0-9;]*[a-zA-Z]`), producing clean Telegram Markdown and allowing perfect deduplication of identical docker log streams.
6.  **AI Local RAG (Knowledge Base)**: Parses a local `knowledge_base.json` rulebook. If an error matches a pattern (e.g. `pvpc_hourly_pricing`), it **injects your custom diagnostic notes and exact bash fix commands** directly into Llama 3.3's prompt, overriding standard AI assumptions with your specific knowledge.

---

## ✨ Main Features

*   **Zero heavy SDKs**: Lightweight, raw HTTP connections (`requests`).
*   **Anti-Self-Alerting Loops**: Advanced LogQL and regex filtering to block self-matching loops.
*   **Startup Antispam Baseline**: On startup, establishes a baseline from the last 5 minutes of logs without firing alerts, avoiding notification flooding on container restarts.
*   **Dynamic Verbose Telemetry (`LOG_LEVEL`)**: Instantly toggle log verbosity levels (`INFO` or `DEBUG`) directly from your `.env` in Dockge without touching code.
*   **Backward Compatibility**: Automatically maps older Gemini environment variables and model configurations to Groq's high-speed `llama-3.3-70b-versatile` engine.

---

## 📂 Repository Structure

The project has the following clean, modular structure:

1.  **[`bot.py`](file:///d:/Aplicaciones/ai-devops-bot/bot.py)**: Main Python script containing the configuration manager, Loki API client, Llama 3.3 Groq conector, and Telegram dispatcher.
2.  **[`requirements.txt`](file:///d:/Aplicaciones/ai-devops-bot/requirements.txt)**: Lightweight dependency definitions (`requests` and `python-dotenv`).
3.  **[`Dockerfile`](file:///d:/Aplicaciones/ai-devops-bot/Dockerfile)**: Multi-stage, slim `python:3.11-slim` container executing securely under a non-root `appuser`.
4.  **[`docker-compose.yml`](file:///d:/Aplicaciones/ai-devops-bot/docker-compose.yml)**: Composition file for Dockge, mapping service names and container mounts.
5.  **[`.github/workflows/docker-publish.yml`](file:///d:/Aplicaciones/ai-devops-bot/.github/workflows/docker-publish.yml)**: Continuous integration pipeline to build and publish to GHCR.
6.  **[`knowledge_base.json`](file:///d:/Aplicaciones/ai-devops-bot/knowledge_base.json)**: Local RAG rulebook containing custom troubleshooting matching patterns and solutions.
7.  **[`.env.example`](file:///d:/Aplicaciones/ai-devops-bot/.env.example)**: Environment template with blank placeholder fields.
8.  **[`README.md`](file:///d:/Aplicaciones/ai-devops-bot/README.md)**: This bilingual documentation file.

---

## ⚙️ Configuration (Environment Variables)

Create your `.env` file in Dockge based on the following template:

```env
# Grafana Loki Configuration
LOKI_URL=http://192.168.0.5:3100
# Optional: Loki Basic Auth Credentials (leave blank if not required)
LOKI_USER=
LOKI_PASSWORD=
# Optional: Custom Loki LogQL Query (default excludes bot, loki, and internal_logs)
# LOKI_QUERY={job=~".+", container_name!="ai-devops-bot", container_name!="loki", container_name!="internal_logs", job!="internal_logs"} |~ "(?i)(error|fatal|panic)" !~ "LogAnalyzerBot"

# Artificial Intelligence (Groq API) Configuration
# Backwards compatible: supports GROQ_API_KEY or GEMINI_API_KEY
GROQ_API_KEY=gsk_your_groq_api_key_here
# Optional: Groq model name (defaults to llama-3.3-70b-versatile)
GROQ_MODEL=llama-3.3-70b-versatile

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# Monitoring Configuration
POLL_INTERVAL_SECONDS=60
# Optional: Logging level (INFO or DEBUG)
LOG_LEVEL=INFO
```

---

## 🚀 Deployment Guides

### Option A: Local Execution (Development)

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/snchz/ai-devops-bot.git
    cd ai-devops-bot
    ```
2.  **Create and activate a virtual environment**:
    ```bash
    python -m venv venv
    # On Windows:
    .\venv\Scripts\activate
    # On Linux/macOS:
    source venv/bin/activate
    ```
3.  **Install dependencies and run**:
    ```bash
    pip install -r requirements.txt
    python bot.py
    ```

---

### Option B: Local Compilation on Dockge

1.  **Clone the repository in your server's stacks directory**:
    ```bash
    cd /opt/stacks
    git clone git@github.com:snchz/ai-devops-bot.git ai-devops-bot
    ```
2.  **Verify `docker-compose.yml` mounts**:
    Make sure your compose file includes the volume mount to reload rules dynamically:
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
3.  **Start Stack in Dockge**:
    *   Open your **Dockge** web UI. Refresh, select `ai-devops-bot` under **Inactive** sidebar.
    *   Click **Edit**, configure your `.env` on the right side, click **Save**, and click **Active**.

---

### Option C: Professional CI/CD Deployment (GitHub Actions + Watchtower)

This is the recommended production workflow: builds in the cloud and auto-deploys on your server.

#### Step 1: Push code to GitHub
Run `git push` from your local machine. This triggers the GitHub Action which compiles the Dockerfile and publishes it to GHCR.
```bash
git add .
git commit -m "feat: add groq and github actions ci-cd"
git push
```

#### Step 2: Set the package to Public
1.  Go to your GitHub Profile -> **Packages** -> **ai-devops-bot**.
2.  Click **Package settings** (right sidebar).
3.  Under **Change visibility**, change it to **Public** and save. *(Completely secure, credentials stay in your server's local `.env`)*.

#### Step 3: Configure in Dockge
Change your compose file to use the compiled package image rather than building it locally:

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
Click **Save**, then **Active**.

#### Step 4: Let Watchtower do the magic
Since you have **Watchtower** running, it will automatically poll GHCR. When it detects your push triggered a new image build, Watchtower pulls it in the background and restarts `ai-devops-bot` transparently.

---
---

# Documentación en Español

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
    E -->|7. Diagnóstico en Lote| G[Groq API Llama 3.3]
    G -->|8. Solución e instrucciones| E
    E -->|9. Notificación en Markdown| H[Telegram API]
```

1.  **Integración Continua (CI)**: Cada vez que haces un `git push` a `main`, una GitHub Action compila el `Dockerfile` y publica la imagen en `ghcr.io` como pública de forma segura (sin credenciales).
2.  **Despliegue Continuo (CD)**: Tu contenedor **Watchtower** escanea el registro, descarga la nueva imagen al vuelo y reinicia el bot de forma transparente y automática.
3.  **Sondeo Antibucles e Ingestión**: El bot realiza peticiones periódicas a Loki. Aplica un filtro LogQL avanzado para **ignorar sus propios logs y los logs de auditoría de Loki**, evitando bucles de retroalimentación infinita.
4.  **Deduplicación en Memoria**: Mantiene en memoria el timestamp en nanosegundos del último log procesado. Compensa el retraso de ingesta de Loki consultando una ventana de seguridad en el pasado, discriminando duplicados en memoria.
5.  **Limpiador de códigos ANSI**: Limpia automáticamente los códigos de escape de color de consola ANSI (`\x1b\[[0-9;]*[a-zA-Z]`) de los logs, produciendo un Markdown de Telegram muy limpio y permitiendo una deduplicación perfecta de las trazas de Docker.
6.  **IA Local RAG (Base de Conocimientos)**: Parsea una base de conocimientos local `knowledge_base.json`. Si un error coincide con un patrón (ej. `pvpc_hourly_pricing`), **inyecta tus notas de diagnóstico y tus comandos bash de solución preferidos** en el prompt de Llama 3.3 de forma prioritaria.

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
6.  **[`knowledge_base.json`](file:///d:/Aplicaciones/ai-devops-bot/knowledge_base.json)**: Archivo JSON local de RAG que lista patrones, diagnósticos conocidos y comandos específicos de reparación.
7.  **[`.env.example`](file:///d:/Aplicaciones/ai-devops-bot/.env.example)**: Plantilla con los campos de configuración vacíos.
8.  **[`README.md`](file:///d:/Aplicaciones/ai-devops-bot/README.md)**: Este archivo de documentación bilingüe.

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
# LOKI_QUERY={job=~".+", container_name!="ai-devops-bot", container_name!="loki", container_name!="internal_logs", job!="internal_logs"} |~ "(?i)(error|fatal|panic)" !~ "LogAnalyzerBot"

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
    Asegúrate de incluir el montaje del volumen de conocimientos para recarga en caliente:
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
