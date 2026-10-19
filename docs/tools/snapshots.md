# Project Snapshots

A paper describes a dataset as it was when the paper was written. The project
behind it keeps changing: more items, corrected labels, new annotators. A
snapshot freezes the project's config, data and annotations under an id a
paper can cite, with a content hash a reader can check and the agreement
numbers as they stood.

## Commands

All commands take the project's config file and work whether or not the
server is running.

```bash
potato snapshot create config.yaml --note "pilot round finished" --tag pilot
potato snapshot list config.yaml
potato snapshot show config.yaml pilot
potato snapshot diff config.yaml pilot latest
potato snapshot tag config.yaml 20261019-120000 paper-v1
potato snapshot verify config.yaml paper-v1
```

| Command | What it does |
|---|---|
| `create` | Freeze the project. If nothing has changed since the latest snapshot it says so and writes nothing; `--force` writes one anyway. `--tag` names it |
| `list` | Snapshots, newest first, with tags and counts |
| `show [ref]` | One snapshot's hashes, counts and per-scheme alpha |
| `diff <old> [new]` | Items and annotators added or removed, answers added, removed or changed, and the change in alpha per scheme |
| `tag <ref> <name>` | Point a name at a snapshot. A tag can be moved to another snapshot; the snapshot itself never changes |
| `verify [ref]` | Re-hash the snapshot's files and contents against its manifest |

A `ref` is a snapshot id, the start of one (`20261019-1205`), a tag, or
`latest`. `list`, `show` and `diff` take `--json`.

## Snapshot contents

Snapshots are written to `snapshots/<id>/` in the task directory. The id is
the UTC time and the first 8 characters of the content hash, for example
`20261019-120000-335ae51e`.

| File | Contents |
|---|---|
| `bundle.tar.gz` | The config file, the study's files (see below), the annotation output directory and the project's SQLite databases (memos, codebook, labeling engine) |
| `annotations.jsonl` | One row per annotator, item and scheme, with every label and span saved for it, in a fixed order. `diff` reads this |
| `items.json` | The item ids in the data files |
| `manifest.json` | The id, time, note, Potato version, hashes, counts, its place in the sequence of snapshots, and the agreement summary Paper Mode computes |

The study's files are the data files plus every file the config refers to:
phase and survey files, attention-check and gold item files, consent and
instruction pages, custom layouts. A file referred to from a referenced YAML
file is included too. `manifest.json` lists them under `project_files`.
Folders the config names, such as a media folder, are listed under
`referenced_directories` but not copied, since they can be any size.

A file outside the task directory is stored as `external/<name>`, and
`create` warns about it: Potato refuses to start a config that points outside
its project, so a study cited that way cannot be run as written.

The files are written read-only, and the folder is renamed into place only
once every file is complete.

### Credentials are left out

Snapshots are made to be cited and handed on, so the bundle leaves out:

- The account roster, with its password hashes. That is
  `authentication.user_config_path` when it is set, and otherwise the server's
  default `user_config.json` beside the output directory (inside it when
  `output_annotation_dir` ends in `/`).
- Any file named under a config key that mentions a password, secret, token,
  credential or API key.
- `admin_api_key.txt`.

`manifest.json` lists each file left out, and why, under `omitted`, and
`create` prints them. None of them is in the content hash. A restored snapshot
therefore has no accounts: annotators register again, or you restore the
roster from your own copy.

### The content hash

`content_hash` is a SHA-256 over the config file, the study's files, the item
ids and the annotation rows. Editing a survey question is a change. The SQLite databases are in the bundle but not in the
hash, because the server rewrites them as it runs, and a hash that changed with
every rewrite could not tell a reader whether the annotations had changed.

`verify` checks three things. The bundle and `annotations.jsonl` must match the
hashes in the manifest. The config and data inside the bundle, together with
the annotation rows, must hash to `content_hash`. Someone holding only the
snapshot folder can therefore confirm it is the one a paper cites.

## In the admin dashboard

The **Publish Dataset** page has a Snapshots card that lists the project's
snapshots and creates one with a note and an optional tag. The same is
available over HTTP:

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/admin/api/snapshots
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"note": "pilot round finished", "tag": "pilot"}' \
     http://localhost:8000/admin/api/snapshots
```

`POST` returns 201 with the new manifest. If nothing has changed it returns
200 with `"unchanged": true` and the existing snapshot. A tag that is not
1-64 letters, digits, `.`, `_` or `-` gets a 400, and nothing is written.

## Publishing

Every publish (archive, Hugging Face or Zenodo) freezes a snapshot first, or
reuses the latest one if nothing has changed. The dataset card's citation
section names it:

> This release is Potato snapshot `20261019-044005-335ae51e` (content hash
> `335ae51e…`). Anyone holding the project folder can check that their copy is
> this one with `potato snapshot verify config.yaml 20261019-044005-335ae51e`.

If freezing fails, the release still goes out and the failure is reported as
a warning.

## Troubleshooting

**`This project has no snapshots yet`.** Run `potato snapshot create` first.

**`'2026' matches 3 snapshots`.** The prefix is ambiguous. Use more of the id,
or a tag.

**`Another snapshot create is writing … right now`.** Two creates of the same
content started in the same second. One of them writes the snapshot; check
with `potato snapshot list`.

**Deleting a snapshot.** Its files are read-only. Make them writable and
remove the folder (`chmod -R u+w snapshots/<id> && rm -rf snapshots/<id>`),
then remove any tag that pointed at it from `snapshots/tags.json`.

## Related

- [Dataset Publishing](../data-export/publishing_datasets.md)
- [Paper Mode](../advanced/paper_mode.md)
