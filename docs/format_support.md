# Extended Format Support

Potato supports annotation of various document formats beyond plain text, including PDF documents, Word files, spreadsheets, Markdown, and source code.

## Overview

The format support system consists of two main components:

1. **Format Handlers** - Extract text and coordinate mappings from documents
2. **Display Components** - Render documents in the annotation interface

## Supported Formats

| Format | Extensions | Display Type | Span Annotation |
|--------|------------|--------------|-----------------|
| PDF | .pdf | `pdf` | Yes |
| Word | .docx | `document` | Yes |
| Markdown | .md, .markdown | `document` | Yes |
| Excel/CSV | .xlsx, .csv, .tsv | `spreadsheet` | Yes (row/cell) |
| Source Code | .py, .js, .java, etc. | `code` | Yes (line-based) |

## Installation

Extended format support requires additional dependencies. Install them with:

```bash
pip install pdfplumber python-docx mammoth mistune pygments openpyxl
```

Or install specific dependencies for the formats you need:

```bash
# PDF support
pip install pdfplumber

# Word document support
pip install python-docx mammoth

# Markdown support
pip install mistune pygments

# Excel support
pip install openpyxl
```

## Configuration

### PDF Documents

Display PDF documents with text extraction and span annotation support:

```yaml
instance_display:
  fields:
    - key: document_path
      type: pdf
      label: "Document"
      span_target: true
      display_options:
        view_mode: scroll      # scroll, paginated, or side-by-side
        max_height: 700        # Maximum viewer height in pixels
        text_layer: true       # Enable text selection
        show_page_controls: true
        initial_page: 1
        zoom: auto            # auto, page-fit, page-width, or percentage
```

**View Modes:**
- `scroll` - Continuous scrolling through pages (default)
- `paginated` - One page at a time with navigation
- `side-by-side` - Multiple pages visible

### PDF Bounding Box Annotation

For image-based annotation on PDF pages (e.g., marking figures, tables, charts),
use the bounding box annotation mode:

```yaml
instance_display:
  fields:
    - key: document_path
      type: pdf
      label: "Document"
      display_options:
        annotation_mode: bounding_box  # Enable bounding box drawing
        view_mode: paginated           # Auto-set to paginated for bbox
        bbox_min_size: 10              # Minimum box size in pixels
        show_bbox_labels: true         # Show label on boxes
        show_page_controls: true
```

**Bounding Box Features:**
- Draw mode: Click and drag to create bounding boxes
- Select mode: Click on boxes to select and manage them
- Delete: Remove selected bounding boxes
- Page navigation: Navigate between pages while maintaining box data
- Label assignment: Associate labels with each bounding box

**Bounding Box Coordinates:**

Bounding boxes are stored with page information and normalized coordinates:

```json
{
  "format_coords": {
    "format": "bounding_box",
    "page": 2,
    "bbox": [0.1, 0.2, 0.3, 0.15],
    "bbox_pixels": [100, 200, 300, 150],
    "label": "FIGURE"
  }
}
```

The `bbox` field contains normalized coordinates `[x, y, width, height]` where
all values are 0-1 relative to page dimensions. The optional `bbox_pixels`
field contains the original pixel coordinates.

### Word Documents (DOCX)

Display and annotate Word documents:

```yaml
instance_display:
  fields:
    - key: document_path
      type: document
      label: "Word Document"
      span_target: true
      display_options:
        collapsible: false
        max_height: 500
        show_outline: true     # Show table of contents
        style_theme: default   # default, minimal, or print
```

### HTML/Document Bounding Box Annotation

For image-based region annotation on rendered HTML documents (e.g., marking
headers, paragraphs, images, tables), use the bounding box annotation mode:

```yaml
instance_display:
  fields:
    - key: html_content
      type: document
      label: "Document Layout"
      display_options:
        annotation_mode: bounding_box  # Enable bounding box drawing
        bbox_min_size: 10              # Minimum box size in pixels
        show_bbox_labels: true         # Show labels on boxes
        style_theme: default
```

**Bounding Box Features:**
- Draw mode: Click and drag to create bounding boxes on the document
- Select mode: Click on boxes to select and manage them
- Delete: Remove selected bounding boxes
- Label assignment: Associate labels with each bounding box

**Use Cases:**
- Document layout analysis (identifying headers, paragraphs, figures)
- Web page region annotation
- Form field detection
- UI element labeling

### Spreadsheets (Excel/CSV)

Display tabular data with row-based or cell-based annotation:

```yaml
instance_display:
  fields:
    - key: data_table
      type: spreadsheet
      label: "Data Table"
      display_options:
        annotation_mode: row   # row, cell, or range
        show_headers: true
        max_height: 400
        striped: true          # Alternating row colors
        hoverable: true        # Highlight on hover
        sortable: true         # Enable column sorting
        selectable: true       # Enable row/cell selection
        compact: false         # Compact table styling
```

**Annotation Modes:**
- `row` - Annotate entire rows (default)
- `cell` - Annotate individual cells
- `range` - Select cell ranges

### Source Code

Display syntax-highlighted code with line-level annotation:

```yaml
instance_display:
  fields:
    - key: code
      type: code
      label: "Source Code"
      span_target: true
      display_options:
        language: python       # Auto-detect if not specified
        show_line_numbers: true
        max_height: 500
        wrap_lines: false
        highlight_lines: [5, 10]  # Highlight specific lines
        theme: default         # default or dark
        copy_button: true
```

**Supported Languages:**
Python, JavaScript, TypeScript, Java, C/C++, C#, Go, Rust, Ruby, PHP,
Swift, Kotlin, Scala, R, SQL, Bash, YAML, JSON, XML, HTML, CSS, and more.

### Markdown

Display rendered Markdown with syntax highlighting:

```yaml
instance_display:
  fields:
    - key: markdown_content
      type: document
      label: "Documentation"
      span_target: true
      display_options:
        style_theme: minimal
        show_outline: true
```

## Format Handling Configuration

Configure global format handling options:

```yaml
format_handling:
  enabled: true
  default_format: auto  # Auto-detect from file extension

  pdf:
    extraction_mode: text  # text, ocr, or hybrid
    cache_extracted: true

  spreadsheet:
    annotation_mode: row
    max_rows: 1000
```

## Data Structure

### File Path References

Reference external files in your data:

```json
{
  "id": "doc_001",
  "document_path": "/path/to/document.pdf",
  "text": "Extracted text for search..."
}
```

### Embedded Table Data

Embed table data directly:

```json
{
  "id": "table_001",
  "table_data": {
    "headers": ["Column A", "Column B", "Column C"],
    "rows": [
      ["Value 1", "Value 2", "Value 3"],
      ["Value 4", "Value 5", "Value 6"]
    ]
  }
}
```

### Embedded Code

Embed source code directly:

```json
{
  "id": "code_001",
  "code": "def hello():\n    print('Hello, World!')",
  "language": "python"
}
```

## Coordinate Mapping

When span annotations are made on format documents, Potato stores both:
1. Character offsets (standard for all text)
2. Format-specific coordinates

### PDF Coordinates

```json
{
  "start": 245,
  "end": 258,
  "format_coords": {
    "format": "pdf",
    "page": 2,
    "bbox": [120.5, 340.2, 185.3, 352.8]
  }
}
```

### Spreadsheet Coordinates

```json
{
  "start": 0,
  "end": 15,
  "format_coords": {
    "format": "spreadsheet",
    "row": 5,
    "col": 2,
    "cell_ref": "B5"
  }
}
```

### Code Coordinates

```json
{
  "start": 100,
  "end": 150,
  "format_coords": {
    "format": "code",
    "line": 10,
    "column": 5
  }
}
```

## Example Projects

See the following example projects:

- `examples/image/pdf-annotation/` - PDF entity annotation
- `examples/advanced/spreadsheet-annotation/` - Tabular data quality review
- `examples/advanced/code-annotation/` - Code quality review

## Troubleshooting

### PDF not displaying

1. Ensure PDF.js can access the file (CORS for remote URLs)
2. Check browser console for JavaScript errors
3. Try enabling `text_layer: false` to test rendering

### Missing dependencies

If you see import errors, install the required packages:

```bash
pip install pdfplumber python-docx mammoth mistune pygments openpyxl
```

### Slow extraction

For large documents:
1. Use `max_pages` option for PDFs
2. Use `max_rows` option for spreadsheets
3. Consider pre-extracting content

## API Reference

### Format Handler Registry

```python
from potato.format_handlers import format_handler_registry

# Check if a file can be handled
if format_handler_registry.can_handle("document.pdf"):
    output = format_handler_registry.extract("document.pdf")

    # Access extracted content
    text = output.text
    html = output.rendered_html
    coords = output.coordinate_map
    metadata = output.metadata

# List supported formats
formats = format_handler_registry.get_supported_formats()
```

### Coordinate Mapper

```python
from potato.format_handlers import CoordinateMapper, PDFCoordinate

# Create mapper
mapper = CoordinateMapper()

# Add mappings
mapper.add_mapping(0, 100, PDFCoordinate(page=1, bbox=[10, 20, 200, 30]))

# Get coordinates for a character range
coords = mapper.get_coords_for_range(50, 75)
```

### Bounding Box Coordinates

```python
from potato.format_handlers import BoundingBoxCoordinate

# Create from normalized coordinates
bbox = BoundingBoxCoordinate(
    page=2,
    bbox=[0.1, 0.2, 0.3, 0.15],  # [x, y, width, height] normalized 0-1
    label="FIGURE"
)

# Create from pixel coordinates
bbox = BoundingBoxCoordinate.from_pixel_coords(
    page=2,
    x=100, y=200, width=300, height=150,
    page_width=1000, page_height=800,
    label="TABLE"
)

# Convert to pixel coordinates
pixels = bbox.to_pixel_coords(1000, 800)  # [x, y, width, height]
```
