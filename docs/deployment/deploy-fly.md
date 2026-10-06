# Deploying to Fly.io

```bash
export FLY_API_TOKEN=...             # `fly tokens create org`, or a personal token
potato deploy up myproject/config.yaml --provider fly
```

This creates a Fly app with one Machine (shared CPU, 1 GB) and a 1 GB volume
holding the task. It is served at `https://<app>.fly.dev` using a shared IPv4
address, which is free. The cost is about $7 a month. Fly has no free tier, and
a new organization needs a card on file.

A Fly volume belongs to one Machine, which is what Potato needs: all the
annotators' state is in one process, and there is never a second copy that
could disagree with it.

## Options

| Flag | Default | |
|---|---|---|
| `--region` | `iad` | Any Fly region. |
| `--size` | `1024` | Machine memory in MB: 512, 1024, 2048 or 4096. |
| `--volume-gb` | `1` | Volume size. $0.15/GB per month. |
| `--owner` | `personal` | The Fly organization. |

The Machine is always running (`autostop` is off). A Machine that has stopped
takes several seconds to answer its first request, and an annotator would see
that as the page hanging.

## Getting the project onto the Machine

The Machine runs the published image, and the project arrives when it starts.
A project under 512 KB, which covers most configs and text datasets, is sent
inside the Machine's configuration. A larger one is uploaded to your backup
storage, so it needs `--backup hf` or `--backup s3`. See
[Backups](deploy-backups.md#getting-the-project-onto-the-host). Either way, the
project is downloaded once per deploy, not on every restart, because the volume
remembers which version it holds.

Secrets are stored with Fly's secrets mechanism, not in the Machine's
environment.

## Managing the app

```bash
potato deploy status config.yaml
potato deploy pull config.yaml       # over the admin API
potato deploy destroy config.yaml    # deletes the app and its volume
```

Running `up` again replaces the Machine's configuration in place: Fly stops the
Machine, applies the new configuration and starts it again, so there is never a
second Machine on the volume.

`potato deploy logs` is not available. Fly does not serve logs over its REST
API, so use `fly logs -a <app>`.

`destroy` deletes the volume along with the app, and `--keep-data` cannot keep
it. Pull first.

## Related

- [Installing and running Potato](installation.md)
- [Backups](deploy-backups.md)
- [Railway](deploy-railway.md), the other managed target with a volume
