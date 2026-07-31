# Remote Data Sources

Potato supports loading annotation data from various remote sources beyond local files, including URLs, cloud storage services, databases, and more.

## Overview

The data sources system extends Potato's data loading capabilities with:

- **Multiple source types**: URLs, Google Drive, Dropbox, S3, Hugging Face, Google Sheets, SQL databases
- **Partial loading**: Load data in chunks for large datasets
- **Incremental loading**: Auto-load more data as annotation progresses
- **Caching**: Cache remote files locally to avoid repeated downloads
- **Secure credentials**: Environment variable substitution for secrets

## Configuration

### Basic Structure

Add `data_sources` to your config.yaml to use extended data loading:

```yaml
# New: data_sources (alternative to data_files)
data_sources:
  - type: file
    path: "data/annotations.jsonl"

  - type: url
    url: "https://example.com/data.jsonl"
```

### Source Types

#### Local File

Load from a local file (same as `data_files` but in the new format):

```yaml
data_sources:
  - type: file
    path: "data/annotations.jsonl"  # Relative to task_dir
```

#### HTTP/HTTPS URL

Load from a remote URL:

```yaml
data_sources:
  - type: url
    url: "https://example.com/data.jsonl"
    # Optional: custom headers for authentication
    headers:
      Authorization: "Bearer ${API_TOKEN}"  # Uses env var
    # Optional: security settings
    max_size_mb: 100          # Max file size (default: 100)
    timeout_seconds: 30       # Request timeout (default: 30)
    block_private_ips: true   # SSRF protection (default: true)
```

#### Google Drive

Load from Google Drive (public or authenticated):

```yaml
# Public shared file
data_sources:
  - type: google_drive
    url: "https://drive.google.com/file/d/xxx/view?usp=sharing"

# Private file with service account
data_sources:
  - type: google_drive
    file_id: "xxx"
    credentials_file: "credentials/gdrive_service_account.json"
```

**Dependencies**: `pip install google-api-python-client google-auth`

#### Dropbox

Load from Dropbox:

```yaml
# Public shared file
data_sources:
  - type: dropbox
    url: "https://www.dropbox.com/s/xxx/file.jsonl?dl=0"

# Private file with access token
data_sources:
  - type: dropbox
    path: "/data/annotations.jsonl"
    access_token: "${DROPBOX_TOKEN}"
```

**Dependencies**: `pip install dropbox`

#### Amazon S3

Load from S3 or S3-compatible storage:

```yaml
data_sources:
  - type: s3
    bucket: "my-annotation-data"
    key: "datasets/items.jsonl"
    region: "us-east-1"  # Optional, default: us-east-1
    # Optional: explicit credentials (prefer env vars or AWS credentials file)
    access_key_id: "${AWS_ACCESS_KEY_ID}"
    secret_access_key: "${AWS_SECRET_ACCESS_KEY}"
    # Optional: for S3-compatible storage (MinIO, etc.)
    endpoint_url: "https://minio.example.com"
```

**Dependencies**: `pip install boto3`

#### Hugging Face Datasets

Load from Hugging Face Hub:

```yaml
data_sources:
  - type: huggingface
    dataset: "squad"           # Dataset name on Hub
    split: "train"             # train/validation/test
    subset: null               # Optional: dataset subset/config
    token: "${HF_TOKEN}"       # Optional: for private datasets
    # Field mapping
    id_field: "id"             # Field to use as item ID
    text_field: "context"      # Field to use as text
```

**Dependencies**: `pip install datasets`

#### Google Sheets

Load from Google Sheets:

```yaml
data_sources:
  - type: google_sheets
    spreadsheet_id: "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    sheet_name: "Sheet1"       # Optional: sheet name (default: first sheet)
    range: "A:Z"               # Optional: range to read
    credentials_file: "credentials/service_account.json"
    header_row: 1              # Row containing headers (1-indexed)
```

**Dependencies**: `pip install google-api-python-client google-auth`

#### SQL Database

Load from PostgreSQL, MySQL, or SQLite:

```yaml
# Using connection string
data_sources:
  - type: database
    connection_string: "${DATABASE_URL}"
    query: "SELECT id, text, metadata FROM items WHERE status = 'pending'"

# Using individual parameters
data_sources:
  - type: database
    dialect: postgresql  # postgresql, mysql, sqlite
    host: "localhost"
    port: 5432
    database: "annotations"
    username: "${DB_USER}"
    password: "${DB_PASSWORD}"
    table: "items"       # Simple table select
    id_column: "id"
    text_column: "text"
```

**Dependencies**: `pip install sqlalchemy psycopg2-binary` (PostgreSQL) or `pip install sqlalchemy pymysql` (MySQL). SQLAlchemy alone is also available as `pip install 'potato-annotation[db]'`.

#### Live Ingestion (Database)

By default a database is read once at startup. Add a `live_ingestion` block and Potato polls it in the background, so rows created *after* the server started become annotatable without a restart.

```yaml
data_sources:
  - id: live_instances          # set an explicit id — see the warning below
    type: database
    connection_string: "${DATABASE_URL}"
    query: "SELECT id, text, metadata, created_at FROM instances"
    live_ingestion:
      enabled: true
      poll_interval_seconds: 5
      cursor_column: created_at
      tiebreaker_column: id     # defaults to id_column
```

Polling is cursor-based, not `OFFSET`-based. Offsets are wrong for a table being written to: insert a row near the front and every later page shifts, silently skipping or repeating items.

##### Options

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Turn on background polling for this source |
| `poll_interval_seconds` | `5.0` | Seconds between polls (0.5–3600) |
| `cursor_column` | — | Column whose ascending order defines "newer". Required unless the query supplies its own `:cursor` |
| `tiebreaker_column` | `id_column` | Second sort key, so rows sharing a cursor value are not skipped |
| `initial_cursor` | none | Where to start on a first run. Required in explicit-`:cursor` mode |
| `batch_size` | `500` | Maximum rows fetched per poll |
| `overlap_seconds` | `0.0` | Rewind the cursor by this much before each read. See "Choosing a cursor column" |
| `safety_lag_seconds` | `0.0` | Refuse to read rows newer than `now - lag`, keeping the cursor behind the write frontier |
| `backoff_initial_seconds` | `1.0` | First retry delay after a failure |
| `backoff_max_seconds` | `300.0` | Ceiling on the exponential backoff |
| `max_consecutive_failures` | `0` | Stop the worker after this many failures in a row. `0` = retry forever |
| `stop_after_items` | `0` | Stop ingesting after this many items. `0` = unlimited |
| `replay_on_start` | `true` | Re-read the source from the beginning at startup. See "Restarts" |

##### Choosing a cursor column

**Prefer a monotonic column** — an auto-incrementing `id BIGSERIAL`, or an insert sequence. A wall-clock column like `created_at` is only best-effort: a transaction that began before a poll can commit after it with an earlier timestamp, and the cursor will already have moved past it.

If you must use a timestamp, set `overlap_seconds` (2 is usually plenty). It rewinds the cursor slightly on every read, so boundary rows are fetched again — and re-fetched rows are dropped by ID deduplication, so the only cost is a little bandwidth.

The `(cursor, tiebreaker)` pair also matters. With `cursor_column` alone, three rows sharing one timestamp and a batch size of two would leave the third permanently unread. Potato always orders by both and remembers both.

##### Two query modes

**Managed (recommended).** Write a plain `SELECT`; Potato generates the keyset predicate, the ordering and the `LIMIT`:

```sql
SELECT * FROM ( <your query> ) AS potato_live
WHERE created_at > :cursor_value
   OR (created_at = :cursor_value AND id > :cursor_tiebreak)
ORDER BY created_at, id LIMIT 500
```

**Explicit.** If your query already contains a `:cursor` placeholder, Potato only binds the value and appends the `LIMIT`. Ordering and tie-breaking become your responsibility, and `initial_cursor` is then required — `col > NULL` matches zero rows, silently and forever:

```yaml
query: "SELECT id, text, created_at FROM instances WHERE created_at > :cursor ORDER BY created_at, id"
live_ingestion:
  enabled: true
  cursor_column: created_at
  initial_cursor: "1970-01-01T00:00:00+00:00"
```

##### Behaviour

- **Deduplication** is by instance ID. A row whose ID is already in the pool is skipped, never overwritten, so existing annotations on it are preserved.
- **Database failures never crash the server.** A failed poll backs off exponentially (with jitter) and retries; annotation carries on with the items already loaded.
- **Polling never blocks annotation requests.** The poll thread holds no lock that the request path needs.

##### Restarts

The cursor is persisted to `live_ingestion_state.json` in your `output_annotation_dir`, so the *poller* always resumes where it left off rather than rescanning the table.

The startup read is a separate question. By default (`replay_on_start: true`) Potato re-reads the source from the beginning when it boots, exactly as a non-live `type: database` source does. Deduplication means nothing is added twice, and it keeps the item pool complete — admin views, exports and adjudication all read that pool, so a pool holding only rows that arrived since the last shutdown would misreport the corpus.

Set `replay_on_start: false` for a table too large to rescan on every boot. The pool will then contain only rows newer than the stored cursor; annotations already written to disk are unaffected, but previously loaded items will be missing from admin views and exports.

Either way, a replay never moves the stored cursor backwards, so the poller cannot be made to re-deliver rows it has already passed.

##### Assignment strategy

`live_ingestion` **cannot** be combined with `assignment_strategy: batch`, and Potato rejects that configuration at startup. BATCH only assigns items belonging to a pre-declared cohort, so a live-ingested item would sit in the pool, appear in admin views and exports, and never be offered to a single annotator.

Everything else works. Two notes:

- `category_based` only routes live rows that carry your configured `category_key`; others land in the uncategorized pool.
- `active_learning`, `llm_confidence`, `diversity_clustering` and `psychometric` fall back to random selection for items they have not scored yet, so newly ingested rows are served immediately and ranked once scores exist.

##### Per-user quota

When `max_annotations_per_user` is unset, Potato normally defaults it to the instance count — but that count is frozen at load time. With live ingestion enabled the default becomes unlimited (`-1`) instead, so later arrivals stay assignable. If you set `max_annotations_per_user` explicitly, that cap still applies to live items, and Potato logs a warning to that effect.

##### Admin API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/admin/api/data_sources/live` | Status and metrics for every live source |
| GET | `/admin/api/data_sources/<source_id>/live` | Status for one source |
| POST | `/admin/api/data_sources/<source_id>/live/poll` | Run one poll immediately |

Each reports `polls_total`, `polls_failed`, `rows_fetched`, `items_added`, `duplicates_skipped`, `consecutive_failures`, `last_error`, `last_poll_at`, `last_cursor` and `is_running`. The same block also appears per source in `GET /admin/api/data_sources`.

##### Limitations

- **An annotator who finishes everything moves on.** When a user has annotated every item currently available to them, they leave the annotation phase and are marked done; rows that arrive afterwards are not offered to them in that session, though any new or still-active annotator receives them normally. This is general Potato behaviour for every runtime source — directory watching and trace ingestion do exactly the same — and is not specific to live ingestion. It matters most when the pool is small relative to the number of annotators.
- **Single process only.** Potato holds its item pool in memory per process, so running under multiple workers (`gunicorn -w N`) gives each one its own pool, its own poller, and no cross-process deduplication.
- **The pool grows without bound.** A source producing tens of thousands of rows per hour will keep enlarging the in-memory pool that each annotation request scans. Use `stop_after_items` to cap it.
- **Automation rules run on the poll thread.** A slow rule action stretches the effective interval; `poll_interval_seconds` is a floor, not a guarantee.
- **Set an explicit `id`.** Without one, the generated id encodes the source's position in the list, so reordering `data_sources` would point a stored cursor at a different table.

**Example project**: `examples/advanced/live-database-ingestion/`

### Partial/Incremental Loading

For large datasets, enable partial loading to load data in chunks:

```yaml
partial_loading:
  enabled: true
  initial_count: 1000          # Load first K items initially
  batch_size: 500              # Items to load per increment
  auto_load_threshold: 0.8     # Auto-load when 80% annotated
```

### Caching

Remote sources are cached locally to avoid repeated downloads:

```yaml
data_cache:
  enabled: true                # Default: true
  cache_dir: ".potato_cache"   # Relative to task_dir
  ttl_seconds: 3600            # Time-to-live (default: 1 hour)
  max_size_mb: 500             # Max cache size (default: 500MB)
```

### Credential Management

Use environment variables for sensitive values:

```yaml
# In config.yaml
data_sources:
  - type: url
    url: "https://api.example.com/data"
    headers:
      Authorization: "Bearer ${API_TOKEN}"

credentials:
  env_substitution: true       # Default: true
  env_file: ".env"             # Optional: path to .env file
```

The `.env` file format:

```bash
# .env (add to .gitignore!)
API_TOKEN=your_secret_token
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

## Admin API Endpoints

### List Data Sources

```
GET /admin/api/data_sources
```

Returns status of all configured data sources.

### Load More Items

```
POST /admin/api/data_sources/{source_id}/load_more?count=500
```

Manually trigger loading more items from a source.

### Refresh Source

```
POST /admin/api/data_sources/{source_id}/refresh
```

Re-fetch data from a remote source.

### Clear Cache

```
POST /admin/api/cache/clear
```

Clear all cached remote files.

## Security Considerations

### SSRF Protection

URL sources block access to private/internal IP addresses by default:

- Localhost (127.0.0.0/8)
- Private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Link-local addresses (169.254.0.0/16)

To disable (not recommended for production):

```yaml
data_sources:
  - type: url
    url: "http://internal-server/data.json"
    block_private_ips: false  # Only for trusted internal URLs
```

### Credential Security

- **Never commit credentials** to version control
- Use environment variables (`${VAR_NAME}` syntax)
- Store `.env` files outside your repository
- Use service account JSON files with minimal permissions
- Rotate credentials regularly

## Backward Compatibility

The `data_files` configuration continues to work:

```yaml
# Traditional approach still works
data_files:
  - "data/existing.jsonl"

# Can combine with data_sources
data_sources:
  - type: url
    url: "https://example.com/additional.jsonl"
```

## Example Configurations

### Loading from Multiple Sources

```yaml
data_sources:
  # Local base data
  - type: file
    path: "data/base.jsonl"
    id: "base_data"

  # Additional data from URL
  - type: url
    url: "https://example.com/extra.jsonl"
    id: "extra_data"

  # More data from S3
  - type: s3
    bucket: "my-bucket"
    key: "annotations/batch1.jsonl"
    id: "s3_batch1"
```

### Large Dataset with Incremental Loading

```yaml
data_sources:
  - type: huggingface
    dataset: "wikipedia"
    split: "train"
    id_field: "title"
    text_field: "text"

partial_loading:
  enabled: true
  initial_count: 1000
  batch_size: 500
  auto_load_threshold: 0.9  # Load more when 90% done

data_cache:
  enabled: true
  ttl_seconds: 86400  # 24 hours
```

## Troubleshooting

### Missing Dependencies

If you see errors about missing packages, install the required dependencies for your source type:

```bash
# For Google APIs (Drive, Sheets)
pip install google-api-python-client google-auth

# For AWS S3
pip install boto3

# For Hugging Face
pip install datasets

# For Dropbox
pip install dropbox

# For SQL databases
pip install sqlalchemy psycopg2-binary  # PostgreSQL
pip install sqlalchemy pymysql          # MySQL
```

### Authentication Errors

1. **Environment variables not set**: Check that required env vars are defined
2. **Credentials file not found**: Verify the path is relative to task_dir
3. **Invalid credentials**: Check that tokens/keys are valid and not expired

### Network Errors

1. **Timeout**: Increase `timeout_seconds` for slow connections
2. **SSRF blocked**: For internal URLs, set `block_private_ips: false`
3. **SSL errors**: Ensure the remote server has valid certificates
