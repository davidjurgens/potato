# Scaling & Large Datasets

This page explains how Potato behaves with large datasets, what is and isn't a
bottleneck, and the knobs available for big projects. It exists partly to
correct a common misconception that Potato "struggles with massive datasets" or
uses "un-indexed files" — neither is accurate for how the item store actually
works.

## How items are stored and looked up

Potato does **not** scan un-indexed files to find items. On load, every item
goes into an ID-keyed store behind `ItemStateManager`. Lookups by instance ID
are **O(1)** hash lookups, not linear scans. On top of that primary index,
Potato maintains secondary indexes:

- a **category → instance IDs** index (`category_to_instance_ids`) for category
  assignment, and
- per-user assignment/ordering lists for the annotation queue.

A regression guard for this behavior lives in
`tests/performance/test_large_dataset_boot.py`, which asserts that lookup cost
does not grow with dataset position (a list scan would fail it).

## Memory and boot profile

The dataset is held in memory, so memory scales roughly linearly with the number
of items. Potato has been optimized so this is the *only* thing that scales with
size — the machine-learning stack is **not** imported at boot unless a feature
that needs it is enabled.

Measured on the reference dataset (see the v2.6.0 release notes):

| Metric | Before | After |
|--------|--------|-------|
| Resident memory (RSS) | ~750 MB | ~365 MB |
| 50k-item boot time | ~10 s | ~5.7 s |

These improvements come from making the embedding / `sentence-transformers`
stack lazy (loaded on demand via a `find_spec` probe rather than at import).
Two guards protect it:

- `tests/unit/test_boot_import_weight.py` asserts `import potato.flask_server`
  does **not** pull in `torch` / `transformers` / `sentence_transformers`.
- `tests/performance/test_large_dataset_boot.py` benchmarks load time, O(1)
  lookups, and (optionally) an RSS ceiling. Reproduce the release-note figures
  locally with:

  ```bash
  POTATO_BENCH_N=50000 POTATO_BENCH_RSS=1 pytest tests/performance -q
  ```

### Per-item memory, measured

Steady-state resident bytes per item, reproducible with
`python scripts/benchmark_item_store.py --items 50000`:

| Item shape | Default (in memory) | `backend: paged` | 1M items, default | 1M items, paged |
|---|---|---|---|---|
| Vision (`image_url` + two fields) | 932 B | 675 B | 0.93 GB | 0.68 GB |
| Text (~540 unique characters) | 1430 B | 695 B | 1.43 GB | 0.70 GB |

## Paging item payloads to disk

For corpora where half a gigabyte matters — Open Images is about 9M items, so
roughly 8.4 GB resident against 6.1 GB paged — item payloads can live in a
SQLite file with a small in-memory cache:

```yaml
item_store:
  backend: paged      # default: memory
  cache_size: 2048    # payloads kept resident
  # path: ...         # defaults to <output_annotation_dir>/.item_cache.sqlite
```

The file is a **cache**: it is rebuilt from your data files on every boot, is
never read from a previous run, and can be deleted at any time.

Read the table above before turning this on. **Paging saves 28% on vision items
and 51% on text — not an order of magnitude.** Once the payload is out of
memory, what remains is the item object and the id bookkeeping, and those do not
page. In exchange, loading the corpus takes about 2.5× as long and a full scan
about 6×; a single item read goes from ~1 µs to ~6 µs, which is nothing against
a request.

Below a million items this buys a slower server and no benefit. The default is
the right choice for almost every project.

## Practical guidance for large projects

- **Shard work across cohorts.** Use [batch assignment](../advanced/task_assignment.md)
  so each annotator is only ever assigned a slice of the data. Annotators never
  load the whole dataset — they load their queue.
- **Cap per-annotator workload.** `per_annotator_quota` (see
  [Heterogeneous Coverage](../advanced/heterogeneous_coverage.md)) bounds how many
  items any one user is assigned.
- **Stream data in over time.** With `data_directory` +
  [directory watching](../configuration/data_directory.md) you can start with a
  subset and add files while the server runs, rather than loading everything up
  front.
- **Right-size the host.** As a rule of thumb, budget memory for the full item
  set plus per-user state. For very large corpora, prefer a machine with more RAM
  over splitting into multiple servers.

## Time between instances

When an annotator presses Next, the page saves the current answer, tells the
server to move, and loads the next page. The page shows "Loading annotation
interface" until that page's scripts have run and its saved spans have
arrived. On the example tasks the server renders a page in 10–30 ms, so most of the
wait is network round trips, and the number of round trips matters more than
bandwidth.

What Potato does about it:

- **Scripts and stylesheets are cached.** Each script and stylesheet URL in a page
  carries a hash of the file's contents (`?v=45&h=3f2a9c…`). A URL whose hash matches the
  file is served with `Cache-Control: immutable` and a one-year lifetime, so
  after the first page the browser does not ask for it again. Editing a file
  changes its hash, and the next page load picks up the new version. Fonts
  and stylesheets loaded from inside a stylesheet (`@import`, `url()`) are
  hashed the same way. Nothing needs configuring.
- **Feature scripts load only where they are used.** A radio-button task does
  not download the PDF viewer or the audio-dialogue player.
- **Navigation does not render the page twice.** The Next button's request
  gets a short JSON reply, and the page is then loaded once.

### Use a server that keeps connections open

`potato start` runs Werkzeug's built-in server, which closes the connection
after every response. Each request then pays for a new TCP connection, plus a
TLS handshake when Potato serves HTTPS itself. A first page load of a simple
radio-button task opens about 45 connections. Caching removes most of them from later pages, but the
first page of every session still pays in full.

For annotators working over the internet, rather than on the same machine or
network, run Potato behind something that keeps connections open:

- the [Docker image](docker.md), which runs gunicorn with threaded workers
  (they keep connections open by default), or
- a reverse proxy such as nginx or Caddy in front of `potato start`. The
  browser's connections end at the proxy, which keeps them open. See
  [Reverse Proxy](reverse-proxy.md).

### Checking a slow deployment

Open the browser's developer tools on the annotation page, go to the Network
tab, and press Next.

- If each `/static/...` request shows a status of 304 rather than "(disk cache)"
  or "(memory cache)", the page was served without content hashes. Check that
  nothing between the browser and Potato rewrites or strips query strings.
- If most requests show a long "Initial connection" or "SSL" phase, connections
  are not being reused. Use one of the setups above.
- If the `/annotate` request itself is slow, the time is on the server. Check
  server load and the size of the item being rendered.

## Bulk exports

Exports are written to **files on disk** (CSV/TSV/JSON/Parquet and the
task-specific formats), not streamed through the browser. The exporter currently
materializes the annotation records in memory before writing, so peak memory
during an export scales with the size of the export. For typical research
datasets this is not a concern; for very large exports on a memory-constrained
host, export per-cohort or per-batch rather than the entire project at once.

> Future improvement: a chunked/streaming writer that bounds export memory
> regardless of dataset size. Tracked as a follow-up; the current disk-write
> design is correct and lossless, just memory-proportional to the export.

## The admin dashboard

`GET /admin/api/instances` computes a row for every instance before it filters,
sorts and paginates, which it has to do to sort by disagreement. It gathers the
per-instance statistics in a single pass over annotators, so the cost follows
the number of annotations rather than instances × annotators: a page of 25 rows
takes about 750 ms over 20,000 instances with 20 annotators. See
[Performance Considerations](../administration/admin_dashboard.md#large-datasets).

## Related

- [Admin Dashboard](../administration/admin_dashboard.md)
- [Docker](docker.md) and [Reverse Proxy](reverse-proxy.md)
- [Task Assignment](../advanced/task_assignment.md)
- [Heterogeneous Coverage](../advanced/heterogeneous_coverage.md)
- [Data Directory & Watching](../configuration/data_directory.md)
- [Export Formats](../data-export/export_formats.md)
