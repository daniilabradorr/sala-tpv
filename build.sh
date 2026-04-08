#!/usr/bin/env bash
set -o errexit

pip install uv
uv sync
uv run python manage.py collectstatic --noinput
uv run python manage.py migrate