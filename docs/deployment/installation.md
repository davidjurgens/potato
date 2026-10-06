# Installing and Running Potato

You can run Potato on your own machine, on a server you rent, or on a hosting
platform. This page helps you pick one, and then sends you to the page for that
option.

## Choosing a target

| Situation | Use | Cost |
|---|---|---|
| Trying Potato, building a task | [Install it locally](#on-your-own-machine) | free |
| Showing a pilot to a few people for an afternoon | [`potato share`](deploy-share.md) | free |
| A study, and you have an AWS account | [`--provider aws`](deploy-aws.md) (Lightsail) | $12/month |
| A study, US academic with no budget | [`--provider openstack --cloud jetstream2`](deploy-openstack.md) | free with an ACCESS allocation |
| A study, as cheaply as possible | [`--provider hetzner`](deploy-vps.md) | about €6/month |
| A study, and you would rather not run a server | [`--provider fly`](deploy-fly.md) or [`--provider railway`](deploy-railway.md) | $6–20/month |
| Annotators deploy their own copy from a link | [A deploy button](deploy-buttons.md) | depends on the host |
| Your institution gives you a server | [Docker](docker.md) and a [reverse proxy](reverse-proxy.md) | — |

On AWS, use Lightsail (`--provider aws`): it has a flat monthly price that
includes the IPv4 address and the disk, and the only permissions it needs are
`lightsail:*`. New AWS accounts get $100–200 of credit, which covers several
months of it. [The AWS page](deploy-aws.md) also covers EC2 and ECS, and when
you might want them instead.

## On your own machine

Potato needs Python 3.9 or newer. The published image uses 3.11.

```bash
pip install potato-annotation
potato --version
```

To use the latest code instead of the latest release:

```bash
git clone https://github.com/davidjurgens/potato.git
cd potato
pip install -e .
```

Or skip Python entirely and use the published image, which has everything
installed:

```bash
docker run -p 8000:7860 -v "$PWD/myproject:/app" ghcr.io/davidjurgens/potato:latest
```

Then follow the [Quick Start](../quick-start.md) to build a task, and start it
with:

```bash
potato start myproject/config.yaml -p 8000
```

The task is at <http://localhost:8000>. Nobody else can reach it. To let other
people in for a short session, run `potato share myproject/config.yaml`, which
gives you a public HTTPS link until you press Ctrl-C. For anything longer, put
the task in the cloud.

## In the cloud

### With one command

`potato deploy` takes the config you already have and does the rest: it
creates the server, gets an HTTPS certificate, uploads the project, starts the
task, and gives you a URL.

```bash
pip install 'potato-annotation[deploy]'          # most targets
pip install 'potato-annotation[deploy-aws]'      # AWS
pip install 'potato-annotation[deploy-openstack]' # Jetstream2 and other OpenStack clouds

potato deploy up myproject/config.yaml --provider aws --dry-run   # see the plan and the cost
potato deploy up myproject/config.yaml --provider aws             # do it
```

`--dry-run` needs no account. It prints every resource that would be created,
the cost per month, and anything in your config that is risky on a public
server. Before any provider creates anything, it shows you the same plan and
waits for you to confirm.

When the study is finished:

```bash
potato deploy pull myproject/config.yaml      # download the annotations
potato deploy destroy myproject/config.yaml   # stop paying
```

[Deploying a task](one-command-deploy.md) covers the whole lifecycle.

### With a button

A deploy button sets up a copy of your task from its git repository in one
click. Use one when other people should be able to run the task in their own
accounts. [Deploy buttons](deploy-buttons.md) explains how to generate the files
for Heroku, Render, AWS and Railway.

### On a server you already have

Run the [Docker image](docker.md) behind any HTTPS reverse proxy. Use one
worker process: Potato keeps its state in memory, and two processes would each
hand out the same items. [Reverse proxy](reverse-proxy.md) has nginx and Caddy
examples.

## Targets that are not supported

These platforms were considered and left out on purpose:

| Platform | Why not |
|---|---|
| Google Cloud Run | Its storage options (Cloud Storage FUSE, NFS) cannot hold a SQLite database safely, and keeping one instance running costs about $50/month. |
| Azure Container Apps | Its persistent storage is Azure Files over SMB, where SQLite is known to report "database is locked". If you have Azure student credit, use an Azure VM with [Docker](docker.md). |
| AWS App Runner | Closed to new customers since 30 April 2026. |
| Lightsail container services | No persistent storage. |
| Koyeb | The plan with persistent storage starts at $29/month, and the platform has changed direction since it was acquired in 2026. |
| Porter | Runs Kubernetes in your own cloud account; the minimum cost is about $225/month. |
| Oracle Cloud Always Free | Its Arm VMs work with [Docker](docker.md), but Oracle reclaims instances it considers idle, and an annotation server between sessions looks idle. |
| Coolify, Dokploy, CapRover | These add a platform layer on top of a VM. For a single container, `--provider hetzner` gets you the same VM without it. |

## Related

- [Quick Start](../quick-start.md): build your first task
- [Deploying a task](one-command-deploy.md): the `potato deploy` lifecycle
- [Backups](deploy-backups.md): keeping data safe on hosts whose disk does not last
- [Getting annotations back](deploy-pull.md)
