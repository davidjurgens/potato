# Error Span with Typed Severity

The Error Span schema implements the MQM (Multidimensional Quality Metrics) annotation workflow. Annotators mark error spans in text, assign each an error type from a configurable taxonomy and a severity level. The system computes an overall quality score based on severity penalties.

## When to Use Error Span

- **Translation quality evaluation**: MQM annotation for MT evaluation
- **Content quality assessment**: Systematic error categorization
- **Writing quality rubrics**: Structured error identification
- **Model output analysis**: Categorize and quantify AI generation errors

## Configuration

```yaml
annotation_schemes:
  - annotation_type: error_span
    name: translation_quality
    description: "Mark errors in the translation"
    error_types:
      - name: Accuracy
        subtypes: ["Addition", "Omission", "Mistranslation"]
      - name: Fluency
        subtypes: ["Grammar", "Spelling", "Punctuation", "Register"]
      - name: Terminology
      - name: Style
    severities:
      - name: Minor
        weight: -1
      - name: Major
        weight: -5
      - name: Critical
        weight: -10
    show_score: true
    max_score: 100
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `error_types` | list | (required) | Error taxonomy with optional subtypes |
| `severities` | list | Minor(-1), Major(-5), Critical(-10) | Severity levels with penalty weights |
| `show_score` | boolean | `true` | Display running quality score |
| `max_score` | integer | `100` | Starting quality score |

### Error Types Format

```yaml
error_types:
  - name: Accuracy                    # Top-level type
    subtypes: ["Addition", "Omission"] # Optional subtypes
  - name: Terminology                 # Type without subtypes
```

### Severities Format

```yaml
severities:
  - name: Minor
    weight: -1      # Penalty subtracted from max_score
  - name: Major
    weight: -5
  - name: Critical
    weight: -10
```

## Data Format

```json
{
  "translation_quality": {
    "errors": [
      {
        "start": 15,
        "end": 28,
        "text": "wrong phrase",
        "type": "Accuracy",
        "subtype": "Mistranslation",
        "severity": "Major"
      },
      {
        "start": 45,
        "end": 52,
        "text": "grammer",
        "type": "Fluency",
        "subtype": "Spelling",
        "severity": "Minor"
      }
    ],
    "score": 94
  }
}
```

## Usage

1. Read the text displayed in the annotation area
2. Select a text span containing an error
3. A popup appears — choose the error type and severity
4. Click "Save" to add the error annotation
5. The error span is highlighted (color by severity)
6. Quality score updates automatically
7. View all errors in the list below the text
8. Delete errors by clicking the × button

## Visual Indicators

- **Minor errors**: Yellow underline
- **Major errors**: Orange underline (thicker)
- **Critical errors**: Red underline (thickest)

## Example

```bash
python potato/flask_server.py start examples/classification/error-span/config.yaml -p 8000
```

## Related

- [Span Annotation](schemas_and_templates.md) — Generic category-labeled span annotation
- [Extractive QA](extractive_qa.md) — Single answer span highlighting
- [Text Edit](text_edit.md) — Direct text editing with diff tracking
- [Choosing Annotation Types](choosing_annotation_types.md)
