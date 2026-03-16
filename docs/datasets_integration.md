# HuggingFace Datasets Integration

Load Potato annotations directly as HuggingFace `DatasetDict` or pandas `DataFrame` objects — no Hub round-trip required.

## Installation

```bash
pip install potato-annotation[huggingface]
# or
pip install datasets>=2.14.0
```

## Quick Start

```python
from potato import load_as_dataset, load_annotations

# Load as HuggingFace DatasetDict
ds = load_as_dataset("path/to/config.yaml")
print(ds)
# DatasetDict({
#     annotations: Dataset({ features: [...], num_rows: 150 })
#     spans: Dataset({ features: [...], num_rows: 42 })
#     items: Dataset({ features: [...], num_rows: 50 })
# })

# Access individual splits
for row in ds["annotations"]:
    print(row["instance_id"], row["user_id"])

# Load as pandas DataFrame (lighter weight)
df = load_annotations("path/to/config.yaml")
print(df.head())
```

## API Reference

### `load_as_dataset(config_path, include_spans=True, include_items=True)`

Returns a `datasets.DatasetDict` with up to three splits:

| Split | Description |
|-------|-------------|
| `annotations` | One row per (instance, user) pair with label columns |
| `spans` | One row per span annotation (start, end, label, text) |
| `items` | One row per data item with all original fields |

**Parameters:**

- `config_path` (str): Path to the Potato YAML config file
- `include_spans` (bool): Include the `spans` split (default: `True`)
- `include_items` (bool): Include the `items` split (default: `True`)

**Raises:**

- `ImportError` if `datasets` is not installed
- `FileNotFoundError` if config file does not exist
- `ValueError` if no annotations are found

### `load_annotations(config_path)`

Returns a `pandas.DataFrame` with one row per (instance, user) annotation pair.

Columns: `instance_id`, `user_id`, plus one column per annotation schema. Complex values (dicts, lists) are JSON-serialized.

**Parameters:**

- `config_path` (str): Path to the Potato YAML config file

**Raises:**

- `FileNotFoundError` if config file does not exist
- `ValueError` if no annotations are found

## Example Workflow

```python
from potato import load_as_dataset

# Load completed annotations
ds = load_as_dataset("examples/classification/single-choice/config.yaml")

# Compute inter-annotator agreement
from datasets import Features
annotations = ds["annotations"].to_pandas()
agreement = annotations.groupby("instance_id")["sentiment"].nunique()
print(f"Items with full agreement: {(agreement == 1).sum()}")

# Push to Hub for sharing
ds.push_to_hub("your-org/my-annotations", private=True)

# Or use with a training pipeline
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")
tokenized = ds["annotations"].map(
    lambda x: tokenizer(x["text"], truncation=True, padding=True),
    batched=True
)
```

## Relationship to HuggingFace Export

The `load_as_dataset()` function uses the same data extraction logic as the `--format huggingface` CLI export, but returns data in-memory instead of pushing to the Hub.

```bash
# CLI export (pushes to Hub)
python -m potato.export --config config.yaml --format huggingface --output your-org/dataset

# Python API (in-memory)
ds = load_as_dataset("config.yaml")
```

## Related Documentation

- [Export Formats](export_formats.md) — all available export formats
- [HuggingFace Export](huggingface_export.md) — push to Hub via CLI
