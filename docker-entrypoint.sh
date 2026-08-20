#!/bin/sh
# Canonical container entrypoint for the Potato image.
#
# POSIX sh, not bash: the runtime stage is python:3.11-slim, which has dash.
#
# Anything after the script name is treated as an override, so the image stays
# useful for one-off work:
#     docker run potato                      # serve $POTATO_CONFIG
#     docker run potato potato validate x.yaml
#     docker run -it potato sh
set -e

CONFIG_FILE="${POTATO_CONFIG:-config.yaml}"
PORT="${PORT:-7860}"
WORKERS="${GUNICORN_WORKERS:-1}"
THREADS="${GUNICORN_THREADS:-8}"
TIMEOUT="${GUNICORN_TIMEOUT:-120}"

# Run whatever was asked for instead of the server.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Potato keeps its item pool, assignment queue and per-user annotation state in
# memory, per process. A second worker gets its own copy of all three: it hands
# out instances the first worker already assigned, and because user_state.json is
# rewritten in full on every save, whichever worker saves last silently discards
# the other's annotations. Multi-worker is opt-in and unsupported.
if [ "${WORKERS}" != "1" ] && [ "${POTATO_ALLOW_MULTIWORKER}" != "1" ]; then
    echo "ERROR: GUNICORN_WORKERS=${WORKERS} but Potato's item pool and user state" >&2
    echo "       are per-process. Multiple workers cause duplicate assignment and" >&2
    echo "       lost annotations. Use 1 worker and raise GUNICORN_THREADS instead." >&2
    echo "       Set POTATO_ALLOW_MULTIWORKER=1 to override (you will lose data)." >&2
    exit 1
fi

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "ERROR: config file not found: ${CONFIG_FILE}" >&2
    echo "       The project directory mounts at /app. Check the -v argument, or" >&2
    echo "       set POTATO_CONFIG to the config's path inside the container." >&2
    echo "       Contents of $(pwd):" >&2
    ls -A . >&2 || true
    exit 1
fi

echo "Starting Potato"
echo "  config:  ${CONFIG_FILE}"
echo "  port:    ${PORT}"
echo "  workers: ${WORKERS} (threads: ${THREADS})"

# create_app is the WSGI factory; it loads config and builds state before the
# first request, so a 200 from /health means the server is genuinely ready.
exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --threads "${THREADS}" \
    --timeout "${TIMEOUT}" \
    --access-logfile - \
    --error-logfile - \
    "potato.flask_server:create_app('${CONFIG_FILE}')"
