# Deploying to Heroku

```bash
export HEROKU_API_KEY=...            # or log in with `heroku login`
potato deploy up myproject/config.yaml --provider heroku --backup hf --hf-token hf_...
```

This creates a Heroku app on the container stack, builds an image from the
published Potato image plus your project, and runs one Basic dyno ($7/month).
The task is served at the app's `*.herokuapp.com` address over HTTPS.

Heroku has been in sustaining-engineering mode since February 2026: accounts
that pay by card keep working, but the platform gets no new features. Use it if
your lab already has an account. Otherwise, [Fly](deploy-fly.md),
[Railway](deploy-railway.md) or [Lightsail](deploy-aws.md) are better choices.

## Backup (required)

A dyno's filesystem is wiped every time the dyno restarts, and Heroku restarts
every dyno at least once a day. Potato will not create the app until you choose
where the data goes:

```bash
--backup hf --hf-token hf_...        # a private HuggingFace dataset
--backup s3 --s3-bucket my-bucket    # an S3 (or R2, B2) bucket
--demo                               # the annotations are disposable
```

The backup is restored into the new dyno each time it starts, before the server
loads anything, so annotators continue where they left off. See
[Backups](deploy-backups.md).

## Dyno sizes

| `--size` | RAM | Monthly | |
|---|---|---|---|
| `eco` | 512 MB | $5 (shared pool) | Sleeps after 30 minutes idle; each wake restores from the backup |
| `basic` | 512 MB | $7 | The default |
| `standard-1x` | 512 MB | $25 | |
| `standard-2x` | 1 GB | $50 | For large datasets or many annotators at once |

Potato uses about 140 MB when idle. If the logs show `R14 (Memory quota
exceeded)`, use `--size standard-2x`.

## How the image is built

Heroku runs containers as an arbitrary non-root user rather than the image's
own, so Potato makes the task directory writable by any user when it builds the
image. The project, a Dockerfile and `heroku.yml` are uploaded through the
Platform API, and Heroku builds the image itself. You don't need Docker
installed.

If the build fails on that route, `--heroku-registry` builds the image locally
with Docker instead, for `linux/amd64`, and pushes it to Heroku's registry.

Secrets (the session key, the admin key, backup credentials) are set as config
vars. They are not built into the image.

## Managing the app

```bash
potato deploy status config.yaml
potato deploy logs config.yaml -f
potato deploy pull config.yaml          # over the admin API, or use the backup
potato deploy destroy config.yaml       # deletes the app; the backup is kept
```

Running `up` again uploads the new project and rebuilds the same app.

## Related

- [Backups](deploy-backups.md)
- [Deploy buttons](deploy-buttons.md): a "Deploy to Heroku" button for your repository
- [Installing and running Potato](installation.md)
