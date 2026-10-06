# Deploying to Render

The free path. No credit card, no CLI, no git repository: one API call deploys
the published Potato image and Render gives it HTTPS.

```bash
export RENDER_API_KEY=rnd_...
potato deploy up myproject/config.yaml --provider render --backup hf --hf-token hf_...
```

Render runs the image and has no way to upload files to it, so your project is
put in the backup's storage and the container downloads it when it starts.
Every Render deployment therefore needs `--backup hf` or `--backup s3`, even on
a paid plan with a disk. HuggingFace is the better choice here, because its
download link does not expire; see [Backups](deploy-backups.md#getting-the-project-onto-the-host).

## Read this before using the free tier

A free Render instance has **no disk** and **stops after 15 minutes idle**. When
it stops, everything written to its filesystem is gone: annotations, user state,
the project database. Fifteen minutes after your last annotator closes the tab.

So `potato deploy` will not create a free service unless you have said what
happens to the data. Three ways to answer:

```bash
# 1. Back up to a HuggingFace Dataset, and restore from it on every start
potato deploy up config.yaml --provider render --backup hf --hf-token hf_...

# 2. Pay for a disk
potato deploy up config.yaml --provider render --plan starter --volume-gb 1

# 3. Say the data is disposable (the project still goes to the backup storage)
potato deploy up config.yaml --provider render --demo --backup hf --hf-token hf_...
```

With a backup, an instance that stopped while idle restores the annotations
when it starts again, so annotators continue where they left off.

The backup is the usual answer for a pilot: it costs nothing, needs only a
HuggingFace account, and the annotations end up somewhere you can share and
version. A paid instance is the answer for a study that will run for weeks.

## Cost

| Plan | Monthly | Disk | Idle behaviour |
|---|---|---|---|
| `free` | $0 | none | stops after 15 minutes |
| `starter` | $7 | $0.25/GB | stays up |
| `standard` | $25 | $0.25/GB | stays up |

Pass the plan with `--plan`. A disk needs `starter` or higher; Render does not
attach one to a free instance.

## Getting an API key

<https://dashboard.render.com/u/settings#api-keys>. Potato reads `--token` and
then `RENDER_API_KEY`, and never writes either to disk.

## One instance

The service is pinned to a single instance and Potato will not raise it.

The item pool, the assignment queue and every annotator's state live in memory,
in the process. A second instance gets its own copy of all three: it hands out
instances the first already assigned, and whichever instance saves last
overwrites the other's annotations. Nothing reports it.

Concurrency comes from threads, which share one copy of that state. The default
of 8 serves the dozens of simultaneous annotators a typical study has.

## Getting the data back

`potato deploy pull` works here over HTTPS, through the admin archive endpoint;
there is no SSH into a Render service. If the service is down, the backup holds
the same data.

**The HuggingFace backup.** Annotations and the project databases are
committed to a private Dataset every five minutes:

```bash
huggingface-cli download --repo-type dataset <you>/<name>-annotations \
  --local-dir ./annotations
```

**The admin export API**, which works on any deployment. The key is in
`.potato/secrets.json`:

```bash
curl -H "X-API-Key: $(python -c "import json;print(json.load(open('.potato/secrets.json'))['<name>']['admin_api_key'])")" \
  -X POST https://potato-<name>.onrender.com/admin/api/export
```

## Managing a deployment

```bash
potato deploy status myproject/config.yaml
potato deploy up myproject/config.yaml --provider render   # push changes
potato deploy destroy myproject/config.yaml
```

Running `up` again uploads the new project, updates the service's environment,
and redeploys the existing service rather than creating a second one.

`potato deploy logs` is not supported: Render's log API needs a paid plan and a
websocket. Read them in the dashboard.

Deleting a service deletes its disk with it. Anything already in the backup
Dataset is unaffected, because `destroy` does not touch that repo.

## Troubleshooting

**"Refusing to create a free Render service"** — see
[the free tier](#read-this-before-using-the-free-tier). The message lists the
three ways forward.

**The first request takes a minute** — a free instance that has spun down starts
on the next request. `potato deploy status` says so when it sees this.

**The service never became live** — the build log in the Render dashboard says
why. The most common cause is an image tag that does not exist.

**`suspended`** — Render suspends services for billing or for exceeding a free
tier limit. The dashboard has the reason.

## Related

- [Deploying a task](one-command-deploy.md) — choosing a target
- [Docker](docker.md) — the image this deploys
- [DigitalOcean](deploy-digitalocean.md) — a persistent VM, from $18/month
- [HuggingFace Spaces](deploy-huggingface.md) — an ephemeral host with the same
  backup story
