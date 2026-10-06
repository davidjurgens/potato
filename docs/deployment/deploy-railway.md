# Deploying to Railway

```bash
export RAILWAY_API_TOKEN=...         # https://railway.com/account/tokens
potato deploy up myproject/config.yaml --provider railway --backup hf --hf-token hf_...
```

This creates a Railway project with one service running the published Potato
image, a volume mounted as the task directory, and a `*.up.railway.app` domain.
Railway bills for the RAM, CPU and volume you use, by the minute. The $5 Hobby
plan includes $5 of usage, and a small task that is always on usually costs
$10–20 a month.

## Options

The service is set to one replica that never sleeps, with no overlap between
an old deployment and its replacement. With overlap, two containers would use
the same volume at once: two copies of the item pool, and whichever saved last
would win.

Railway mounts volumes as root, so the service runs with `RAILWAY_RUN_UID=0`.
The image hands the task directory to its own user and switches to that user
before the server starts, so Potato itself never runs as root.

## Getting the project onto the service

Railway has no way to upload files, so the project is put in your backup
storage and downloaded when the container starts. A deploy therefore needs
`--backup hf` or `--backup s3`. With the volume, the project is downloaded once
per deploy. See [Backups](deploy-backups.md#getting-the-project-onto-the-host).

## Managing the service

```bash
potato deploy status config.yaml
potato deploy logs config.yaml       # the latest deployment's logs
potato deploy pull config.yaml       # over the admin API
potato deploy destroy config.yaml    # deletes the project, volume included
```

Running `up` again updates the service's variables and redeploys it.

## A Railway button

Railway publishes templates from its dashboard, not from a file in your
repository. `potato deploy button config.yaml --target railway` prints the
steps. See [Deploy buttons](deploy-buttons.md).

## Related

- [Installing and running Potato](installation.md)
- [Fly.io](deploy-fly.md)
- [Backups](deploy-backups.md)
