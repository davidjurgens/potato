# Deploying to Render

The free path. No credit card, no CLI, no git repository — one API call deploys
the published Potato image and Render gives it HTTPS.

```bash
export RENDER_API_KEY=rnd_...
potato deploy up myproject/config.yaml --provider render --hf-token hf_...
```

## Read this before using the free tier

A free Render instance has **no disk** and **stops after 15 minutes idle**. When
it stops, everything written to its filesystem is gone: annotations, user state,
the project database. Fifteen minutes after your last annotator closes the tab.

So `potato deploy` will not create a free service unless you have said what
happens to the data. Three ways to answer:

```bash
# 1. Mirror annotations to a HuggingFace Dataset as they arrive
potato deploy up config.yaml --provider render --hf-token hf_...

# 2. Pay for a disk
potato deploy up config.yaml --provider render --plan starter --volume-gb 1

# 3. Say the data is disposable
potato deploy up config.yaml --provider render --demo
```

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

`potato deploy pull` does not work here: there is no SSH into a Render service.
Two routes instead.

**The HuggingFace backup**, if you deployed with `--hf-token`. Annotations are
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

Running `up` again triggers a redeploy of the existing service rather than
creating a second one.

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

- [Docker](docker.md) — the image this deploys
- [DigitalOcean](deploy-digitalocean.md) — a persistent VM, from $18/month
- [HuggingFace Spaces](deploy-huggingface.md) — an ephemeral host with the same
  backup story
