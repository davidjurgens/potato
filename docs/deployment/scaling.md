# Scaling & Large Datasets

This page explains how Potato behaves with large datasets, what is and isn't a
bottleneck, and the knobs available for big projects. It exists partly to
correct a common misconception that Potato "struggles with massive datasets" or
uses "un-indexed files" — neither is accurate for how the item store actually
works.

## How items are stored and looked up

Potato does **not** scan un-indexed files to find items. On load, every item is
placed into an in-memory, ID-keyed `OrderedDict`
(`ItemStateManager.instance_id_to_instance`). Lookups by instance ID are **O(1)**
hash lookups (`get_item()`), not linear scans. On top of that primary index,
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

## Related

- [Task Assignment](../advanced/task_assignment.md)
- [Heterogeneous Coverage](../advanced/heterogeneous_coverage.md)
- [Data Directory & Watching](../configuration/data_directory.md)
- [Export Formats](../data-export/export_formats.md)
