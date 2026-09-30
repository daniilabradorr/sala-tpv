#!/bin/sh
set -eu

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"

echo "Collecting static files..."
uv run python manage.py collectstatic --noinput

echo "Applying database migrations..."
uv run python manage.py migrate --noinput

echo "Starting Gunicorn..."
exec uv run gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}"
