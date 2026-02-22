# Keyword Highlights Example

This example demonstrates how to use **admin-defined keyword highlights** to help annotators identify relevant words and phrases in the text.

## What are Keyword Highlights?

Keyword highlights are pre-defined words or phrases that are automatically highlighted in the text when an annotator views an instance. This feature helps:

- Draw attention to important keywords relevant to the annotation task
- Reduce cognitive load by pre-identifying relevant terms
- Ensure annotators don't miss key terms
- Speed up annotation by providing visual cues

## How It Works

1. **Keywords are defined in a TSV file** (`sentiment_keywords.tsv`) with three columns:
   - `Word`: The keyword or phrase (supports wildcards like `excel*`)
   - `Label`: The category for this keyword (e.g., "positive", "negative")
   - `Schema`: The annotation schema this keyword is relevant to

2. **Keywords are displayed as colored boxes** around the matching text:
   - Colors are based on the label (positive = green, negative = red)
   - Displayed with dashed borders to distinguish from user annotations
   - Hovering shows the keyword category

3. **Works alongside span annotations** - annotators can still create their own span annotations on any text, including highlighted keywords.

## Configuration

Add to your config.yaml:

```yaml
# Path to the keywords TSV file
keyword_highlights_file: sentiment_keywords.tsv

# Optional: Define colors for each label
ui:
  spans:
    span_colors:
      sentiment:
        positive: "(22, 163, 74)"    # Green
        negative: "(239, 68, 68)"    # Red
```

## TSV File Format

```
Word	Label	Schema
love	positive	sentiment
hate	negative	sentiment
excel*	positive	sentiment
```

Note: Use tabs to separate columns, not spaces.

## Wildcard Support

Keywords support `*` wildcards:
- `excel*` matches "excellent", "excels", "excel"
- `*happy` matches "unhappy", "happy"
- `disappoint*` matches "disappointing", "disappointed"

## Matching Behavior

- **Case-insensitive**: "Love" matches "love", "LOVE", "Love"
- **Word boundaries**: "love" matches "love" but not "lovely" (unless using wildcards)
- **Multiple schemas**: A single TSV file can define keywords for multiple annotation schemas

## Running the Example

From within this directory:
```bash
cd examples/ai-assisted/keyword-highlights
python ../../../potato/flask_server.py start config.yaml -p 8000
```

Then open http://localhost:8000 in your browser.

## Troubleshooting

- **Keywords not appearing**: Check that the TSV file path is correct relative to where you run the server
- **Wrong colors**: Ensure the schema and label names in `ui.spans.span_colors` match exactly (case-sensitive)
- **No matches**: Verify your keywords exist in the text (matching is case-insensitive)
