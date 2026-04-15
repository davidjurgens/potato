# Export Formats

Potato supports exporting annotations to multiple industry-standard formats for use with machine learning frameworks, other annotation tools, and data pipelines.

## Overview

Potato's annotation pipeline works in two stages:

1. **Live Persistence** — During annotation, all data is automatically saved as per-user `user_state.json` files inside `output_annotation_dir`
2. **Export** — After annotation, use the Export CLI or admin API to convert annotations into analysis-ready formats (JSON, CSV, COCO, YOLO, CoNLL, etc.)

## Live Annotation Storage

### Configuration

```yaml
output_annotation_dir: annotation_output/
```

During annotation, Potato automatically persists all user state to JSON files:

```
annotation_output/
├── user1/
│   └── user_state.json
├── user2/
│   └── user_state.json
└── ...
```

Each `user_state.json` contains the complete annotation state for that user:

```json
{
    "user_id": "annotator_1",
    "instance_id_to_label_to_value": {
        "item_001": {
            "sentiment": {"labels": {"positive": true}}
        }
    },
    "instance_id_to_span_to_value": {
        "item_001": {
            "ner": [
                {"start": 0, "end": 5, "label": "PERSON", "text": "Alice"}
            ]
        }
    }
}
```

> **Note:** The older `output_annotation_format` config key is legacy and has no effect. Use `export_annotation_format` for auto-export (see below).

## Auto-Export

You can configure Potato to automatically export annotations in additional formats during annotation. Exports are written to `{output_annotation_dir}/exports/{format}/`.

```yaml
# Single format
export_annotation_format: "csv"

# Multiple formats
export_annotation_format:
  - "csv"
  - "jsonl"

# Control how often auto-export runs (default: 60 seconds)
auto_export_interval: 60
```

Supported auto-export formats include `csv`, `tsv`, `jsonl`, `parquet`, `coco`, `yolo`, `conll_2003`, and all other registered exporters. Run `python -m potato.export --list-formats` to see all available formats.

## Export CLI

The export CLI converts Potato annotations to specialized formats.

### Basic Usage

```bash
# List available export formats
python -m potato.export --list-formats

# Export to COCO format
python -m potato.export --config config.yaml --format coco --output ./export/

# Export to YOLO format
python -m potato.export --config config.yaml --format yolo --output ./export/

# Export with options
python -m potato.export --config config.yaml --format coco --output ./export/ \
    --option split_ratio=0.8 --option include_unlabeled=false
```

### Command Options

| Option | Description |
|--------|-------------|
| `--config`, `-c` | Path to Potato YAML config file |
| `--format`, `-f` | Export format (coco, yolo, pascal_voc, etc.) |
| `--output`, `-o` | Output directory (default: ./export_output) |
| `--option` | Format-specific option as key=value (repeatable) |
| `--list-formats` | List available formats and exit |
| `--verbose`, `-v` | Enable verbose logging |

## Supported Export Formats

### COCO (coco)

The Common Objects in Context format, widely used for object detection and instance segmentation.

**Best for:** Image bounding boxes, polygons, keypoints

**Output Structure:**
```
export/
├── annotations/
│   └── instances.json
└── images/
    └── (symlinked or copied images)
```

**annotations/instances.json:**
```json
{
    "info": {"description": "Potato export", "version": "1.0"},
    "licenses": [],
    "images": [
        {"id": 1, "file_name": "image_001.jpg", "width": 1920, "height": 1080}
    ],
    "annotations": [
        {
            "id": 1,
            "image_id": 1,
            "category_id": 1,
            "bbox": [100, 50, 200, 300],
            "area": 60000,
            "segmentation": [[100, 50, 300, 50, 300, 350, 100, 350]],
            "iscrowd": 0
        }
    ],
    "categories": [
        {"id": 1, "name": "person", "supercategory": "object"}
    ]
}
```

**Usage:**
```bash
python -m potato.export -c config.yaml -f coco -o ./coco_export/
```

### YOLO (yolo)

YOLO format for object detection, with one text file per image.

**Best for:** Object detection training with YOLO models

**Output Structure:**
```
export/
├── images/
│   ├── train/
│   │   └── image_001.jpg
│   └── val/
│       └── image_002.jpg
├── labels/
│   ├── train/
│   │   └── image_001.txt
│   └── val/
│       └── image_002.txt
├── data.yaml
└── classes.txt
```

**Label File Format (image_001.txt):**
```
# class_id center_x center_y width height (normalized 0-1)
0 0.5 0.5 0.25 0.35
1 0.3 0.4 0.15 0.20
```

**data.yaml:**
```yaml
train: ./images/train
val: ./images/val
nc: 3
names: ['person', 'vehicle', 'object']
```

**Usage:**
```bash
python -m potato.export -c config.yaml -f yolo -o ./yolo_export/ \
    --option split_ratio=0.8
```

**Options:**
- `split_ratio`: Train/val split ratio (default: 0.8)

### Pascal VOC (pascal_voc)

Pascal Visual Object Classes format using XML annotation files.

**Best for:** Object detection, compatible with many CV frameworks

**Output Structure:**
```
export/
├── Annotations/
│   └── image_001.xml
├── ImageSets/
│   └── Main/
│       ├── train.txt
│       └── val.txt
└── JPEGImages/
    └── image_001.jpg
```

**Annotation XML:**
```xml
<annotation>
    <folder>JPEGImages</folder>
    <filename>image_001.jpg</filename>
    <size>
        <width>1920</width>
        <height>1080</height>
        <depth>3</depth>
    </size>
    <object>
        <name>person</name>
        <bndbox>
            <xmin>100</xmin>
            <ymin>50</ymin>
            <xmax>300</xmax>
            <ymax>350</ymax>
        </bndbox>
    </object>
</annotation>
```

**Usage:**
```bash
python -m potato.export -c config.yaml -f pascal_voc -o ./voc_export/
```

### CoNLL-2003 (conll_2003)

CoNLL-2003 format for named entity recognition.

**Best for:** NER/span annotations, sequence labeling

**Output Format:**
```
-DOCSTART- -X- O O

Alice B-PERSON
went O O
to O O
Paris B-LOCATION
. O O

Bob B-PERSON
works O O
at O O
Google B-ORGANIZATION
. O O
```

**Usage:**
```bash
python -m potato.export -c config.yaml -f conll_2003 -o ./conll_export/
```

**Options:**
- `tag_scheme`: BIO, BIOES, or IOB (default: BIO)

### CoNLL-U (conll_u)

Universal Dependencies CoNLL-U format for linguistic annotation.

**Best for:** POS tagging, dependency parsing, morphological analysis

**Output Format:**
```
# sent_id = 1
# text = Alice went to Paris.
1	Alice	Alice	PROPN	NNP	Number=Sing	2	nsubj	_	SpaceAfter=No
2	went	go	VERB	VBD	Tense=Past	0	root	_	_
3	to	to	ADP	IN	_	4	case	_	_
4	Paris	Paris	PROPN	NNP	Number=Sing	2	obl	_	SpaceAfter=No
5	.	.	PUNCT	.	_	2	punct	_	_
```

**Usage:**
```bash
python -m potato.export -c config.yaml -f conll_u -o ./conllu_export/
```

### Segmentation Masks (mask)

Export polygon/segmentation annotations as binary mask images.

**Best for:** Semantic segmentation, instance segmentation

**Output Structure:**
```
export/
├── images/
│   └── image_001.jpg
├── masks/
│   └── image_001.png
└── class_mapping.json
```

**Mask Format:**
- PNG images with pixel values corresponding to class IDs
- 0 = background, 1+ = class indices

**Usage:**
```bash
python -m potato.export -c config.yaml -f mask -o ./mask_export/
```

### Parquet (parquet)

Columnar format for efficient analytics. Produces structured tables for annotations, spans, and source items.

**Best for:** Large-scale analysis with pandas, DuckDB, Spark, or any Arrow-compatible tool

**Requires:** `pyarrow >= 12.0.0` (`pip install pyarrow`)

**Output Structure:**
```
export/
├── annotations.parquet    # One row per (instance_id, user_id) pair
├── spans.parquet          # One row per span annotation (if spans exist)
└── items.parquet          # One row per original data item (optional)
```

**annotations.parquet schema:**

| Column | Type | Description |
|--------|------|-------------|
| `instance_id` | string | The annotated item's ID |
| `user_id` | string | The annotator's ID |
| *\<schema_name\>* | varies | One column per annotation schema, type depends on schema |

Schema columns are flattened by annotation type:
- **radio/select** → `string` (the selected label)
- **likert/slider/number** → `float64`
- **multiselect** → `list<string>` (selected labels)
- **text** → `string`

**spans.parquet schema:**

| Column | Type | Description |
|--------|------|-------------|
| `instance_id` | string | The annotated item's ID |
| `user_id` | string | The annotator's ID |
| `schema_name` | string | Name of the span annotation schema |
| `start` | int | Character offset where the span begins |
| `end` | int | Character offset where the span ends |
| `label` | string | The span's label |
| `text` | string | The text content of the span |

**items.parquet schema:**

| Column | Type | Description |
|--------|------|-------------|
| `item_id` | string | The item's ID |
| *\<field_name\>* | varies | One column per field in the original data (nested dicts/lists are JSON-serialized) |

**Usage:**
```bash
python -m potato.export -c config.yaml -f parquet -o ./parquet_export/
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `compression` | `snappy` | Compression codec: `snappy`, `gzip`, `zstd`, `lz4`, or `none` |
| `include_items` | `true` | Generate `items.parquet` with source data |
| `include_spans` | `true` | Generate `spans.parquet` (if span annotations exist) |
| `row_group_size` | PyArrow default | Row group size for `annotations.parquet` |

```bash
# Export with gzip compression, skip items table
python -m potato.export -c config.yaml -f parquet -o ./parquet_export/ \
    --option compression=gzip --option include_items=false
```

**Reading with pandas:**
```python
import pandas as pd

annotations = pd.read_parquet("export/annotations.parquet")
spans = pd.read_parquet("export/spans.parquet")
items = pd.read_parquet("export/items.parquet")

# Filter to a specific annotator
user_anns = annotations[annotations["user_id"] == "annotator_1"]
```

**Reading with DuckDB:**
```sql
-- Direct query without loading into memory
SELECT instance_id, sentiment, COUNT(*) as n
FROM 'export/annotations.parquet'
GROUP BY instance_id, sentiment;

-- Join annotations with source items
SELECT a.instance_id, a.sentiment, i.text
FROM 'export/annotations.parquet' a
JOIN 'export/items.parquet' i ON a.instance_id = i.item_id;
```

### CSV (csv)

Export annotations as comma-separated values with one row per annotation.

```bash
python -m potato.export --config config.yaml --format csv --output ./export/
```

### TSV (tsv)

Export annotations as tab-separated values. Same structure as CSV but with tab delimiters.

```bash
python -m potato.export --config config.yaml --format tsv --output ./export/
```

### JSONL (jsonl)

Export annotations as JSON Lines (one JSON object per line). Preserves full annotation structure.

```bash
python -m potato.export --config config.yaml --format jsonl --output ./export/
```

### EAF - ELAN Annotation Format (eaf)

Export tiered annotations as ELAN EAF XML files for use with [ELAN](https://archive.mpi.nl/tla/elan), a tool for linguistic and phonetic annotation of audio/video.

```bash
python -m potato.export --config config.yaml --format eaf --output ./export/
```

### TextGrid - Praat (textgrid)

Export tiered annotations as Praat TextGrid files for use with [Praat](https://www.fon.hum.uva.nl/praat/), a tool for phonetic analysis.

```bash
python -m potato.export --config config.yaml --format textgrid --output ./export/
```

### Agent Evaluation (agent_eval)

Export agent trace evaluation results with aggregated scores, step-level ratings, and error taxonomies.

```bash
python -m potato.export --config config.yaml --format agent_eval --output ./export/
```

### Coding Agent Evaluation (coding_eval)

Export coding agent evaluation results including process reward model (PRM) labels, code review annotations, DPO pairs, and SWE-bench compatibility scores.

```bash
python -m potato.export --config config.yaml --format coding_eval --output ./export/
```

### HuggingFace Datasets (huggingface)

Export annotations directly as a HuggingFace Dataset. See [HuggingFace Hub Export](huggingface_export.md) for detailed options.

```bash
python -m potato.export --config config.yaml --format huggingface --output ./export/
```

## Programmatic Export

Use the export registry directly in Python:

```python
from potato.export.registry import export_registry
from potato.export.cli import build_export_context

# Build context from config
context = build_export_context("path/to/config.yaml")

# Export to COCO
result = export_registry.export("coco", context, "./output/")

if result.success:
    print(f"Exported {len(result.files_written)} files")
    print(f"Stats: {result.stats}")
else:
    print(f"Errors: {result.errors}")
```

### Custom Exporters

Create custom exporters by subclassing `BaseExporter`:

```python
from potato.export.base import BaseExporter, ExportContext, ExportResult

class MyExporter(BaseExporter):
    format_name = "my_format"
    description = "My custom export format"
    file_extensions = [".myformat"]

    def can_export(self, context: ExportContext) -> tuple:
        # Check if this exporter can handle the context
        has_spans = any(ann.get("spans") for ann in context.annotations)
        if not has_spans:
            return False, "No span annotations found"
        return True, None

    def export(self, context: ExportContext, output_path: str,
               options: dict = None) -> ExportResult:
        # Perform the export
        # ...
        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=["output.myformat"],
            stats={"annotations": len(context.annotations)}
        )

# Register the exporter
from potato.export.registry import export_registry
export_registry.register(MyExporter())
```

## Format Compatibility Matrix

| Annotation Type | COCO | YOLO | Pascal VOC | CoNLL-2003 | CoNLL-U | Mask | Parquet | CSV/TSV | EAF/TextGrid | Agent Eval |
|----------------|------|------|------------|------------|---------|------|---------|---------|--------------|------------|
| Bounding boxes | Yes | Yes | Yes | - | - | - | Yes | Yes | - | - |
| Polygons | Yes | - | - | - | - | Yes | Yes | - | - | - |
| Keypoints | Yes | - | - | - | - | - | Yes | - | - | - |
| Text spans | - | - | - | Yes | Yes | - | Yes | Yes | - | - |
| Classifications | Partial | - | - | - | - | - | Yes | Yes | - | - |
| Tiered segments | - | - | - | - | - | - | Yes | - | Yes | - |
| Agent traces | - | - | - | - | - | - | Yes | - | - | Yes |

## Best Practices

1. **Choose the right format for your task:**
   - Object detection → COCO, YOLO, or Pascal VOC
   - NER/Sequence labeling → CoNLL-2003
   - Linguistic analysis → CoNLL-U
   - Segmentation → Mask or COCO with segmentation

2. **Validate exports before training:**
   - Use format-specific validation tools
   - Check that all images/items are exported
   - Verify label distributions

3. **Handle missing data:**
   - Use `--option include_unlabeled=false` to skip unannotated items
   - Check export warnings for skipped items

4. **Use consistent splits:**
   - Set `split_ratio` for reproducible train/val splits
   - Or manage splits externally and export separately

## Troubleshooting

### No Annotations Exported

1. Check that annotation output directory exists
2. Verify users have completed annotations
3. Check that the annotation type is supported by the export format

### Image Paths Not Found

1. Ensure image paths in data are accessible
2. Use absolute paths or paths relative to config file
3. Check for URL vs local file path issues

### Label Mismatch

1. Verify label names match between schema and export
2. Check for case sensitivity issues
3. Ensure category IDs are consistent

## Exporting via Admin API

All export formats are available through the admin API, allowing exports without CLI access. This is useful for remote deployments, HuggingFace Spaces, or integrating exports into automated workflows.

### List Available Formats

```bash
curl http://localhost:8000/admin/api/export/formats \
  -H "X-API-Key: YOUR_ADMIN_KEY"
```

### Run an Export

```bash
curl -X POST http://localhost:8000/admin/api/export \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_ADMIN_KEY" \
  -d '{
    "format": "coco",
    "output": "/path/to/output",
    "options": {}
  }'
```

The endpoint accepts any format returned by the formats listing endpoint. Format-specific options are passed in the `options` field.

See [HuggingFace Hub Export](huggingface_export.md) for HuggingFace-specific options and [HuggingFace Spaces](huggingface_spaces.md) for remote deployment guidance.

## Related Documentation

- [Data Format](../configuration/data_format.md) - Input data format
- [Configuration](../configuration/configuration.md) - Output configuration options
- [Image Annotation](../annotation-types/multimedia/image_annotation.md) - Bounding box and polygon annotation
- [Schemas and Templates](../annotation-types/schemas_and_templates.md) - All annotation types
