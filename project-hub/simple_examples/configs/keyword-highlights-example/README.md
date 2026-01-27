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

## Running the Example

```bash
cd project-hub/simple_examples/configs/keyword-highlights-example
python -m potato start config.yaml
```

Then open http://localhost:8000 in your browser.
