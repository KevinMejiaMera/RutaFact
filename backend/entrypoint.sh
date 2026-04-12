#!/bin/bash
set -e

# ─────────────────────────────────────────────
# Crear directorios necesarios en runtime
# (después de que los volúmenes ya están montados)
# ─────────────────────────────────────────────
mkdir -p /app/logs
mkdir -p /app/storage/logs
mkdir -p /app/storage/backups
mkdir -p /app/staticfiles
mkdir -p /app/mediafiles

# ─────────────────────────────────────────────
# Crear archivos de log si no existen
# ─────────────────────────────────────────────
touch /app/logs/celery.log
touch /app/storage/logs/rutafact.log
touch /app/storage/logs/celery_worker.log
touch /app/storage/logs/celery_beat.log
touch /app/storage/logs/gunicorn_access.log
touch /app/storage/logs/gunicorn_error.log
touch /app/storage/logs/sri_integration.log
touch /app/storage/logs/certificates.log

# ─────────────────────────────────────────────
# Ejecutar el comando original pasado al contenedor
# ─────────────────────────────────────────────
exec "$@"
