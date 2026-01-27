# Preview CLI

The Potato Preview CLI allows you to validate annotation configurations and preview how schemas will render without running the full server. This is useful for rapid prototyping, debugging, and CI/CD validation.

## Overview

The preview CLI provides:

- **Configuration validation**: Check for errors and warnings before deployment
- **Schema preview**: See how annotation schemas will render as HTML
- **Keybinding conflict detection**: Identify conflicting keyboard shortcuts
- **Multiple output formats**: Summary, HTML, JSON, or layout-only snippets

## Installation

The preview CLI is included with Potato. No additional installation required.

## Basic Usage

```bash
# Default summary output
python -m potato.preview_cli config.yaml

# Or using the module directly
python -m potato.preview_cli path/to/your/config.yaml
```

## Output Formats

### Summary (Default)

Displays a text summary of the configuration:

```bash
python -m potato.preview_cli config.yaml
```

Output:
```
============================================================
ANNOTATION TASK PREVIEW
============================================================
Task Name: Sentiment Annotation
Task Directory: ./my_task

Validation: PASSED

ANNOTATION SCHEMAS (2 total):
----------------------------------------
  [radio] sentiment
          Select the sentiment of the text...
          Labels: 3
          Keybindings: 3

  [multiselect] topics
          Select all relevant topics...
          Labels: 5
          Keybindings: 0

============================================================
```

### HTML Output

Generate a full HTML page preview:

```bash
python -m potato.preview_cli config.yaml --format html > preview.html
```

Open `preview.html` in a browser to see how your annotation schemas will look.

### JSON Output

Generate structured JSON output for programmatic processing:

```bash
python -m potato.preview_cli config.yaml --format json
```

Output:
```json
{
  "task_name": "Sentiment Annotation",
  "validation_issues": [],
  "schema_count": 2,
  "schemas": [
    {
      "name": "sentiment",
      "type": "radio",
      "description": "Select the sentiment",
      "labels": ["Positive", "Negative", "Neutral"],
      "keybindings": [
        {"key": "1", "action": "Positive"},
        {"key": "2", "action": "Negative"},
        {"key": "3", "action": "Neutral"}
      ],
      "error": null
    }
  ]
}
```

### Layout-Only HTML

Generate just the annotation schema HTML snippet (what goes inside `{{ TASK_LAYOUT }}`):

```bash
python -m potato.preview_cli config.yaml --layout-only > task_layout.html
```

This is useful for:
- Embedding in custom templates
- Testing schema rendering in isolation
- Prototyping custom layouts

Output:
```html
<div class="annotation_schema">
  <div class="schema_container" data-annotation-id="0">
    <!-- Schema HTML here -->
  </div>
</div>
```

## Command Line Options

| Option | Short | Description |
|--------|-------|-------------|
| `--format` | `-f` | Output format: `summary`, `html`, or `json` |
| `--layout-only` | `-l` | Output only task layout HTML snippet |
| `--verbose` | `-v` | Enable verbose/debug output |

## Configuration Validation

The preview CLI validates your configuration and reports issues:

### Errors (Blocking)

```
ERROR: Missing required field 'annotation_task_name'
ERROR: Must have either 'data_files' or 'data_directory'
ERROR: Both top-level and phase-level annotation_schemes found
```

### Warnings (Non-Blocking)

```
WARNING: No annotation schemes found in configuration
WARNING: Key '1' used by both 'schema1:Label1' and 'schema2:Label2'
```

### Exit Codes

- `0`: Configuration is valid
- `1`: Configuration has errors

Use exit codes in CI/CD pipelines:

```bash
python -m potato.preview_cli config.yaml || echo "Config validation failed"
```

## Keybinding Conflict Detection

The CLI automatically detects keyboard shortcut conflicts across schemas:

```bash
python -m potato.preview_cli config.yaml
```

Output includes:
```
KEYBINDING CONFLICTS:
  WARNING: Key '1' used by both 'sentiment:Positive' and 'quality:High'
  WARNING: Key '2' used by both 'sentiment:Negative' and 'quality:Low'
```

## Use Cases

### Rapid Prototyping

Quickly iterate on schema designs:

```bash
# Edit config
vim config.yaml

# Preview immediately
python -m potato.preview_cli config.yaml --format html > preview.html && open preview.html
```

### CI/CD Integration

Validate configurations in your deployment pipeline:

```yaml
# .github/workflows/validate.yml
- name: Validate Potato Config
  run: python -m potato.preview_cli configs/production.yaml
```

### Template Development

Generate layout snippets for custom template integration:

```bash
python -m potato.preview_cli config.yaml --layout-only > templates/includes/schemas.html
```

### Debugging

Get detailed information about schema generation:

```bash
python -m potato.preview_cli config.yaml --verbose --format json
```

## API Reference

The preview CLI functions can also be used programmatically:

```python
from potato.preview_cli import (
    load_config,
    validate_config,
    get_annotation_schemes,
    detect_keybinding_conflicts,
    generate_preview_html,
    generate_preview_json,
    generate_preview_summary,
    generate_layout_html,
)

# Load and validate
config = load_config("config.yaml")
issues = validate_config(config)

# Extract schemes
schemes = get_annotation_schemes(config)

# Check for conflicts
conflicts = detect_keybinding_conflicts(schemes)

# Generate outputs
html = generate_preview_html(schemes)
layout = generate_layout_html(schemes)
json_output = generate_preview_json(config, schemes, issues)
summary = generate_preview_summary(config, schemes, issues, conflicts)
```

### Functions

| Function | Description |
|----------|-------------|
| `load_config(path)` | Load and parse YAML configuration |
| `validate_config(config)` | Validate configuration, return issues list |
| `get_annotation_schemes(config)` | Extract all annotation schemes |
| `detect_keybinding_conflicts(schemes)` | Find keyboard shortcut conflicts |
| `generate_preview_html(schemes)` | Generate full HTML preview page |
| `generate_layout_html(schemes)` | Generate layout-only HTML snippet |
| `generate_preview_json(config, schemes, issues)` | Generate JSON output |
| `generate_preview_summary(config, schemes, issues, conflicts)` | Generate text summary |

## Troubleshooting

### "Module not found" Error

Ensure Potato is installed:

```bash
pip install -e .
# or
pip install potato-annotation
```

### Schema Rendering Errors

If a schema fails to render, the output will include an error message:

```html
<!-- Error generating my_schema: KeyError 'labels' -->
```

Check that your schema configuration is complete.

### Missing annotation_id

The preview CLI automatically sets `annotation_id` on schemas before rendering. If you're using the API directly, ensure you set this:

```python
for idx, scheme in enumerate(schemes):
    scheme["annotation_id"] = idx
```

## Related Documentation

- [Configuration](configuration.md) - Full configuration reference
- [Schemas and Templates](schemas_and_templates.md) - Annotation schema types
- [UI Configuration](ui_configuration.md) - Customizing the interface
