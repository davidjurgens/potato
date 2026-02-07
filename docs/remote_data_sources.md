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

**Dependencies**: `pip install sqlalchemy psycopg2-binary` (PostgreSQL) or `pip install sqlalchemy pymysql` (MySQL)

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
