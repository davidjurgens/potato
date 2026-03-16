# HuggingFace Hub Export

Push your annotations directly to the [HuggingFace Hub](https://huggingface.co/docs/hub/) as a Dataset, making them instantly available for download via `datasets.load_dataset()`.

## Installation

```bash
pip install potato-annotation[huggingface]

# Or install dependencies directly
pip install huggingface_hub>=0.20.0 datasets>=2.14.0
```

## Quick Start

```bash
# Export annotations to a HuggingFace Hub dataset
python -m potato.export \
    --config config.yaml \
    --format huggingface \
    --output your-org/my-annotations \
    --option token=hf_xxx
```

## CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `token` | HuggingFace API token (or set `HF_TOKEN` env var) | `$HF_TOKEN` |
| `private` | Create a private dataset | `false` |
| `commit_message` | Custom commit message | `"Upload annotations from Potato"` |
| `include_items` | Include original item data as a separate split | `true` |
| `include_spans` | Include span annotations as a separate split | `true` |

Pass options with `--option key=value`:

```bash
python -m potato.export \
    --config config.yaml \
    --format huggingface \
    --output your-org/sentiment-annotations \
    --option token=hf_your_token \
    --option private=true \
    --option include_items=false
```

## Dataset Structure

The exported dataset contains up to three splits:

### `annotations` Split

One row per (instance_id, user_id) pair with flattened annotation columns:

| Column | Type | Description |
|--------|------|-------------|
| `instance_id` | string | Item identifier |
| `user_id` | string | Annotator identifier |
| `<schema_name>` | string | JSON-serialized annotation value per schema |

### `spans` Split (optional)

One row per span annotation:

| Column | Type | Description |
|--------|------|-------------|
| `instance_id` | string | Item identifier |
| `user_id` | string | Annotator identifier |
| `schema_name` | string | Schema that produced the span |
| `start` | int | Character start offset |
| `end` | int | Character end offset |
| `label` | string | Span label |
| `text` | string | Annotated text |

### `items` Split (optional)

One row per original data item:

| Column | Type | Description |
|--------|------|-------------|
| `item_id` | string | Item identifier |
| `<field>` | varies | Original data fields (dicts/lists serialized as JSON) |

## Loading the Dataset

```python
from datasets import load_dataset

# Load all splits
ds = load_dataset("your-org/my-annotations")
print(ds)
# DatasetDict({
#     annotations: Dataset({features: ['instance_id', 'user_id', 'sentiment'], num_rows: 150})
#     spans: Dataset({features: ['instance_id', 'user_id', 'schema_name', ...], num_rows: 42})
#     items: Dataset({features: ['item_id', 'text'], num_rows: 50})
# })

# Access annotations
for row in ds["annotations"]:
    print(row["instance_id"], row["sentiment"])

# Load private dataset
ds = load_dataset("your-org/my-annotations", token="hf_xxx")
```

## Dataset Card

A `DatasetCard` is automatically generated and pushed alongside the data, including:

- Annotation schema descriptions and labels
- Number of annotation records
- Usage code example
- Link back to the Potato project

## Authentication

### API Token

Get your token from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). You need a token with **write** access.

Set it via:

1. CLI option: `--option token=hf_xxx`
2. Environment variable: `export HF_TOKEN=hf_xxx`
3. HuggingFace CLI login: `huggingface-cli login`

### Organization Datasets

To push to an organization, use `org-name/dataset-name` as the output path:

```bash
python -m potato.export \
    --config config.yaml \
    --format huggingface \
    --output my-research-lab/sentiment-v2
```

## Troubleshooting

**"huggingface_hub and datasets are required"**
Install the dependencies: `pip install huggingface_hub>=0.20.0 datasets>=2.14.0`

**"output_path must be a HuggingFace repo ID"**
The `--output` parameter must be in `org/name` or `username/name` format.

**Authentication errors**
Verify your token has write permissions and hasn't expired.

**Large datasets timing out**
For very large annotation sets, consider exporting to Parquet first and uploading manually.

## Exporting from the Admin API

If you don't have CLI access (e.g., running on HuggingFace Spaces or a remote server), you can trigger exports via the admin API endpoint.

### Prerequisites

- An admin API key (printed to the console on server startup, or set via `admin_api_key` in your config)
- The `HF_TOKEN` environment variable or pass the token in the request options

### Triggering an Export

```bash
curl -X POST http://localhost:8000/admin/api/export \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_ADMIN_KEY" \
  -d '{
    "format": "huggingface",
    "output": "your-org/my-annotations",
    "options": {"token": "hf_xxx", "private": "true"}
  }'
```

The response includes the export result:

```json
{
  "success": true,
  "format": "huggingface",
  "files_written": ["your-org/my-annotations"],
  "stats": {"num_annotations": 150, "num_items": 50},
  "warnings": [],
  "errors": []
}
```

### Listing Available Formats

```bash
curl http://localhost:8000/admin/api/export/formats \
  -H "X-API-Key: YOUR_ADMIN_KEY"
```

### For HuggingFace Spaces Users

When running on Spaces, you won't have terminal access. Use the admin API instead:

1. Set `HF_TOKEN` as a Space secret in your repository settings
2. Note the admin API key from the Space logs (or configure one in your YAML)
3. Use `curl` or any HTTP client to call the export endpoint
4. Pass the format as `"huggingface"` and your repo ID as the output

## Related Documentation

- [Export Formats](export_formats.md) - Other export formats (COCO, YOLO, Parquet, etc.)
- [HuggingFace Spaces](huggingface_spaces.md) - Deploy Potato on HuggingFace Spaces
