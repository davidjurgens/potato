# Export Formats

Potato supports exporting annotations to multiple industry-standard formats for use with machine learning frameworks, other annotation tools, and data pipelines.

## Overview

Potato provides two levels of export:

1. **Native Export** - Annotations are automatically saved in JSON/JSONL/CSV/TSV format as configured
2. **Format Conversion** - Export CLI converts annotations to specialized formats (COCO, YOLO, CoNLL, etc.)

## Native Output Formats

### Configuration

Set the output format in your config file:

```yaml
output_annotation_dir: annotation_output/
output_annotation_format: json  # json, jsonl, csv, or tsv
```

### JSON Format

Each user's annotations are saved as a single JSON file with structure:

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

### JSONL Format

One JSON object per line, suitable for streaming processing:

```jsonl
{"instance_id": "item_001", "sentiment": "positive", "spans": [...]}
{"instance_id": "item_002", "sentiment": "negative", "spans": [...]}
```

### CSV/TSV Format

Tabular format with columns for each annotation field:

```csv
instance_id,sentiment,confidence
item_001,positive,0.95
item_002,negative,0.87
```

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

| Annotation Type | COCO | YOLO | Pascal VOC | CoNLL-2003 | CoNLL-U | Mask |
|----------------|------|------|------------|------------|---------|------|
| Bounding boxes | Yes | Yes | Yes | - | - | - |
| Polygons | Yes | - | - | - | - | Yes |
| Keypoints | Yes | - | - | - | - | - |
| Text spans | - | - | - | Yes | Yes | - |
| Classifications | Partial | - | - | - | - | - |

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

## Related Documentation

- [Data Format](data_format.md) - Input data format
- [Configuration](configuration.md) - Output configuration options
- [Image Annotation](image_annotation.md) - Bounding box and polygon annotation
- [Schemas and Templates](schemas_and_templates.md) - All annotation types
