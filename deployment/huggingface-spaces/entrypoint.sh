#!/bin/bash
set -e

# Configuration
CONFIG_FILE="${POTATO_CONFIG:-config.yaml}"
PORT="${PORT:-7860}"
WORKERS="${GUNICORN_WORKERS:-2}"
THREADS="${GUNICORN_THREADS:-4}"
TIMEOUT="${GUNICORN_TIMEOUT:-120}"

echo "Starting Potato annotation server..."
echo "  Config: ${CONFIG_FILE}"
echo "  Port: ${PORT}"
echo "  Workers: ${WORKERS}"

# Validate config exists
if [ ! -f "${CONFIG_FILE}" ]; then
    echo "ERROR: Config file not found: ${CONFIG_FILE}"
    echo "Set POTATO_CONFIG environment variable to your config path."
    exit 1
fi

# Start with gunicorn for production
exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --threads "${THREADS}" \
    --timeout "${TIMEOUT}" \
    --access-logfile - \
    --error-logfile - \
    "potato.flask_server:create_app('${CONFIG_FILE}')"
