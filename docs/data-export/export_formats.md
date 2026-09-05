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

> **Note:** `output_annotation_format` is deprecated. The loader reads it as `export_annotation_format` and logs a warning, turning `json` into `jsonl` because no exporter is called `json`. It will stop being read in a later release. `potato migrate <config> --to-v2` renames it for you.

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

**Best for:** Image bounding boxes, polygons, segmentation masks

**Output Structure:**
```
<output-dir>/
└── annotations.json
```

A single file is written. **Images are not copied or symlinked** — the exported
`file_name` values point at wherever your images already live.

**annotations.json:**
```json
{
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

No `info` or `licenses` block is emitted. A few strict COCO consumers require
them; add `"info": {}` and `"licenses": []` if yours does.

**Category IDs** come from `label_id` on each label when present, so a file
imported from COCO exports with its original (often sparse) numbering intact.
Labels without one are numbered from 1 upward.

**Segmentation:** polygons export as `segmentation: [[x1, y1, ...]]`; masks
export as COCO compressed RLE with `iscrowd: 1` unless the annotation carries an
explicit `iscrowd: 0`. Landmarks are skipped with a warning — COCO keypoints are
not yet emitted.

**Image dimensions** come from `image_width`/`image_height` (or
`width`/`height`) on the data item when it declares them. A data file usually
names an image rather than measuring one, so when those fields are absent
Potato derives the size: from a mask's own RLE, which needs no file access, or
by reading the image. Declaring them is still faster and works when the image
is somewhere the exporter cannot read.

**Items nobody annotated are not exported.** Each CV exporter writes the
annotations it finds, so an item that was shown and left unmarked appears in no
image list and no annotation list. The export names how many were left out and
which. For detector training an image with no objects is a negative example, so
if you need those images, add them to the output yourself.

**Usage:**
```bash
python -m potato.export -c config.yaml -f coco -o ./coco_export/
```

**Importing COCO** is covered in
[Image Annotation Formats](../annotation-types/multimedia/image_formats.md).

!!! warning "Fixed: box and polygon export before this release"
    Every CV exporter (COCO, YOLO, Pascal VOC) read flat, absolute-pixel fields
    that the annotation UI has never written — it stores coordinates normalized
    and nested under `coordinates`. As a result **bounding boxes exported as
    `[0, 0, 0, 0]` with `area: 0`, and polygons were silently dropped**, for any
    annotation made in the browser. Masks were unaffected.

    The unit tests hand-built the flat shape, so they passed throughout. If you
    have COCO/YOLO/VOC exports produced before this release, re-export them.

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

### REFI-QDA project exchange (qdpx)

The interchange format NVivo, ATLAS.ti, MAXQDA, Quirkos and QDA Miner read and
write. Exporting one hands a Potato project to a colleague who uses any of
them, or archives it in a form that outlives this tool.

```bash
python -m potato.export -c config.yaml -f qdpx -o ./export/
```

A `.qdpx` is a ZIP holding `project.qde` (REFI-QDA XML) and one UTF-8 `.txt`
per annotated item under `sources/`. Codes carry their hierarchy, descriptions
and colours; span annotations become `PlainTextSelection` elements with a
`Coding` each; annotators become `Users`.

Two things worth knowing:

- **`endPosition` is inclusive.** REFI-QDA 1.5 §10.2 defines a selection by
  "the first and the last character", where Potato's `end` is exclusive. The
  exporter writes `end - 1`, and the importer measures both readings against
  the source text rather than assuming, because exporting tools disagree.
- **`flatten_subcodes`.** ATLAS.ti supports one level of subcode and silently
  mangles anything deeper. Passing this option re-parents every code to the top
  level and renames it `Parent > Child > Grandchild`, so you control the loss
  instead of discovering it. Potato warns when your codebook is deep enough for
  this to matter.

Two exports of an unchanged project are byte-identical: the GUIDs REFI-QDA
requires are derived from what they name, so an export can be diffed.

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

Export brush/fill mask annotations as PNG images, one per label per image.

**Best for:** Semantic segmentation

**Requires:** `Pillow` (`pip install Pillow`)

**Output Structure:**
```
<output-dir>/
├── image_001_road_mask.png
├── image_001_sky_mask.png
└── image_002_road_mask.png
```

Files are written flat as `{image-stem}_{label}_mask.png`. **Images are not
copied**, and no class-mapping file is written.

**Mask Format:**
- RGBA PNG, one file per (image, label) pair
- Mask pixels take the label's configured colour at alpha 200; everything else
  is fully transparent
- Only `type: "mask"` annotations are exported. Polygons and boxes are ignored
  by this format — use COCO for those.

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
- **likert/slider/number** → `float64`, or `string` for a scale with named labels
- **multiselect** → `list<string>` (selected labels)
- **text** → `string`

A schema that stores **several answers at once** gets one column per
sub-answer, named `<schema>.<key>`. These are the same columns the CSV writes:

| Schema | Stored | Columns |
|---|---|---|
| `multirate` | `{"Urgency": "Low", "Customer tone": "High"}` | `handling.Urgency`, `handling.Customer tone` |
| `constant_sum`, `soft_label` | `{"A": 40, "B": 60}` | `budget.A`, `budget.B` |
| `image_annotation` and other blob schemas | `{"_data": "[...]"}` | `uibox._data` (the JSON) |

A single-select stays a single column, because that is the shape that is usable
in a dataframe: `severity` holds `"Serious"` rather than spreading across a
sparse `severity.Serious`, `severity.Minor`, … as the CSV does.

Every column is present on every row, filled with null where an annotator did
not answer, so a schema only some annotators reached is still in the file.

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

`text` is derived from the offsets at export time rather than stored, so it can
never disagree with them. Offsets on a `dialogue` field index that field's
*rendered* text — `"{speaker}: {text}"`, one turn per line, which is what the
annotator saw. The exporter reconstructs that string, so the column reads the
same as for a plain text field.

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

!!! tip "Both formats round-trip"
    Potato also *reads* EAF and TextGrid, so annotations can go out to ELAN or
    Praat, be refined there, and come back in. See
    [Transcript Format Support](../annotation-types/multimedia/transcript_formats.md).

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

### Codebook (codebook)

A qualitative-coding deliverable: one CSV row per **code** in the
project [codebook](../advanced/codebook.md), including the hierarchy and
how often each code was used.

```bash
python -m potato.export --config config.yaml --format codebook -o codebook.csv
```

| Column | Meaning |
|--------|---------|
| `schema` | Annotation scheme the code belongs to |
| `annotation_type` | The scheme's type (e.g. `span`, `multiselect`) |
| `code` | Code (label) name |
| `parent` | Parent code name, if nested |
| `description` | Code description, if any |
| `color` | Code colour hex, if set |
| `n_uses` | Number of annotations that applied this code |

### Quotation Report (quotation_report)

A qualitative-coding deliverable: one CSV row per **coded span** (a
"quotation") with full provenance — the quote text, its character
offsets, the source instance, and the coder.

```bash
python -m potato.export --config config.yaml --format quotation_report -o quotations.csv

# Also append one row per memo (analytic notes alongside the quotes):
python -m potato.export --config config.yaml --format quotation_report \
  --option include_memos=true -o quotations.csv
```

| Column | Meaning |
|--------|---------|
| `schema` | Scheme the code belongs to (memos use the literal `(memo)`) |
| `code` | Code applied to the span (for a memo row: the memo's visibility) |
| `text` | The quoted span text (for a memo row: the memo body) |
| `start` / `end` | Character offsets of the span (or span-anchored memo) |
| `field` | Source field, in multi-field instances |
| `instance_id` | Instance the span came from |
| `source_doc` | Source document/file, if recorded |
| `coder` | Username of the coder |

| Option | Default | Description |
|--------|---------|-------------|
| `include_memos` | `false` | Also append one row per [memo](../advanced/memos.md): `schema="(memo)"`, `code=<visibility>`, `text=<memo body>`, offsets from the memo anchor when span-anchored. |

### ConvoKit (convokit)

Writes annotations back onto the utterances and conversations they were made
about, as [ConvoKit](../integrations/convokit.md) metadata. Requires items
imported with `potato convokit`, whose turns carry real ConvoKit utterance ids —
the mapping is a direct lookup, not a match by position or text.

```bash
# Overlay files that drop into an existing corpus (default)
python -m potato.export --config config.yaml --format convokit -o out/

# A complete corpus directory with the annotations merged in
python -m potato.export --config config.yaml --format convokit \
  --option mode=corpus -o annotated-corpus/
```

**Overlay mode** writes one `info.<field>.jsonl` per field, in exactly the shape
`corpus.load_info()` reads:

```json
{"id": "146743638.12667.12652", "value": {"alice": ["personal_attack"]}}
```

```python
from convokit import Corpus, download
corpus = Corpus(filename=download("conversations-gone-awry-corpus"))
corpus.load_info("utterance", ["potato_turn_problems"])
```

A `potato_export_manifest.json` records which object type each field targets,
since `load_info` makes the caller name it and the filename does not encode it.

**Corpus mode** writes `utterances.jsonl`, `speakers.json`, `conversations.json`,
`corpus.json`, and `index.json`. Metadata skipped on import is not re-emitted;
the fields involved are listed in `corpus.json` so the output is not mistaken for
a faithful copy of the source.

| Annotation | Lands on |
|---|---|
| Instance scheme, conversation-unit items | Conversation metadata |
| Instance scheme, utterance-unit items | Utterance metadata |
| `turn_level` scheme | Utterance metadata, keyed by `turn_id` |
| Span | Utterance metadata, split onto the utterances it covers |

A span crossing a comment boundary is split into one entry per utterance, each
with offsets relative to that utterance's own text, sharing a `span_group` so the
pieces can be recombined.

| Option | Default | Description |
|--------|---------|-------------|
| `mode` | `info` | `info` for overlay files, `corpus` for a full dump |
| `aggregate` | `none` | `none` keeps `{user_id: value}`; `majority` or `mean` adds an aggregate and moves the per-annotator dict to `<field>_raw` |
| `field_prefix` | `potato_` | Prefix for written fields. Underscore, not a dot — MongoDB rejects `.` in keys |
| `include_spans` | `true` | Map span annotations onto utterances |
| `corpus_dir` | – | Existing corpus directory, for `write_into_corpus` |
| `write_into_corpus` | `false` | Write overlays directly into `corpus_dir` |

Per-annotator data is never discarded, in any mode. Every field is accompanied by
`<field>_n_annotators`.

### Adjudication (adjudication)

The adjudicated label -- one resolved answer per item -- is what an adjudicated
workflow is for, and it is not in csv, jsonl or parquet. Those three read
per-annotator state, so an export made after adjudication carries the
disagreements and not the resolution. Use this format to get the resolution.

```bash
python -m potato.export --config config.yaml --format adjudication -o final/
```

Two files:

| File | One row per | Holds |
|---|---|---|
| `adjudicated.csv` | (item, schema) | The final value, where it came from, and the adjudicator's confidence |
| `adjudication_log.jsonl` | decision | Notes, error taxonomy, span decisions, guideline flags and time spent |

The `source` column names an annotator when the adjudicator adopted that
person's answer verbatim, and reads `adjudicator` when they answered it
themselves.

A composite scheme such as `constant_sum`, `soft_label` or
`hierarchical_multiselect` resolves to a whole allocation or path list, which
has no scalar reading. Those cells hold JSON, which round-trips. Scalar answers
stay scalar.

The exporter declines when the project has no adjudication config or has
recorded no decisions, and warns if an adjudicated item resolved no schema at
all.

`python -m potato.adjudication_export` is the older, separate CLI for the same
data. It merges unanimous agreements with adjudicated decisions into one
dataset, which this exporter does not; use it when you want that merge.

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

| Annotation Type | COCO | YOLO | Pascal VOC | CoNLL-2003 | CoNLL-U | Mask | Parquet | CSV/TSV | EAF/TextGrid | Agent Eval | ConvoKit |
|----------------|------|------|------------|------------|---------|------|---------|---------|--------------|------------|----------|
| Bounding boxes | Yes | Yes | Yes | - | - | - | Yes | Yes | - | - | - |
| Polygons | Yes | - | - | - | - | Yes | Yes | - | - | - | - |
| Keypoints | Yes | - | - | - | - | - | Yes | - | - | - | - |
| Text spans | - | - | - | Yes | Yes | - | Yes | Yes | - | - | Yes |
| Classifications | Partial | - | - | - | - | - | Yes | Yes | - | - | Yes |
| Tiered segments | - | - | - | - | - | - | Yes | - | Yes | - | - |
| Agent traces | - | - | - | - | - | - | Yes | - | - | Yes | - |
| Per-turn labels | - | - | - | - | - | - | Yes | - | - | Yes | Yes |

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
