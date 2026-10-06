# Backups

On some hosts, the disk does not outlast the process. Heroku dynos, Render's
free tier, ECS Express tasks and HuggingFace Spaces all start from an empty
filesystem after a restart, and they restart at least once a day. The backup
copies everything Potato has collected to storage you own while the study runs,
and copies it back when the server starts.

```bash
potato deploy up config.yaml --provider heroku --backup hf --hf-token hf_...
potato deploy up config.yaml --provider heroku --backup s3 --s3-bucket my-bucket
potato deploy up config.yaml --provider heroku --backup hf,s3 --hf-token hf_... --s3-bucket my-bucket
```

The backup works on every provider. On a VM it costs nothing extra and adds a
second copy of the data.

## What it copies

- **The annotation output directory**, file by file: every annotator's state,
  plus the account list in `user_config.json`.
- **`project.sqlite` and `datasets.sqlite`**, which hold memos, the codebook,
  cases and the review workflow. They are copied with SQLite's `.backup`, never
  as raw files: the live database runs in WAL mode while the server writes to
  it, and a copy of the file could be missing recent work or be corrupt.

A copy is made every `--backup-minutes` (default 5). Only files that changed
since the last copy are uploaded.

## Restoring at startup

When the server starts and finds no annotator data on its disk (no
`user_state.json` anywhere in the output directory), it downloads the latest
backup before it loads anything. That includes the account list, so annotators
log in with the same passwords and continue where they left off.

The restore never overwrites existing data. If the disk already holds
annotations, it is treated as the authoritative copy and left alone. The log
says which happened:

```
RESTORED 214 file(s) from the s3://my-bucket/potato/pilot backup into an empty task.
```

Without the restore, a backup only goes one way: after a restart the server
starts empty, an annotator who returns gets a new `user_state.json`, and the
next backup overwrites the copy that held their earlier work.

## HuggingFace

```bash
potato deploy up config.yaml --provider render --backup hf --hf-token hf_...
```

The backup goes to a **private** dataset, `<your account>/<name>-annotations`
by default (use `--hf-backup-repo owner/name` to pick another). The token needs
write access. It is given to the server as the `HF_TOKEN` secret and is never
written into the config or the bundle.

Image-only hosts (Render, Fly, Railway, ECS) also fetch the project from this
dataset when they start; see [Getting the project onto the host](#getting-the-project-onto-the-host).

To download the backup yourself:

```bash
huggingface-cli download --repo-type dataset you/pilot-annotations --local-dir ./backup
```

## S3 and compatible stores

```bash
export POTATO_S3_ACCESS_KEY_ID=...
export POTATO_S3_SECRET_ACCESS_KEY=...
potato deploy up config.yaml --provider heroku --backup s3 --s3-bucket my-bucket
```

The bucket must already exist. `--s3-endpoint` sends the backup to any service
with an S3-compatible API: Cloudflare R2, Backblaze B2, MinIO, or a university
object store.

```bash
potato deploy up config.yaml --provider fly --backup s3 \
    --s3-bucket my-bucket --s3-endpoint https://<account>.r2.cloudflarestorage.com
```

Use an access key that can reach only this bucket. It is stored in the
server's environment, where anyone with shell access to the server can read
it. Objects go under `potato/<name>/` (change this with `--s3-prefix`):
`annotations/…` for the output directory, `_databases/…` for the snapshots.

## Configuring it by hand

`potato deploy` writes this block into the bundled config. Outside deploy,
for example on your own server, add it to the config yourself:

```yaml
backup:
  schedule_minutes: 5
  restore_on_boot: true
  sinks:
    - type: huggingface
      repo_id: lab/pilot-annotations
    - type: s3
      bucket: my-bucket
      prefix: potato/pilot
      region: us-east-1
      endpoint_url: https://s3.example.edu      # optional
```

Credentials come from the environment (`HF_TOKEN`, `POTATO_S3_ACCESS_KEY_ID`,
`POTATO_S3_SECRET_ACCESS_KEY`) or from the sink entry itself, where `${VAR}`
references are expanded. The older `huggingface_backup:` block still works. It
is read as one HuggingFace sink with `restore_on_boot` turned off, so an
existing deployment behaves exactly as before.

## Getting the project onto the host

Render, Fly, Railway and ECS Express run the published image and have no way to
upload files to it. When the container starts, it downloads the project as a
tarball from `POTATO_BUNDLE_URL` and checks it against `POTATO_BUNDLE_SHA256`.
`potato deploy up` puts the tarball in the backup's own storage, so you don't
need a separate account:

- HuggingFace: `_bundle/<sha>.tar.gz` in the backup dataset, downloaded with
  the token. The link does not expire.
- S3: a presigned link, valid for at most seven days. On a host with a disk,
  the project is downloaded once per deploy. On a host without one it is
  downloaded on every restart, so after a week a restart fails until you run
  `up` again. The plan warns about this; use the HuggingFace backup on those
  hosts.

On Fly, a project smaller than 512 KB is sent inside the machine's
configuration and needs no storage at all.

Files in the output directory and the databases are never replaced by a new
version of the project.

## Related

- [Deploying a task](one-command-deploy.md)
- [Getting annotations back](deploy-pull.md)
- [HuggingFace Spaces](deploy-huggingface.md), where the backup is always on
