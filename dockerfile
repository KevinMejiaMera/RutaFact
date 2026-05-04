# Imagen base oficial
FROM python:3.10-slim

# Variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias del sistema (SIN JAVA JRE)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libc6-dev \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    curl \
    wget \
    gnupg \
    libmagic-dev \
    libxml2-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Crear usuario no root
RUN useradd -ms /bin/bash appuser

# Establecer directorio de trabajo
WORKDIR /app

# Copiar primero requirements.txt para aprovechar el cache
COPY backend/requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código del backend
COPY backend/ /app/

# Crear directorios necesarios
RUN mkdir -p \
    /app/storage/logs \
    /app/storage/backups \
    /app/staticfiles \
    /app/mediafiles \
    /app/logs

# Crear archivos de logs vacíos
RUN touch /app/storage/logs/rutafact.log \
          /app/storage/logs/celery_worker.log \
          /app/storage/logs/celery_beat.log \
          /app/storage/logs/gunicorn_access.log \
          /app/storage/logs/gunicorn_error.log \
          /app/storage/logs/sri_integration.log \
          /app/storage/logs/certificates.log \
          /app/logs/celery.log

# Copiar entrypoint y dar permisos
COPY backend/entrypoint.sh /app/entrypoint.sh
# Convertir CRLF → LF (fix para Windows)
RUN sed -i 's/\r//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Dar permisos a los archivos y carpetas
RUN chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    chmod -R 644 /app/storage/logs/*.log && \
    chmod 644 /app/logs/celery.log

# Entrypoint garantiza directorios en runtime
ENTRYPOINT ["/app/entrypoint.sh"]
