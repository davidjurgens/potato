# Extractive QA / Answer Span

The Extractive QA schema provides a streamlined interface for SQuAD-style question answering annotation. A question is displayed prominently above a passage, and annotators highlight the answer span directly in the text.

## When to Use Extractive QA

- **Reading comprehension datasets**: SQuAD, Natural Questions, TriviaQA-style tasks
- **Question-answer span annotation**: When the answer is a contiguous text span in the passage
- **Answer verification**: Checking whether model-predicted spans are correct
- **Unanswerable question detection**: With `allow_unanswerable: true`

## Configuration

```yaml
annotation_schemes:
  - annotation_type: extractive_qa
    name: answer_span
    description: "Highlight the answer to the question in the passage"
    question_field: "question"    # Field in data containing the question
    passage_field: "passage"      # Field in data containing the passage (or use text_key)
    allow_unanswerable: true      # Show "Unanswerable" button
    highlight_color: "#FFEB3B"    # Color for answer highlight
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `question_field` | string | `"question"` | Data field containing the question text |
| `passage_field` | string | `""` | Data field containing the passage text (falls back to `text_key`) |
| `allow_unanswerable` | boolean | `true` | Whether to show the "Unanswerable" button |
| `highlight_color` | string | `"#FFEB3B"` | CSS color for the answer highlight |

## Data Format

### Input Data

```json
{"id": "1", "question": "When was Python created?", "passage": "Python was created by Guido van Rossum and first released in 1991."}
```

### Annotation Output

```json
{
  "answer_span": {
    "answer_text": "in 1991",
    "start": 58,
    "end": 65,
    "unanswerable": false
  }
}
```

For unanswerable questions:

```json
{
  "answer_span": {
    "answer_text": "",
    "start": -1,
    "end": -1,
    "unanswerable": true
  }
}
```

## Usage

1. The question appears in a styled box at the top
2. The passage text is displayed below
3. Select text in the passage to mark the answer — it will be highlighted
4. Only one answer span at a time (new selection replaces previous)
5. Click "Clear Selection" to remove the answer
6. Click "Unanswerable" if no answer exists in the passage

## Example

```bash
python potato/flask_server.py start examples/classification/extractive-qa/config.yaml -p 8000
```

## Related

- [Span Annotation](schemas_and_templates.md) — Generic multi-label span annotation
- [Error Span](error_span.md) — Error annotation with type and severity
- [Choosing Annotation Types](choosing_annotation_types.md)
