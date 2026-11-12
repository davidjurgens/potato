#!/bin/bash
set -e

# Configuration
CONFIG_FILE="${POTATO_CONFIG:-config.yaml}"
PORT="${PORT:-7860}"
WORKERS="${GUNICORN_WORKERS:-1}"
THREADS="${GUNICORN_THREADS:-8}"
TIMEOUT="${GUNICORN_TIMEOUT:-120}"

# Potato keeps its item pool, assignment queue and per-user annotation state in
# memory, per process. A second worker gets its own copy of all three: it hands
# out instances the first worker already assigned, and because user_state.json is
# rewritten in full on every save, whichever worker saves last silently discards
# the other's annotations. Multi-worker is opt-in and unsupported.
if [ "${WORKERS}" != "1" ] && [ "${POTATO_ALLOW_MULTIWORKER}" != "1" ]; then
    echo "ERROR: GUNICORN_WORKERS=${WORKERS} but Potato's item pool and user state"
    echo "       are per-process. Multiple workers cause duplicate assignment and"
    echo "       lost annotations. Use 1 worker and raise GUNICORN_THREADS instead."
    echo "       Set POTATO_ALLOW_MULTIWORKER=1 to override (you will lose data)."
    exit 1
fi

echo "Starting Potato Demo Space..."
echo "  Config: ${CONFIG_FILE}"
echo "  Port: ${PORT}"
echo "  Workers: ${WORKERS}"

# Validate config exists
if [ ! -f "${CONFIG_FILE}" ]; then
    echo "ERROR: Config file not found: ${CONFIG_FILE}"
    exit 1
fi

# Start with gunicorn using the factory pattern
exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --threads "${THREADS}" \
    --timeout "${TIMEOUT}" \
    --access-logfile - \
    --error-logfile - \
    "potato.flask_server:create_app('${CONFIG_FILE}')"
