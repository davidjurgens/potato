# Deploying to Your Own Machine

The default target. `--provider local` runs the published Potato image against
your task in Docker, on this machine, with no account and nothing to pay for.

```bash
potato deploy up myproject/config.yaml
```

`local` is what `--provider` defaults to, so that is the whole command.

## Why run a deploy locally

It shows you what will actually be deployed. `potato deploy up` does more than
start a server: it bundles the project, rewrites the config for a host,
generates a session key and an admin key, and injects them as environment
variables. Running that on your own machine is how you see the result before a
cloud provider is billing for it.

It is also the same code path every cloud provider uses. The bundle, the image,
the entrypoint and the environment are identical; only the machine differs. A
task that works here works on a droplet.

## What it does not replace

**It is not a way to show the task to someone else.** The port is published on
`127.0.0.1` only, so nothing outside this machine can reach it — including your
own phone on the same wifi. [`potato share`](deploy-share.md) is what puts a
task on a URL you can send to a person.

**It is not how you develop a task.** `potato start config.yaml` reads your
config and data files where they sit, so a restart picks up an edit. A deploy
copies them into a bundle first, so a change means rebuilding it. Use `start`
while you are writing the task and `up` when you want to see what ships.

## Requirements

Docker, running. Potato checks the daemon rather than the binary, because
Docker Desktop installed but not started is the common case and produces an
unreadable socket error otherwise.

The image is pulled from `ghcr.io/davidjurgens/potato:latest` on every `up`,
which is about 840 MB the first time and a few seconds after that. Without the
pull, an image fetched weeks ago would be reused forever with nothing to say
so. If the pull fails and you already have the image, the deploy continues and
says which copy it used.

## Starting it

```
$ potato deploy up myproject/config.yaml --port 8123

Preflight for myproject/config.yaml  (provider: local)
...
Bundle: 4 files, 75.3KB

4 step(s):
   1. docker.pull   pull ghcr.io/davidjurgens/potato:latest
   2. docker.rm     remove any existing container potato-deploy-my-study
   3. docker.run    run potato-deploy-my-study on 127.0.0.1:8123 ...
   4. health.wait   poll http://127.0.0.1:8123/health until the server answers

Pulling ghcr.io/davidjurgens/potato:latest ...
Started potato-deploy-my-study at http://127.0.0.1:8123

Deployed: http://127.0.0.1:8123
```

The last step matters more than it looks. `docker run` returns a container id
and exits 0 whether or not the server ever serves a request, and every refusal
the image makes — an unwritable directory, a config that will not parse, a
`GUNICORN_WORKERS` override — happens after that. So `up` waits for `/health`,
and if the container exits first it prints the exit code and the tail of the
log:

```
Error: potato-deploy-my-study exited with code 3 before serving a request.
Last 25 log lines:
  ...
  ValueError: Invalid JSON at line 1 in data/toy-example.json
The container was left in place: docker logs potato-deploy-my-study
```

The container is left in place deliberately. Its logs are how you find out what
happened.

## Where things are

Everything lives under `.potato/` beside your config:

| Path | Holds |
|---|---|
| `.potato/bundle/local/<name>/` | the bundle, mounted at `/app` in the container |
| `.potato/deployments.json` | which deployments exist and their state |
| `.potato/secrets.json` | the generated admin API key, mode 0600 |

Keep `.potato/` out of version control. Potato's own `.gitignore` already does.

The bundle directory is the running task's directory, not a copy of it, so the
server writes annotations and `project.sqlite` straight back into
`.potato/bundle/local/<name>/`. Two consequences worth knowing:

- **A rebuild does not delete them.** Running `up` again replaces the config
  and the data files and leaves the annotation output and the databases alone.
- **`destroy` does not delete them either.** It removes the container. The
  annotations stay on disk until you remove the directory yourself.

Each provider gets its own bundle directory, so building for DigitalOcean does
not disturb a local deployment of the same task.

## File ownership

The container runs as the user who ran the CLI, not as the image's own uid, so
the annotations end up owned by you rather than by a uid you would need root to
read. This is also what stops the server dying on its first write on a Linux
host. See [File ownership](docker.md#file-ownership) for the longer version.

## Managing it

```bash
potato deploy status myproject/config.yaml     # is the container up
potato deploy logs myproject/config.yaml -f    # follow the server logs
potato deploy pull myproject/config.yaml       # copy the annotations out
potato deploy destroy myproject/config.yaml    # remove the container
```

`logs` reads both of the container's streams. Tracebacks and gunicorn boot
failures arrive on stderr, so reading stdout alone returns the access log and
drops the reason the server died.

`pull` copies the annotation output out of the container and snapshots
`project.sqlite` with `sqlite3 .backup` first. The database runs in WAL mode
with a live writer, and copying the file alone gives you one that is corrupt or
missing recent work with nothing to tell you so. On a local deployment the data
is already on your disk in the bundle directory, so `pull` is mostly there to
rehearse the command you will run against a real host.

`destroy` refuses to run on a deployment that has never been pulled, on the
grounds that it cannot tell an unannotated study from a failed download.
`--force` overrides it.

## Running more than one

Deployment names default to a slug of `annotation_task_name`. Pass `--name` and
a different `--port` to run several at once:

```bash
potato deploy up config.yaml --name pilot --port 8001
potato deploy up config.yaml --name main  --port 8002
```

Each gets its own container, its own bundle directory and its own generated
keys.

## Troubleshooting

**`docker is required for the local provider`** — the daemon is not reachable.
Start Docker Desktop, or run the server directly with `potato start`.

**`exited with code 3 before serving a request`** — the log tail printed
underneath says why. The most common causes are a data file that will not parse
and a config path that resolves outside the task directory.

**`could not pull ... and no local copy exists`** — no network and no cached
image. Nothing to do but connect.

**It was healthy and now the port is refused** — the container stopped.
`potato deploy status` reports its state and `potato deploy logs` has the last
of its output.

**The URL works for you and not for a colleague** — that is the intended
behaviour; the port is bound to loopback. Use
[`potato share`](deploy-share.md).

## Related

- [Deploying a task](one-command-deploy.md) — choosing a target
- [Docker](docker.md) — the image this runs, and running it by hand
- [`potato share`](deploy-share.md) — a temporary public URL for the same server
- [DigitalOcean](deploy-digitalocean.md) — the same bundle on a real host
