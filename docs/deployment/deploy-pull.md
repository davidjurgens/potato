# Getting Annotations Back

```bash
potato deploy pull myproject/config.yaml
```

Downloads everything a deployment has collected into a timestamped directory,
checks what arrived, and prints the result. Nothing is deleted from the host.

```
Pulled to ./potato-pull-pilot-20260820-161905
  downloaded over HTTPS from https://potato-pilot.onrender.com
  project.sqlite snapshotted server-side with the SQLite backup API
  files      27
  size       3.6MB
  annotators 24
  databases  project.sqlite
```

## What comes back

- The whole annotation output directory: every annotator's `user_state.json`,
  their annotated instances, the assignment file, `potato.log`, and any
  adjudication or MACE output.
- `project.sqlite` — memos, the codebook, cases, typing sessions, the review
  workflow. None of it can be regenerated from the annotations.
- `datasets.sqlite`, when the deployment has one.

Two things are deliberately left behind. `.item_cache.sqlite` is rebuilt from
the data files on demand and is often the largest file there. `admin_api_key.txt`
is the credential guarding the endpoint doing the download.

## The SQLite snapshot

`project.sqlite` runs in WAL mode with a live writer. The `.sqlite` file on disk
is not a complete database on its own — the `-wal` sidecar holds committed pages
it does not have. Copy the file alone and you get a database that is corrupt or
missing recent work, and nothing tells you at the time. It opens. It just has
holes.

So every transport snapshots through SQLite itself before copying, and if the
snapshot fails, the pull says so rather than falling back to a file copy. The
downloaded databases are then opened and integrity-checked locally, and a pull
that returns an unreadable one is reported as a failure.

This is worth knowing if you ever fetch the files yourself:

```bash
# Wrong — silently gives you a damaged database
scp root@host:/opt/potato/app/project.sqlite .

# Right
ssh root@host "sqlite3 /opt/potato/app/project.sqlite \".backup /tmp/snap.sqlite\""
scp root@host:/tmp/snap.sqlite ./project.sqlite
```

## Transports

Potato picks the best available transport for the provider.

| Provider | Transport |
|---|---|
| `digitalocean` | SFTP over the deploy key, falling back to HTTPS |
| `huggingface` | The backup Dataset; the Space itself for a `--demo` deployment |
| `render` | HTTPS |
| `local` | `docker cp` |

The HTTPS route uses `GET /admin/api/data/archive`, authenticated with the admin
API key that `potato deploy` generated and stored in `.potato/secrets.json`. It
needs no shell, which is why it works on Render and anything serverless — the
hosts most likely to lose their disk in the first place.

You can use it by hand against any deployment:

```bash
curl -H "X-API-Key: $ADMIN_KEY" \
  https://your-host/admin/api/data/archive -o annotations.tar.gz

# Or ask what it would send, before sending it
curl -H "X-API-Key: $ADMIN_KEY" https://your-host/admin/api/data/manifest
```

## Verification and destroy

`potato deploy destroy` refuses to run on a deployment that has never been
successfully pulled, so what counts as "successfully" matters.

A pull that returns zero files is **not** recorded as one. An empty result and a
study nobody has annotated yet look identical from the outside, and only one of
them means the data is safe. If the task genuinely has no annotations, say so:

```bash
potato deploy pull config.yaml --allow-empty
```

An unreadable database counts the same way. `destroy` keeps refusing until a
good pull succeeds.

`--force` overrides `destroy` entirely, and discards whatever is on the host.

## Options

| Flag | Purpose |
|---|---|
| `--dest DIR` | Where to write, instead of `./potato-pull-<name>-<timestamp>/` |
| `--allow-empty` | Record a pull that returned nothing |
| `--name` | Which deployment, when a config has several |

## Continuous backup

Pulling is something you remember to do. For a host whose filesystem does not
survive a restart — a Space, a free Render instance — that is not good enough,
so those deployments also mirror annotations to a HuggingFace Dataset every few
minutes. It works on every provider despite being documented under
[HuggingFace Spaces](deploy-huggingface.md#backing-up-from-any-provider).

## Troubleshooting

**"rejected the admin API key"** — `.potato/secrets.json` no longer matches what
the server has, usually because the deployment was recreated. On a provider with
SSH you can read the key from `/opt/potato/potato.env` on the host.

**"Nothing came back"** — either nobody has annotated, or `output_annotation_dir`
on the server is not where the config says. The manifest endpoint shows what the
server thinks it has.

**"No `user_state.json` anywhere in the result"** — files arrived, so the
transport worked. The output directory is the thing to check.

**"has no admin data-archive endpoint"** — the deployment is running a Potato
older than the one that added it. Redeploy, or use the provider's own transport.

## Related

- [DigitalOcean](deploy-digitalocean.md)
- [Render](deploy-render.md)
- [HuggingFace Spaces](deploy-huggingface.md)
