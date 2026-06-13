#!/usr/bin/env bash
set -o errexit

# 1. Instalar uv de forma global en el entorno de construcción
pip install uv

# 2. Sincronizar dependencias de producción de forma exacta y congelada
uv sync --frozen --no-dev

# 3. Recopilar archivos estáticos usando el entorno de uv
uv run python manage.py collectstatic --noinput

# 4. Ejecutar migraciones de la base de datos de forma silenciosa
uv run python manage.py migrate --noinput