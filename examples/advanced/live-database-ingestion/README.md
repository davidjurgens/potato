# Live Database-Backed Instance Ingestion

Annotate a database table that is still being written to. Rows inserted after
the server starts become annotatable within one poll interval — no restart.

## Requirements

```bash
pip install 'potato-annotation[db]'
```

SQLite needs no driver. PostgreSQL additionally needs `psycopg2-binary`, MySQL
needs `pymysql`.

## Running it

From the repository root:

```bash
# 1. Create the database with 5 rows
python examples/advanced/live-database-ingestion/seed_db.py

# 2. Start Potato
python potato/flask_server.py start examples/advanced/live-database-ingestion/config.yaml -p 8000
```

Open <http://localhost:8000>, register a user, and annotate through the five
seeded messages.

Then, **while the server is still running**, add more:

```bash
python examples/advanced/live-database-ingestion/seed_db.py --add 3
```

Within about five seconds those three rows are served to annotators. Nothing
was restarted and no file was touched.

## What to look at

Check the ingestion metrics (the config sets no `admin_api_key`, so log in
first and use the session cookie):

```bash
curl -b cookies.txt http://localhost:8000/admin/api/data_sources/live
```

```json
{
  "enabled": true,
  "sources": [{
    "source_id": "live_instances",
    "is_running": true,
    "polls_total": 42,
    "polls_failed": 0,
    "rows_fetched": 8,
    "items_added": 8,
    "duplicates_skipped": 0,
    "consecutive_failures": 0,
    "last_error": null,
    "last_cursor": "2026-07-29T12:34:56.789012+00:00"
  }]
}
```

Force a poll instead of waiting for the interval:

```bash
curl -b cookies.txt -X POST \
  http://localhost:8000/admin/api/data_sources/live_instances/live/poll
```

## Things worth trying

**Restart resumption.** Stop the server, run `--add 2`, start it again. All ten
rows are in the pool: the startup read replays the table so admin views and
exports stay complete, and deduplication means nothing is added twice. The
cursor in `annotations/live_ingestion_state.json` still governs the *poller*,
so it never re-delivers rows it has passed. Set `replay_on_start: false` to
resume from the cursor instead — cheaper for a large table, but the pool then
holds only rows newer than the cursor.

**Failure handling.** Rename `data/live.db` while the server runs. Polls start
failing and backing off, `consecutive_failures` climbs in the admin API, and
annotation of already-loaded items keeps working. Rename it back and ingestion
resumes on its own.

**Deduplication.** Run `--add 3` twice with the same content. Every row has a
distinct id, so all six arrive; re-running the *seed* would produce ids that
already exist and be skipped, leaving existing annotations untouched.

## Configuration notes

The config is commented, but three choices are worth calling out:

- **`cursor_column: created_at` with `overlap_seconds: 2`.** A wall-clock
  cursor is best-effort — a transaction can commit out of timestamp order and
  be stepped over. The overlap re-reads the boundary; duplicates it produces
  cost nothing. A monotonic id column would be strictly correct.
- **`assignment_strategy: fixed_order`.** `batch` is rejected at startup with
  live ingestion, because it only serves items from a pre-declared cohort.
- **`max_annotations_per_user` is unset.** With live ingestion on it defaults
  to unlimited rather than to the startup instance count, which is what keeps
  later arrivals assignable.

See [Remote Data Sources](../../../docs/configuration/remote_data_sources.md)
for the full option reference.
