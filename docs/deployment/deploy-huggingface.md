# Deploying to a HuggingFace Space

```bash
pip install 'potato-annotation[huggingface]'
export HF_TOKEN=hf_...
potato deploy up myproject/config.yaml --provider huggingface
```

This creates a Docker Space, a private Dataset repo for the annotations, and
uploads the project. The Space gets HTTPS on `*.hf.space` with nothing to
configure.

## Two things to know first

**Docker Spaces are not free.** From the Hub documentation: *"Static Spaces are
free for everyone. Gradio and Docker Spaces run on compute and require a paid
plan to create: PRO for personal accounts, Team or Enterprise for
organizations."* Potato Spaces are Docker Spaces, so creating one needs PRO
($9/month) or a Team plan. Restarting a Space you already have does not.

If you want a free host, use [Render](deploy-render.md) or
[`potato share`](deploy-share.md).

**A Space's filesystem does not survive.** It is wiped on every rebuild and
every restart, and free Spaces sleep after 48 hours idle. Annotations written to
it are temporary by construction.

That second fact shapes the whole provider. It creates a private Dataset repo
`<you>/<name>-annotations` and mirrors the annotation output into it every five
minutes, and the Space's README says so. **The Dataset, not the Space, is where
your data lives.** `--demo` skips it for a throwaway, and says plainly in the
plan that anything collected will be lost.

## Getting the data

```bash
potato deploy pull myproject/config.yaml
```

This downloads the backup Dataset, not the Space. Whatever is on the Space right
now is at best a partial copy of what the Dataset already has.

Without a backup — a `--demo` deployment — there is nowhere to pull from, and
the only route is the admin export API against the running Space.

`potato deploy destroy` deletes the Space and **leaves the Dataset alone**.
Deleting the host is cheap and reversible; deleting the annotations is neither,
so it is never implied. Remove the Dataset yourself when you are done with it.

## The concurrency cap

A free account runs at most **three Spaces at once**. A fourth cannot start: the
API returns 403 and the Space lands in `PAUSED`.

`PAUSED` and `SLEEPING` look similar and behave completely differently. A
sleeping Space wakes when a visitor opens it. A paused one does not: only its
owner can restart it, so a visitor sees a dead page. `potato deploy status`
distinguishes them.

The 48-hour idle-sleep timer cannot be shortened on free hardware.

## What gets uploaded

A Space built by `potato deploy` contains the project, a Dockerfile and a
README, which is a dozen or so files. The Dockerfile derives from the published
image:

```dockerfile
FROM ghcr.io/davidjurgens/potato:latest
COPY --chown=potato:potato . /app
```

The demo catalog under `deployment/huggingface-spaces/` still copies the whole
Potato package into each Space, which comes to 930 files. Deriving from the
image instead means the Space carries only your project.

Secrets — the session signing key, the admin API key, the HuggingFace token for
the backup — are set as **Space secrets** through the API, never committed. Even
a private Space repo is readable by everyone who has access to it.

## Options

| Flag | Purpose |
|---|---|
| `--owner` | Deploy under an organization instead of your account |
| `--private` | Create a private Space |
| `--demo` | No backup Dataset; annotations are disposable |
| `--backup-minutes` | How often to mirror annotations (default 5) |
| `--name` | Space name, defaulting to a slug of the task name |

## Backing up from any provider

The `huggingface_backup` block is not specific to Spaces. Any deployment on any
provider can mirror its annotations to a Dataset, which is the answer to an
ephemeral filesystem wherever you meet one:

```yaml
huggingface_backup:
  enabled: true
  repo_id: "your-name/study-annotations"
  token: "${HF_TOKEN}"
  repo_type: dataset
  schedule_minutes: 5
  private: true
```

Passing `--hf-token` to `potato deploy up` configures this for you.

## Troubleshooting

**A payment error on create** — Docker Spaces need PRO or a Team plan. The error
names the free alternatives.

**The Space is `PAUSED`** — usually the three-Space cap. Pause another Space,
then restart this one from its settings page or with
`huggingface-cli`. Restarting does not need PRO.

**`BUILD_ERROR`** — the build log at
`https://huggingface.co/spaces/<owner>/<name>?logs=build` says why.

**Logs are not streamed** — HuggingFace's log endpoints are undocumented and
JWT-gated, so Potato links to the UI rather than pretending to stream them.

**Annotations are missing after a rebuild** — expected, and the reason the
backup exists. Check the Dataset repo. If this was a `--demo` deployment, they are
gone.

## The demo catalog

The Spaces under the `Blablablab` organization are a separate, maintainer-run
catalog built from `deployment/huggingface-spaces/spaces_manifest.yaml`, not by
`potato deploy`. See [Potato on HuggingFace](../data-export/potato_on_huggingface.md).

## Related

- [Render](deploy-render.md) — free, no paid plan needed
- [DigitalOcean](deploy-digitalocean.md) — a persistent VM
- [Docker](docker.md) — the image a Space derives from
