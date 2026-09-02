# Running Potato in Docker

Potato publishes a prebuilt image to GitHub Container Registry. It contains the
server and its dependencies and nothing else — your project mounts at `/app` at
run time, so one image serves every task.

```bash
docker run -p 8000:7860 -v "$PWD/myproject:/app" ghcr.io/davidjurgens/potato:latest
```

Open <http://localhost:8000>. `myproject` is a directory holding `config.yaml`
and whatever it references (`data/`, `layouts/`).

## Why a prebuilt image

Potato's core dependencies include numpy, pandas, scipy and scikit-learn.
Installing them on a small VM is slow at best: on a 1 GB machine the build is
killed for running out of memory, and on 2 GB it takes five to ten minutes,
repeated on every redeploy. Pulling the image takes under a minute and gives the
same bytes every time. `potato deploy` uses it for that reason.

## Tags

| Tag | Contents | Size |
|---|---|---|
| `latest`, `2.8.0` | Core dependencies | ~840 MB |
| `latest-all`, `2.8.0-all` | Plus AI SDKs, document formats, export and OAuth | ~1.5 GB |
| `sha-<short>` | A specific commit | — |

Both are built for `linux/amd64` and `linux/arm64`, so they run natively on
Apple Silicon.

Pin a version for a study that will run for months. `latest` moves.

The `-all` variant covers `ai_support`, PDF and DOCX ingestion, parquet export
and OAuth logins. Neither variant includes the `vision` extra: it pulls
multi-gigabyte torch wheels, and browser-side segmentation does not need it:
ONNX Runtime Web is vendored in the image already.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `POTATO_CONFIG` | `config.yaml` | Config path inside the container |
| `PORT` | `7860` | Listen port |
| `GUNICORN_THREADS` | `8` | Concurrent requests |
| `GUNICORN_TIMEOUT` | `120` | Worker timeout, seconds |
| `POTATO_SECRET_KEY` | generated | Flask session signing key |
| `POTATO_ADMIN_API_KEY` | generated | Admin API authentication |
| `POTATO_GENERATED_TEMPLATES_DIR` | auto | Where baked task templates go |

Set `POTATO_SECRET_KEY` on anything that outlives a single run. Without it the
key is random per process, so every restart logs all annotators out.

```bash
docker run -p 8000:7860 \
  -v "$PWD/myproject:/app" \
  -e POTATO_SECRET_KEY="$(openssl rand -hex 32)" \
  -e POTATO_CONFIG=configs/pilot.yaml \
  ghcr.io/davidjurgens/potato:latest
```

## One worker

The image runs a single gunicorn worker and refuses to start with more.

Potato keeps its item pool, its assignment queue and every annotator's state in
memory, in the process. A second worker gets its own copy of all three: it hands
out instances the first worker already assigned, and because `user_state.json`
is rewritten in full on each save, whichever worker saves last discards the
other's annotations. Nothing reports this; annotations simply go missing.

Raise `GUNICORN_THREADS` for concurrency instead. Threads share one copy of the
state, so they do not have this problem. The default of 8 comfortably serves the
dozens of simultaneous annotators a typical study has.

`POTATO_ALLOW_MULTIWORKER=1` overrides the refusal. Do not use it to serve a
real study.

## File ownership

The image runs as uid 1000. A bind mount keeps the host's ownership, so the
container can only write to your project directory if that uid can. On Linux it
usually cannot: a directory you created belongs to your own uid, and one created
by root belongs to root.

The server checks this at startup and refuses to run rather than dying partway
through boot. Two ways to satisfy it:

```bash
sudo chown -R 1000:1000 myproject                  # hand it to the container user
docker run --user "$(id -u):$(id -g)" ...          # or run as yourself
```

`--user` also leaves the annotations owned by you rather than by a uid you would
need root to read.

Docker Desktop on macOS and Windows ignores ownership on bind mounts, so the
problem never appears there. A setup that works on a Mac can still fail on a
Linux server.

If the project is deliberately read-only and the config writes everything under
`/data`, set `POTATO_ALLOW_READONLY_APP=1` to skip the check.

`potato deploy` handles ownership on every target it provisions.

## Keeping the data

Annotations are written under `output_annotation_dir` inside the mounted
project, so with a bind mount they are already on your disk. Nothing else is
needed for a local run.

For a container whose filesystem does not survive a restart — most managed
hosts — mount a volume and point the project at it, or use
`potato deploy pull` to fetch the data down.

Two files matter beyond the annotation output: `project.sqlite` (memos, the
codebook, cases, search index, review workflow) and `datasets.sqlite`. Both live
in the project directory and neither is regenerable.

!!! warning "Copying a live SQLite file gives you a corrupt database"
    `project.sqlite` runs in WAL mode with a live writer. `docker cp` on the
    file alone yields a corrupt or stale database, and it fails silently — you
    find out weeks later. Snapshot it first:

    ```bash
    docker exec <container> sqlite3 /app/project.sqlite ".backup /tmp/snap.sqlite"
    docker cp <container>:/tmp/snap.sqlite ./project.sqlite
    ```

    `potato deploy pull` does this for you.

## Health checks

`GET /health` is unauthenticated and reports only whether the server is up:
`{"status": "ok"}` once it is ready, `503` while it is still loading data. Point
a load balancer or orchestrator at it. Large tasks take a while to index, so
allow a generous start period; the image's own `HEALTHCHECK` gives it 90
seconds.

`GET /admin/health` reports item and annotator counts, and needs the admin API
key in an `X-API-Key` header.

## Other commands

Anything after the image name replaces the server:

```bash
docker run --rm -v "$PWD/myproject:/app" ghcr.io/davidjurgens/potato:latest \
  python -m potato.preview_cli config.yaml

docker run --rm -it -v "$PWD/myproject:/app" ghcr.io/davidjurgens/potato:latest sh
```

## Building it yourself

```bash
git clone https://github.com/davidjurgens/potato
cd potato
docker build -t potato .
docker build --build-arg POTATO_EXTRAS=all -t potato:all .
```

`POTATO_EXTRAS` takes any extras name from `setup.py`: `ai`, `formats`,
`export`, `vision`, `all`.

## Troubleshooting

**`config file not found`** — the project did not mount where the server looked.
The error lists what it found in `/app`; compare that against your `-v`
argument. A relative host path needs to be absolute or `$PWD`-prefixed.

**`/app is not writable by uid 1000`** — see
[File ownership](#file-ownership). The server refuses to start rather than
failing partway through boot.

**Everyone is logged out after a restart** — set `POTATO_SECRET_KEY`.

**The server exits with `GUNICORN_WORKERS`** — see [One worker](#one-worker).

## Related

- [Reverse proxy](reverse-proxy.md) — TLS and path prefixes
- [Scaling](scaling.md) — how many annotators one instance serves
