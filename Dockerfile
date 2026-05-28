# Usar una imagen oficial de Python ligera y estable
FROM python:3.11-slim AS builder

# Configurar variables de entorno óptimas para Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema necesarias para construir paquetes de Python si fuera necesario
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Crear entorno virtual e instalar dependencias
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Imagen final de producción ---
FROM python:3.11-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Crear un usuario del sistema no privilegiado para ejecutar el bot de forma segura
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /bin/bash appuser

# Copiar el entorno virtual con las dependencias instaladas desde la etapa builder
COPY --from=builder /opt/venv /opt/venv

# Copiar el código del bot, base de conocimientos y ajustar permisos
COPY bot.py knowledge_base.json ./

RUN chown -R appuser:appgroup /app

# Cambiar al usuario no priviligiado
USER appuser

# Ejecutar el bot
CMD ["python", "bot.py"]
