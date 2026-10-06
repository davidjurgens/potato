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

# Some hosts start the container as root whatever the image says: Railway does
# when RAILWAY_RUN_UID=0, which it needs because it mounts volumes root-owned.
# Hand the task directory to the image's user and continue as that user, so
# the server never runs as root and its files stay writable after a restart.
if [ "$(id -u)" = "0" ] && [ "${POTATO_RUN_AS_ROOT}" != "1" ] && \
   id potato >/dev/null 2>&1 && command -v setpriv >/dev/null 2>&1; then
    chown -R potato:potato . 2>/dev/null || true
    export HOME=/home/potato
    exec setpriv --reuid=potato --regid=potato --init-groups /bin/sh "$0"
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

# Image-only hosts (Render, Fly, Railway, ECS) have no SSH and nothing to upload
# to, so the project arrives as a tarball fetched here. The sha marker makes a
# restart on a persistent disk skip the download, and the bundle's .potato-keep
# list names the entries holding collected data, which an update never replaces.
if [ -n "${POTATO_BUNDLE_URL}" ]; then
    marker=".potato-bundle-sha"
    if [ -n "${POTATO_BUNDLE_SHA256}" ] && [ -f "${marker}" ] && \
       [ "$(cat "${marker}")" = "${POTATO_BUNDLE_SHA256}" ]; then
        echo "Project bundle ${POTATO_BUNDLE_SHA256} already in place"
    else
        echo "Fetching project bundle"
        staging=".potato-staging"
        rm -rf "${staging}"
        mkdir -p "${staging}"
        if [ -n "${POTATO_BUNDLE_TOKEN}" ]; then
            curl -fsSL --retry 3 -H "Authorization: Bearer ${POTATO_BUNDLE_TOKEN}" \
                -o "${staging}.tar.gz" "${POTATO_BUNDLE_URL}" || fetch_failed=1
        else
            curl -fsSL --retry 3 -o "${staging}.tar.gz" "${POTATO_BUNDLE_URL}" \
                || fetch_failed=1
        fi
        if [ -n "${fetch_failed}" ]; then
            echo "ERROR: could not download the project bundle from POTATO_BUNDLE_URL." >&2
            echo "       A presigned URL may have expired; run 'potato deploy up' again." >&2
            exit 1
        fi
        if [ -n "${POTATO_BUNDLE_SHA256}" ]; then
            actual=$(sha256sum "${staging}.tar.gz" | cut -d' ' -f1)
            if [ "${actual}" != "${POTATO_BUNDLE_SHA256}" ]; then
                echo "ERROR: project bundle checksum mismatch." >&2
                echo "       expected ${POTATO_BUNDLE_SHA256}" >&2
                echo "       got      ${actual}" >&2
                rm -rf "${staging}" "${staging}.tar.gz"
                exit 1
            fi
        fi
        tar -xzf "${staging}.tar.gz" -C "${staging}"
        rm -f "${staging}.tar.gz"
        keep=""
        if [ -f "${staging}/.potato-keep" ]; then
            keep=$(cat "${staging}/.potato-keep")
        fi
        for entry in "${staging}"/* "${staging}"/.[!.]*; do
            [ -e "${entry}" ] || continue
            name=$(basename "${entry}")
            skip=""
            for kept in ${keep}; do
                if [ "${name}" = "${kept}" ] && [ -e "${name}" ]; then
                    skip=1
                fi
            done
            if [ -n "${skip}" ]; then
                continue
            fi
            rm -rf "./${name}"
            mv "${entry}" "./${name}"
        done
        rm -rf "${staging}"
        if [ -n "${POTATO_BUNDLE_SHA256}" ]; then
            echo "${POTATO_BUNDLE_SHA256}" > "${marker}"
        fi
    fi
fi

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "ERROR: config file not found: ${CONFIG_FILE}" >&2
    echo "       The project directory mounts at /app. Check the -v argument, or" >&2
    echo "       set POTATO_CONFIG to the config's path inside the container." >&2
    echo "       Contents of $(pwd):" >&2
    ls -A . >&2 || true
    exit 1
fi

# Potato writes annotation output, potato.log and its SQLite databases into the
# project directory, so an unwritable /app kills the server during boot. A bind
# mount carries the host's ownership and the container's uid matches it only by
# coincidence: any directory created by root, and any host account whose uid is
# not 1000, fails here. Docker Desktop ignores ownership on bind mounts, so this
# is invisible on a Mac and reliable on Linux.
#
# Checked here because the alternative is a PermissionError thirty frames into a
# gunicorn worker traceback, printed after the process has already given up.
if [ "${POTATO_ALLOW_READONLY_APP}" != "1" ]; then
    # touch rather than a `>` redirect: a redirection failure on a special
    # builtin is fatal in POSIX sh, so dash exits before reaching the message
    # this check exists to print.
    probe=".potato-write-probe.$$"
    if ! touch "${probe}" 2>/dev/null; then
        echo "ERROR: $(pwd) is not writable by uid $(id -u), which is the user" >&2
        echo "       this image runs as. Potato writes annotation output," >&2
        echo "       potato.log and its SQLite databases into the project" >&2
        echo "       directory, so it cannot start." >&2
        echo "" >&2
        echo "       Give the directory to the container user:" >&2
        echo "           sudo chown -R 1000:1000 <project-dir>" >&2
        echo "       or run the container as yourself:" >&2
        echo '           docker run --user "$(id -u):$(id -g)" ...' >&2
        echo "" >&2
        echo "       Set POTATO_ALLOW_READONLY_APP=1 if the config writes" >&2
        echo "       everything under /data and /app is deliberately read-only." >&2
        exit 1
    fi
    rm -f "${probe}"
fi

echo "Starting Potato"
echo "  config:  ${CONFIG_FILE}"
echo "  port:    ${PORT}"
echo "  workers: ${WORKERS} (threads: ${THREADS})"

# gunicorn 26 opens a control socket under $HOME/.gunicorn/. A container run
# with a host uid that is not in /etc/passwd (`potato deploy` with the local
# provider, Heroku) has HOME=/, so every boot logged "Control server error:
# Permission denied: '/.gunicorn'". Potato never uses the socket. Older gunicorn
# has no such flag and would refuse it, hence the check.
control_socket=""
if gunicorn --help 2>/dev/null | grep -q -- "--no-control-socket"; then
    control_socket="--no-control-socket"
fi

# create_app is the WSGI factory; it loads config and builds state before the
# first request, so a 200 from /health means the server is genuinely ready.
# ${control_socket} is unquoted on purpose: empty means no argument at all.
exec gunicorn ${control_socket} \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --threads "${THREADS}" \
    --timeout "${TIMEOUT}" \
    --access-logfile - \
    --error-logfile - \
    "potato.flask_server:create_app('${CONFIG_FILE}')"
