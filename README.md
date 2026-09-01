# AI DevOps Log Monitor & Analyzer Bot 🤖🪵🧠

Choose your language / Selecciona tu idioma:
*   [English Documentation 🇬🇧](#english-documentation)
*   [Documentación en Español 🇪🇸](#documentación-en-español)

---

# English Documentation

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Docker Slim](https://img.shields.io/badge/docker-slim--3.11-cyan.svg)](https://hub.docker.com/_/python)
[![Docker Engine](https://img.shields.io/badge/Docker-Native%20Socket-blue.svg)](https://docs.docker.com/engine/api/)
[![AI Groq](https://img.shields.io/badge/AI-Groq%20Llama%203.3-orange.svg)](https://groq.com/)
[![Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini-blueviolet.svg)](https://ai.google.dev/)

A **Senior DevOps** production-grade tool designed to intelligently monitor Docker container logs natively via `/var/run/docker.sock`, analyze critical errors and anomalies using ultra-fast LLMs (**Meta Llama 3.3 via Groq**, **Google Gemini**, or **Ollama**), and deliver highly precise diagnostics, root-cause analyses, and console-ready resolution commands formatted in Markdown directly to your **Web UI** dashboard.

---

## 🏗️ Architecture & Flow

```mermaid
graph TD
    A["Docker Host (/var/run/docker.sock)"] -->|1. Direct Log Stream & Discovery| B["ai-devops-bot Engine"]
    B -->|2. Deduplication & Cooldown Filter| B
    B -->|3. Local RAG Knowledge Base (SQLite WAL)| C["Custom Solutions & Ignore Rules"]
    B -->|4. Diagnostic Prompt (Top Errors)| D["AI Provider (Groq / Gemini / Ollama)"]
    D -->|5. Root Cause & Solution Commands| B
    B -->|6. Bounded History (FIFO 15 max)| E["SQLite Database (history.db)"]
    B -->|7. Real-time REST API & Glassmorphic UI| F["Web Dashboard (:8000)"]
```

1.  **Direct Docker Ingestion**: Connects directly to the Docker Engine socket (`/var/run/docker.sock`). Automatically discovers all running containers and ingests new log streams without needing external log collectors (No Loki or Promtail required).
2.  **In-Memory Deduplication & Cooldown**: Groups identical and concurrent errors by container and suppresses duplicates within the configured `COOLDOWN_MINUTES` window to eliminate alert fatigue.
3.  **Local RAG Knowledge Base**: Matches errors against custom rules in SQLite. Injects custom administrator diagnostics, preferred bash commands, or automatically silences and auto-resolves known benign errors (`action: IGNORE`).
4.  **Polymorphic AI Diagnostics**: Seamlessly dispatches batched error logs to Groq (Llama 3.3), Google Gemini, or local Ollama.
5.  **Ultra-Lightweight & Low Disk Wear**: Configured with SQLite WAL (`PRAGMA synchronous = NORMAL`, `cache_size = 2MB`) and bounded FIFO history (capped at 15 items per incident) to prevent excessive disk wear and memory leaks (~33 MB RAM footprint).

---

## ✨ Main Features

*   **100% Autonomous & Self-Contained**: Operates directly on the Docker socket with zero external monitoring stack requirements.
*   **Asynchronous Web Control Center (Web UI)**: A premium, dark-themed dashboard served natively on `HEALTHCHECK_PORT` (default `8000`) with zero external Python dependencies.
*   **Interactive RAG Knowledge Base**: Add, edit, or delete custom troubleshooting rules and regex patterns directly from the browser with instant hot-reloading.
*   **Full Context Log Viewer**: One-click context exploration fetching preceding and subsequent container logs around an incident for fast troubleshooting.
*   **Polymorphic AI Providers**: Toggle between Groq (Llama 3.3), Google Gemini (REST), and Ollama (local AI).
*   **Auto-Purge & Maintenance**: Automatically closes inactive incidents and cleans up records older than 30 days.

---

## ⚙️ Configuration (Environment Variables)

Create your `.env` file based on the template:

```env
# Docker Socket Path
DOCKER_SOCKET=/var/run/docker.sock
# Optional: Ignored container names (comma-separated)
IGNORED_CONTAINERS=ai-devops-bot,dozzle,cadvisor,node-exporter,homepage,dockge-dockge-1

# Logging Format (TEXT or JSON)
LOG_FORMAT=TEXT

# AI Provider Selection (groq, gemini, or ollama)
AI_PROVIDER=groq

# Provider A: Groq API (Llama 3.3)
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# Provider B: Google Gemini (REST)
GEMINI_API_KEY=AIzaSy_your_gemini_key_here
GEMINI_MODEL=gemini-2.5-flash

# Provider C: Ollama (Local AI)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Alert Fatigue Prevention Window (minutes)
COOLDOWN_MINUTES=15

# Web UI & REST API Port
HEALTHCHECK_PORT=8000

# Logging Level (INFO or DEBUG)
LOG_LEVEL=INFO

# SQLite Database Path
DATABASE_PATH=data/history.db
```

---

## 🚀 Quick Deployment with Docker Compose

```yaml
services:
  ai-devops-bot:
    image: ghcr.io/snchz/ai-devops-bot:latest
    container_name: ai-devops-bot
    restart: unless-stopped
    user: 1000:1000
    group_add:
      - "989"  # Docker group ID
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - /path/to/data:/app/data:z
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

```bash
docker compose up -d
```

---

# Documentación en Español

[![Versión de Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Docker Slim](https://img.shields.io/badge/docker-slim--3.11-cyan.svg)](https://hub.docker.com/_/python)
[![Docker Socket Nativo](https://img.shields.io/badge/Docker-Socket%20Nativo-blue.svg)](https://docs.docker.com/engine/api/)
[![AI Groq](https://img.shields.io/badge/AI-Groq%20Llama%203.3-orange.svg)](https://groq.com/)
[![Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini-blueviolet.svg)](https://ai.google.dev/)

Una herramienta de nivel **Senior DevOps** diseñada para monitorizar de forma inteligente los logs de contenedores directamente a través de `/var/run/docker.sock`, analizar anomalías y errores críticos mediante inteligencia artificial (**Meta Llama 3.3 en Groq**, **Google Gemini** u **Ollama**), y enviar diagnósticos precisos junto con soluciones inmediatas y comandos de consola formateados en Markdown directo a la interfaz **Web** integrada.

---

## 🏗️ Arquitectura y Flujo de Trabajo

```mermaid
graph TD
    A["Servidor Docker (/var/run/docker.sock)"] -->|1. Stream directo de logs| B["Motor ai-devops-bot"]
    B -->|2. Deduplicación y Cooldown| B
    B -->|3. Base de Conocimiento RAG (SQLite WAL)| C["Reglas y Soluciones Personalizadas"]
    B -->|4. Prompt Diagnóstico por Lote| D["Proveedor IA (Groq / Gemini / Ollama)"]
    D -->|5. Causa y Comandos de Solución| B
    B -->|6. Historial Acotado (FIFO 15 máx)| E["Base de Datos SQLite (history.db)"]
    B -->|7. REST API y Panel Glassmorphic| F["Interfaz Web (:8000)"]
```

1.  **Ingestión Directa de Docker**: Conexión nativa al socket del demonio de Docker (`/var/run/docker.sock`). Descubre automáticamente todos los contenedores activos y procesa sus logs en tiempo real sin requerir Loki ni Promtail.
2.  **Deduplicación y Cooldown**: Agrupa errores idénticos por contenedor y silencia repeticiones dentro del intervalo configurado en `COOLDOWN_MINUTES` para prevenir la fatiga por alertas.
3.  **Base de Conocimiento RAG**: Compara los errores contra reglas locales en SQLite. Permite inyectar soluciones conocidas del administrador o auto-resolver y silenciar errores inofensivos (`action: IGNORE`).
4.  **Diagnósticos con IA**: Envía los logs agrupados a Groq (Llama 3.3), Google Gemini o un modelo local en Ollama.
5.  **Ultraligero y Bajo Desgaste en Disco**: Optimizado con SQLite WAL (`PRAGMA synchronous = NORMAL`, caché de 2 MB) e historial acotado FIFO (máximo 15 entradas por incidencia), reduciendo el consumo a solo **~33 MB de RAM** y minimizando las escrituras en disco SSD.

---

## ✨ Características Principales

*   **100% Autónomo y sin dependencias externas**: Monitoreo directo sobre Docker Socket sin requerir infraestructura adicional de logs.
*   **Panel de Control Web Asíncrono**: Interfaz web oscura y moderna en el puerto `8000` con cero dependencias externas de Python.
*   **Editor Interactivo de Base de Conocimiento (RAG)**: Añade, edita y elimina patrones y soluciones desde el navegador con recarga en caliente instantánea.
*   **Visor de Contexto Completo**: Visualiza los logs anteriores y posteriores a un fallo con un clic para entender qué ocurrió en el contenedor.
*   **Proveedores de IA Polimórficos**: Compatible con Groq (Llama 3.3), Google Gemini y Ollama.
*   **Auto-Purga y Mantenimiento**: Cierre automático de incidencias inactivas y eliminación programada de registros con más de 30 días.

---

## ⚙️ Configuración (.env)

```env
# Ruta al Socket de Docker
DOCKER_SOCKET=/var/run/docker.sock
# Opcional: Contenedores a ignorar (separados por coma)
IGNORED_CONTAINERS=ai-devops-bot,dozzle,cadvisor,node-exporter,homepage,dockge-dockge-1

# Formato de logs (TEXT o JSON)
LOG_FORMAT=TEXT

# Proveedor de IA (groq, gemini, o ollama)
AI_PROVIDER=groq

# Proveedor A: Groq API (Llama 3.3)
GROQ_API_KEY=tu_api_key_de_groq_aqui
GROQ_MODEL=llama-3.3-70b-versatile

# Proveedor B: Google Gemini (REST)
GEMINI_API_KEY=tu_api_key_de_gemini_aqui
GEMINI_MODEL=gemini-2.5-flash

# Proveedor C: Ollama (AI Local)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Intervalo de enfriamiento de alertas (minutos)
COOLDOWN_MINUTES=15

# Puerto Web UI y REST API
HEALTHCHECK_PORT=8000

# Nivel de logs (INFO o DEBUG)
LOG_LEVEL=INFO

# Ruta a la base de datos SQLite
DATABASE_PATH=data/history.db
```

---

## 🚀 Despliegue con Docker Compose

```yaml
services:
  ai-devops-bot:
    image: ghcr.io/snchz/ai-devops-bot:latest
    container_name: ai-devops-bot
    restart: unless-stopped
    user: 1000:1000
    group_add:
      - "989"  # ID de grupo docker
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - /home/leif/docker/configs/ai-devops-bot/data:/app/data:z
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

```bash
docker compose up -d
```
