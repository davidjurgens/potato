# Inline Text Editing / Post-Edit

The Text Edit schema enables annotators to directly edit displayed text while the system tracks changes. It computes a real-time diff showing insertions, deletions, and substitutions, along with edit distance metrics. Used for machine translation post-editing, grammar correction, text simplification, and paraphrase generation.

## When to Use Text Edit

- **MT post-editing**: Correct machine translation output
- **Grammar error correction**: Fix grammatical errors in text
- **Text simplification**: Rewrite complex text in simpler form
- **Paraphrase generation**: Create alternative phrasings
- **Quality estimation**: Measure how much editing is needed (via edit distance)

## Configuration

```yaml
annotation_schemes:
  - annotation_type: text_edit
    name: post_edit
    description: "Edit the machine translation to correct errors"
    source_field: "mt_output"     # Field in data containing text to edit
    show_diff: true               # Show real-time diff highlighting
    show_edit_distance: true      # Show word and character edit distance
    allow_reset: true             # Show "Reset to original" button
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `source_field` | string | `""` | Data field containing the text to edit (pre-fills the editor) |
| `show_diff` | boolean | `true` | Show word-level diff visualization |
| `show_edit_distance` | boolean | `true` | Show word and character edit distance counters |
| `allow_reset` | boolean | `true` | Show "Reset to original" button |

## Data Format

### Input Data

```json
{"id": "1", "text": "Source: Die Katze sitzt auf der Matte.", "mt_output": "The cat sit on the mat."}
```

### Annotation Output

```json
{
  "post_edit": {
    "edited_text": "The cat sits on the mat.",
    "original_text": "The cat sit on the mat.",
    "edit_distance_chars": 1,
    "edit_distance_words": 1
  }
}
```

## UI Description

1. **Source text block**: Read-only display of the original text (gray background)
2. **Editor textarea**: Pre-filled with source text, editable by the annotator
3. **Edit distance counters**: Words changed and characters changed (live update)
4. **Diff display**: Color-coded word-level diff (green = insertion, red strikethrough = deletion)
5. **Reset button**: Restores editor to original text

## Example

```bash
python potato/flask_server.py start examples/classification/text-edit/config.yaml -p 8000
```

## Related

- [Text (Free Text)](../schemas_and_templates.md) — Simple text input without diff tracking
- [Error Span](error_span.md) — Mark errors without editing the text
- [Choosing Annotation Types](../choosing_annotation_types.md)
