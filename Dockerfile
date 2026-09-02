# Canonical Potato image.
#
# Every deploy target pulls this rather than building from source on the host.
# Potato's core dependencies include numpy, pandas, scipy and scikit-learn; on a
# 1 GB droplet `pip install` is an out-of-memory kill, and on 2 GB it is five to
# ten minutes on every redeploy. A pull is under a minute and byte-identical
# each time.
#
#   docker build -t potato .
#   docker build --build-arg POTATO_EXTRAS=all -t potato:all .
#   docker run -p 8000:7860 -v "$PWD/myproject:/app" potato
#
# The image ships Potato and nothing else. The project — config.yaml, data/,
# layouts/ — is mounted at /app, which is why one image serves every task.

# ---------------------------------------------------------------- builder ----
FROM python:3.11-slim AS builder

# gcc and friends are needed to build any dependency without a manylinux wheel
# for the target architecture. They stay in this stage.
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Empty installs core only. `all` adds the AI SDKs, format readers, export and
# auth extras (see setup.py); it deliberately excludes `vision`, which pulls
# multi-gigabyte torch wheels.
ARG POTATO_EXTRAS=""

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src

# setup.py holds the dependency lists; requirements.txt is a development
# superset (pytest, selenium, docs tooling) and must not reach the image.
COPY setup.py MANIFEST.in README.md ./
COPY potato/ ./potato/

RUN if [ -n "$POTATO_EXTRAS" ]; then \
        pip install ".[${POTATO_EXTRAS}]" gunicorn; \
    else \
        pip install . gunicorn; \
    fi && \
    python -c "import potato, flask, gunicorn; print('installed', potato.__file__)"

# ---------------------------------------------------------------- runtime ----
FROM python:3.11-slim AS runtime

# sqlite3 is not optional: `potato deploy pull` snapshots the project database
# with `.backup` before copying it, because project.sqlite runs in WAL mode with
# a live writer and copying the file alone yields a corrupt or stale database.
RUN apt-get update && \
    apt-get install -y --no-install-recommends sqlite3 curl && \
    rm -rf /var/lib/apt/lists/*

# uid 1000 because HuggingFace Spaces requires it and nothing else objects.
RUN useradd -m -u 1000 potato

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# /app is the mount point for the project; /data is for anything the operator
# wants to outlive the container (annotation output, the SQLite databases).
RUN mkdir -p /app /data && chown -R potato:potato /app /data
VOLUME ["/data"]

USER potato
WORKDIR /app

ENV POTATO_CONFIG=config.yaml \
    PORT=7860 \
    GUNICORN_WORKERS=1 \
    GUNICORN_THREADS=8

EXPOSE 7860

# /health is unauthenticated and reports only liveness; it returns 503 until the
# state managers exist, so start-period covers data loading on a large task.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
