# Deploying a Task

Getting a Potato task in front of annotators used to mean provisioning a
machine, installing the dependency stack, copying the project, configuring a
reverse proxy for TLS, and keeping it alive. `potato deploy` does all of that
from the config file you already have.

```bash
potato deploy up myproject/config.yaml --provider digitalocean
```

Several minutes later you have an HTTPS URL to send to annotators, and
`potato deploy pull` brings the annotations back down when you are done.

## Choosing a target

[Installing and running Potato](installation.md) has the short version. In
full:

| Target | Cost | Disk survives a restart | Use it for |
|---|---|---|---|
| [`local`](deploy-local.md) | free | yes | seeing what will deploy, before it costs anything |
| [`potato share`](deploy-share.md) | free | — | a pilot, a lab meeting, a link for twenty minutes |
| [`aws`](deploy-aws.md) (Lightsail) | $12/mo | yes | **a study on AWS**: flat price, `lightsail:*` permissions |
| [`aws-ec2`](deploy-aws.md#ec2-provider-aws-ec2) | ~$18/mo | yes | AWS accounts that require EC2 |
| [`aws-ecs`](deploy-aws.md#ecs-express-mode-provider-aws-ecs) | ~$45–70/mo | no, `--backup` | AWS with no server to manage |
| [`openstack`](deploy-openstack.md) | free with an allocation | yes | Jetstream2 (US academics), campus clouds |
| [`hetzner`](deploy-vps.md) | ~€6/mo | yes | the cheapest durable VM |
| [`vultr`](deploy-vps.md), [`linode`](deploy-vps.md) | $10–12/mo | yes | US-billed VMs |
| [`digitalocean`](deploy-digitalocean.md) | from $18/mo | yes | a VM with the longest history in Potato |
| [`fly`](deploy-fly.md) | ~$6/mo | yes (volume) | a managed container with a volume |
| [`railway`](deploy-railway.md) | ~$10–20/mo, usage | yes (volume) | a managed container with a volume |
| [`render`](deploy-render.md) | free, or $7/mo | paid only; `--backup` | a study with no budget |
| [`heroku`](deploy-heroku.md) | from $7/mo | no, `--backup` | labs that already use Heroku |
| [`huggingface`](deploy-huggingface.md) | needs PRO, $9/mo | no, backup built in | a public demo, and anyone already on the Hub |

`local` is the default, and it is the right first command whatever you plan to
use afterwards: same bundle, same image, same config rewriting, no account.

**With a budget, use a VM**: Lightsail on AWS, Hetzner for the lowest price,
Jetstream2 if you have an allocation. VMs are the targets with a persistent
disk, log streaming and SSH, so everything in this documentation works on them.

**Without one, use Render or Jetstream2.** Read
[the free tier warning](deploy-render.md#read-this-before-using-the-free-tier)
before using Render: a free instance has no disk and stops fifteen minutes
after your last annotator leaves. Potato will not create one until you have
said where the data goes.

## What each target supports

| | `local` | VMs¹ | `fly` | `railway` | `render` | `heroku` | `aws-ecs` | `huggingface` |
|---|---|---|---|---|---|---|---|---|
| Public HTTPS URL | no | yes | yes | yes | yes | yes | yes | yes |
| Survives a restart | yes | yes | yes | yes | paid / backup | backup | backup | backup |
| `deploy logs` | yes | yes | no | yes | no | yes | yes | no |
| `deploy pull` | yes | yes | yes | yes | yes | yes | yes | yes |

¹ `aws`, `aws-ec2`, `digitalocean`, `hetzner`, `vultr`, `linode`, `openstack`.

An unsupported operation raises an error naming the alternative rather than
quietly doing nothing, because a pull that silently returns zero files is
indistinguishable from a study nobody annotated.

Where the filesystem does not survive, pass `--backup hf` or `--backup s3`.
Annotations and the project databases are copied off the host every five
minutes and restored into the new server when it starts. The backup works on
every provider. See [Backups](deploy-backups.md).

## The lifecycle

```bash
potato deploy check   config.yaml --provider digitalocean   # what would this expose?
potato deploy up      config.yaml --provider digitalocean   # create or update
potato deploy status  config.yaml                           # is it up, is TLS healthy
potato deploy logs    config.yaml -f                        # follow the server logs
potato deploy pull    config.yaml                           # download the annotations
potato deploy destroy config.yaml                           # remove everything
potato deploy list    config.yaml                           # every deployment of this config
```

After the first `up`, none of these need `--provider` again. The deployment
record knows which one it is.

Running `up` a second time **updates** the existing deployment rather than
creating a second one: it uploads the new bundle and restarts the service.
`--name` runs several deployments from one config.

## Before it spends anything

`up` prints three things and then asks:

1. **The preflight report** — configuration errors that would break the deploy,
   and warnings about what the URL will expose.
2. **The plan** — every resource that will be created, with the exact firewall
   rules, cloud-init and environment keys. `--dry-run` stops here and needs no
   credentials at all.
3. **The estimated monthly cost.**

`--yes` skips the prompt. Nothing is created before you answer.

`potato deploy check` runs the first of those on its own, and is worth running
early: it reads the config the way a host would, and finds the paths that only
resolve on your laptop.

## Configuration and secrets

Deploy rewrites what is unambiguously a hosting concern: `debug` off, sessions
persisted, workers pinned to one, paths made relative to the bundle.

**It does not touch your authentication.** Whatever `user_config`,
`authentication`, `login` and `require_password` say is what ships. Preflight
reports open registration on a public host as a warning, because for a
crowdsourced study that is usually the point. It does report it, before you
confirm, rather than deciding for you.

Secrets are generated per deployment, injected as environment variables, and
stored locally in `.potato/secrets.json` at mode 0600. They never enter the
bundle, which is what keeps them out of a repo-backed target's git history.
Provider API tokens are never written to disk at all.

## One worker

Every target runs a single application process. Potato holds the item pool, the
assignment queue and every annotator's state in memory, and rewrites
`user_state.json` in full on each save. A second process gets its own copy of
all three: it hands out instances the first already assigned, and whichever one
saves last overwrites the other's annotations. Nothing reports it.

Concurrency comes from threads, which share one copy of that state. The default
of eight serves the dozens of simultaneous annotators a typical study has. See
[Scaling](scaling.md).

## Getting the data back

```bash
potato deploy pull myproject/config.yaml
```

This downloads the annotation output directory, plus `project.sqlite` (memos,
codebook, cases, search index, review workflow) and `datasets.sqlite`. Neither
database can be regenerated from anything else.

Both are snapshotted with SQLite's `.backup` before being copied. They run in
WAL mode with a live writer, so copying the file gives you a database that is
corrupt or missing recent work, with nothing to tell you so.

A pull that returns no files is not recorded as a pull, and `destroy` refuses
to run on a deployment that has never been pulled. See
[Getting annotations back](deploy-pull.md).

## Related

- [Running it on your own machine](deploy-local.md)
- [Sharing a task on a temporary URL](deploy-share.md)
- [AWS](deploy-aws.md) · [Jetstream2 and OpenStack](deploy-openstack.md) ·
  [Hetzner, Vultr, Linode](deploy-vps.md) · [DigitalOcean](deploy-digitalocean.md)
- [Fly.io](deploy-fly.md) · [Railway](deploy-railway.md) · [Render](deploy-render.md) ·
  [Heroku](deploy-heroku.md) · [HuggingFace Spaces](deploy-huggingface.md)
- [Backups](deploy-backups.md) · [Deploy buttons](deploy-buttons.md)
- [Getting annotations back](deploy-pull.md)
- [Docker](docker.md) — the image every target runs
- [Scaling](scaling.md) — how many annotators one host serves
- [Reverse proxy](reverse-proxy.md) — if you terminate TLS yourself
