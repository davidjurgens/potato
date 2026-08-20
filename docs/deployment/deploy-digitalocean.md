# Deploying to a DigitalOcean Droplet

One command takes a task from a config file to an HTTPS URL you can send to
annotators.

```bash
pip install 'potato-annotation[deploy]'
export DIGITALOCEAN_TOKEN=dop_v1_...
potato deploy up myproject/config.yaml --provider digitalocean
```

It prints what it will create, what it will cost and what the URL will expose,
then asks before spending anything. Several minutes later — most of it spent
installing Docker and pulling the image on a fresh machine — you have a running
server at `https://<droplet-ip>`.

## Before you start

A DigitalOcean personal access token with **read and write** scope, from
<https://cloud.digitalocean.com/account/api/tokens>. Read-only tokens fail at
the first call with a clear message.

Potato looks for the token in `--token`, then `DIGITALOCEAN_TOKEN`,
`DIGITALOCEAN_ACCESS_TOKEN` or `DO_TOKEN`, then `~/.config/doctl/config.yaml`.
It is never written to disk.

## What gets created

| Resource | Purpose | Cost |
|---|---|---|
| Droplet, `s-2vcpu-2gb` | Runs the server | $18/month |
| Cloud firewall | Inbound 22, 80, 443 only | free |
| SSH key | Generated for this deployment alone | free |
| Block volume (with `--volume-gb`) | Annotations that survive the droplet | $0.10/GB/month |

Everything is tagged `potato` and `potato-<name>`, so you can find and remove it
from the console even if the local state file is lost.

`s-1vcpu-1gb` is offered by DigitalOcean and Potato will warn you off it. The
image is about 840 MB and the working set is numpy, pandas and scipy; 1 GB
swaps. 2 GB is the smallest size worth using.

## How TLS works without a domain

With no `--domain`, Caddy obtains a Let's Encrypt certificate for the droplet's
IP address. Browsers accept it with no warning and no DNS to configure.

**IP certificates are valid for about six days**, not ninety. Renewal happens
automatically and has roughly two days of slack rather than thirty. If a study
runs unattended for weeks, check `potato deploy status` occasionally — a failed
renewal shows up there as a TLS error before an annotator meets a browser
warning.

**The certificate store belongs on a volume.** With `--volume-gb` it is placed
there automatically, so a restart does not mean re-issuing.

For a real name, point an A record at the droplet and pass `--domain`:

```bash
potato deploy up myproject/config.yaml --provider digitalocean \
  --domain annotate.example.edu
```

That path uses ordinary ninety-day certificates. Create the DNS record first —
Caddy validates over HTTP-01 and needs the name to resolve.

Potato does not use `sslip.io` or similar wildcard DNS services. They are
deliberately absent from the Public Suffix List, which means a browser treats
every host under one as the same site for cookie purposes: anyone else's machine
on that domain could set a cookie your Flask session would accept.

## Keeping the annotations

```bash
potato deploy pull myproject/config.yaml
```

This downloads the annotation output directory, plus `project.sqlite` (memos,
codebook, cases, search index, review workflow) and `datasets.sqlite`. Neither
database can be regenerated.

Both are snapshotted with `sqlite3 .backup` on the host before being copied.
That is not a detail you can skip if you fetch them yourself: they run in WAL
mode with a live writer, so copying the file gives you a database that is
corrupt or missing recent work, with nothing to tell you so.

`potato deploy destroy` refuses to run on a deployment that has never been
pulled. `--force` overrides it.

Use `--volume-gb` for anything longer than a pilot:

```bash
potato deploy up myproject/config.yaml --provider digitalocean --volume-gb 25
```

Annotations then live on the volume rather than the droplet's own disk, so
resizing or rebuilding the droplet does not lose them.

## Access control

Deploy does not change how your task authenticates. Whatever `user_config` and
`authentication` say is what ships.

Preflight tells you what the URL exposes before you confirm. Open registration
on a public host is reported as a warning, not an error, because for a
crowdsourced study it is often the point. To restrict it:

```yaml
user_config:
  allow_all_users: false
  users:
    - alice
    - bob
```

The admin API key is generated per deployment, injected as an environment
variable, and stored locally in `.potato/secrets.json` at mode 0600. It never
enters the bundle. Keep `.potato/` out of version control — Potato's own
`.gitignore` already does.

## Managing a deployment

```bash
potato deploy status myproject/config.yaml     # is it up and is TLS healthy
potato deploy logs myproject/config.yaml -f    # follow the server logs
potato deploy list myproject/config.yaml       # every deployment of this config
potato deploy up myproject/config.yaml --provider digitalocean   # push changes
potato deploy destroy myproject/config.yaml    # remove everything
```

Running `up` again on the same name updates the existing droplet: it uploads the
new bundle and restarts the service rather than creating a second machine. Use
`--name` to run several deployments from one config:

```bash
potato deploy up config.yaml --provider digitalocean --name pilot
potato deploy up config.yaml --provider digitalocean --name main
```

## The deploy sequence

The waits are long, so it helps to know which one you are sitting in.

1. Verify the token, then generate an ed25519 key for this deployment only, so
   that your own SSH keys are never uploaded and revoking one deployment cannot
   affect another.
2. Create the volume, if you asked for one.
3. Launch the droplet from DigitalOcean's `docker-20-04` image with a cloud-init
   payload, and **record its id locally before anything else runs**. A machine
   whose id was never written down is a machine that bills forever.
4. Attach the firewall.
5. Wait for an IPv4 address, then for SSH, then for cloud-init. These are three
   separate moments minutes apart.
6. Upload the bundle over SFTP as a single archive.
7. Write the environment file at mode 0600, holding the session key and admin
   key.
8. Start the server and Caddy, then poll `/health` until it answers.

The app listens on `127.0.0.1:8000` inside the droplet and is reachable only
through Caddy. Port 8000 is never opened, so there is no plaintext route to the
task even if the firewall is removed.

Run `potato deploy up --dry-run` to see all of it, including the exact firewall
rules and cloud-init, without creating anything or needing a token.

## Troubleshooting

**`Refusing to deploy`** — preflight found an error. Each finding says how to
satisfy it. `--force` is not honoured for a public host.

**It stops at "Waiting for first-boot provisioning"** — Docker is installing and
the image is pulling, which takes several minutes on a small droplet. If it
fails, the last 40 lines of `/var/log/cloud-init-output.log` are printed.

**"never became healthy"** — the droplet was created and is still running. It is
not cleaned up automatically, because the logs on it are how you find out what
happened. Use `potato deploy logs`, then `destroy --force` when you are done.

**A browser certificate warning** — most often DNS. With `--domain`, the A
record must resolve before Caddy can validate. Without one, check
`potato deploy status`: a failed IP-certificate renewal reports as a TLS error.

**`No deploy key for '<name>'`** — `.potato/secrets.json` was deleted. The key
exists nowhere else. Add your own key to the droplet from the DigitalOcean
console to reach it.

## Related

- [Docker](docker.md) — the image this deploys, and running it yourself
- [Reverse proxy](reverse-proxy.md) — if you terminate TLS yourself
- [Scaling](scaling.md) — how many annotators one droplet serves
