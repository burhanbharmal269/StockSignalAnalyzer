#!/bin/sh
set -e

echo "Running database migrations..."
python -m alembic upgrade head

echo "Starting application..."
exec python src/main.py
