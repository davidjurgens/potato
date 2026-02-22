# Annotation Filtering

This guide covers how to filter data based on prior annotation decisions. This is useful for multi-phase annotation workflows where the output of one task feeds into another.

## Common Use Cases

1. **Triage -> Full Annotation**: Filter items that were "accepted" in a rapid triage phase
2. **Quality Control**: Filter items that passed quality checks
3. **Expert Review**: Filter items flagged for expert review
4. **Multi-stage Annotation**: Chain annotation tasks together

## Option 1: CLI Tool

The `filter_by_annotation` CLI tool filters data files based on prior annotations.

### Basic Usage

```bash
# Filter for accepted items from triage
python -m potato.filter_by_annotation \
    --annotations annotation_output/ \
    --data data/items.json \
    --schema data_quality \
    --value accept \
    --output accepted_items.json
```

### CLI Options

| Option | Description |
|--------|-------------|
| `--annotations`, `-a` | Path to annotation_output directory (required) |
| `--data`, `-d` | Path to original data file (JSON or JSONL) |
| `--schema`, `-s` | Name of the annotation schema to filter by (required) |
| `--value`, `-v` | Value(s) to filter for (e.g., `accept` or `accept maybe`) |
| `--output`, `-o` | Output file path for filtered data |
| `--id-key` | Key in data items containing the instance ID (default: `id`) |
| `--invert` | Invert filter: return items that DON'T match |
| `--format` | Output format: `json` or `jsonl` (default: `json`) |
| `--summary` | Show annotation summary instead of filtering |
| `--verbose`, `-V` | Enable verbose logging |

### Examples

**Filter for multiple values:**
```bash
python -m potato.filter_by_annotation \
    --annotations annotation_output/ \
    --data data/items.json \
    --schema quality \
    --value good acceptable \
    --output filtered.json
```

**Invert filter (get rejected items):**
```bash
python -m potato.filter_by_annotation \
    --annotations annotation_output/ \
    --data data/items.json \
    --schema triage \
    --value accept \
    --invert \
    --output rejected_items.json
```

**Show annotation summary:**
```bash
python -m potato.filter_by_annotation \
    --annotations annotation_output/ \
    --schema data_quality \
    --summary
```

Output:
```
Annotation summary for schema 'data_quality':
----------------------------------------
  accept: 150 (60.0%)
  reject: 75 (30.0%)
  skip: 25 (10.0%)
----------------------------------------
  Total: 250
```

## Option 2: Config-Based Filtering

Filter data automatically during server startup using configuration.

### Configuration

In your config YAML, use a dict format for data_files with `filter_by_prior_annotation`:

```yaml
data_files:
  - path: data/items.json
    filter_by_prior_annotation:
      annotation_dir: ../triage-task/annotation_output/
      schema: data_quality
      value: accept
```

### Configuration Options

| Option | Type | Description |
|--------|------|-------------|
| `annotation_dir` | string | Path to the annotation_output directory from the prior task |
| `schema` | string | Name of the annotation schema to filter by |
| `value` | string or list | Value(s) to filter for |
| `invert` | boolean | If true, return items that DON'T match (default: false) |

### Examples

**Filter for single value:**
```yaml
data_files:
  - path: data/all_items.json
    filter_by_prior_annotation:
      annotation_dir: ../triage/annotation_output/
      schema: triage
      value: accept
```

**Filter for multiple values:**
```yaml
data_files:
  - path: data/all_items.json
    filter_by_prior_annotation:
      annotation_dir: ../quality-check/annotation_output/
      schema: quality
      value:
        - good
        - acceptable
```

**Invert filter (exclude rejected items):**
```yaml
data_files:
  - path: data/all_items.json
    filter_by_prior_annotation:
      annotation_dir: ../review/annotation_output/
      schema: review_status
      value: rejected
      invert: true
```

## Workflow Example: Triage -> Full Annotation

### Step 1: Create Triage Task

```yaml
# triage-task/config.yaml
annotation_task_name: "Data Quality Triage"
task_dir: .

data_files:
  - data/raw_items.json

item_properties:
  id_key: id
  text_key: text

annotation_schemes:
  - annotation_type: triage
    name: data_quality
    description: Is this data suitable for annotation?
    auto_advance: true

output_annotation_dir: annotation_output
```

### Step 2: Run Triage

```bash
python potato/flask_server.py start triage-task/config.yaml -p 8000
```

Annotators rapidly accept/reject/skip items.

### Step 3: Create Full Annotation Task

**Option A: Using CLI to create filtered data file**

```bash
# Filter accepted items
python -m potato.filter_by_annotation \
    --annotations triage-task/annotation_output/ \
    --data triage-task/data/raw_items.json \
    --schema data_quality \
    --value accept \
    --output full-annotation-task/data/accepted_items.json
```

```yaml
# full-annotation-task/config.yaml
annotation_task_name: "Full Annotation"
task_dir: .

data_files:
  - data/accepted_items.json  # Pre-filtered data

annotation_schemes:
  - annotation_type: span
    name: entities
    description: Annotate named entities
    labels:
      - PERSON
      - ORGANIZATION
      - LOCATION

output_annotation_dir: annotation_output
```

**Option B: Using config-based filtering**

```yaml
# full-annotation-task/config.yaml
annotation_task_name: "Full Annotation"
task_dir: .

data_files:
  - path: ../triage-task/data/raw_items.json
    filter_by_prior_annotation:
      annotation_dir: ../triage-task/annotation_output/
      schema: data_quality
      value: accept

annotation_schemes:
  - annotation_type: span
    name: entities
    description: Annotate named entities
    labels:
      - PERSON
      - ORGANIZATION
      - LOCATION

output_annotation_dir: annotation_output
```

## Output Format

The filtered output preserves all original fields from the input data:

**Input (`raw_items.json`):**
```json
[
  {"id": "item_001", "text": "Hello world", "category": "greeting"},
  {"id": "item_002", "text": "Bad data", "category": "noise"},
  {"id": "item_003", "text": "Good data", "category": "content"}
]
```

**Triage annotations:**
- item_001: accept
- item_002: reject
- item_003: accept

**Output (`accepted_items.json`):**
```json
[
  {"id": "item_001", "text": "Hello world", "category": "greeting"},
  {"id": "item_003", "text": "Good data", "category": "content"}
]
```

All original fields (`id`, `text`, `category`) are preserved, making the filtered output immediately usable as input to another Potato task.

## Python API

For programmatic use:

```python
from potato.filter_by_annotation import (
    filter_items_by_annotation,
    get_annotation_summary,
    load_annotations_from_dir,
)

# Filter items
filtered = filter_items_by_annotation(
    annotation_dir="annotation_output/",
    data_file="data/items.json",
    schema_name="triage",
    filter_value="accept",
    id_key="id"
)

# Get summary
summary = get_annotation_summary("annotation_output/", "triage")
print(summary)  # {'accept': 100, 'reject': 50, 'skip': 25}

# Load raw annotations
annotations = load_annotations_from_dir("annotation_output/")
# Returns: {'item_001': {'triage': {'name': 'accept', 'value': 'accept'}}, ...}
```

## Troubleshooting

### No items after filtering

Check the annotation summary to see what values exist:
```bash
python -m potato.filter_by_annotation \
    --annotations annotation_output/ \
    --schema YOUR_SCHEMA \
    --summary
```

### Items not matching

Ensure the schema name matches exactly (case-sensitive) and the annotation_dir points to the correct location.

### ID mismatch

Verify the `id_key` matches between your data file and annotations. Both should use the same field name (default: `id`).
