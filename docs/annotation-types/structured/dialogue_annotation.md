# Dialogue and List Annotation

Potato supports annotation of multi-item data where each instance contains a list of text elements. This is commonly used for:
- **Dialogue annotation**: Conversations with multiple turns
- **Pairwise comparison**: Comparing two or more text variants
- **Multi-document tasks**: Rating or labeling multiple related texts

## Data Format

### Input Data

Multi-item data is represented as a list of strings in the `text` field:

```json
{"id": "conv_001", "text": ["Tom: Isn't this awesome?!", "Sam: Yes! I like you!", "Tom: Great!", "Sam: Awesome! Let's party!"]}
{"id": "conv_002", "text": ["Tom: I am so sorry for that", "Sam: No worries", "Tom: Thanks for your understanding!"]}
```

Each string in the list represents one item (e.g., a dialogue turn, a document variant, etc.).

## Configuration

### Basic Setup

```yaml
# Data configuration
data_files:
  - data/dialogues.json

item_properties:
  id_key: id
  text_key: text

# Configure list display
list_as_text:
  text_list_prefix_type: none  # No prefix since speaker names are in text
  alternating_shading: true    # Shade every other turn for readability

# Annotation schemes
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "What is the overall sentiment of this conversation?"
    labels:
      - positive
      - neutral
      - negative
```

### Display Options

The `list_as_text` configuration controls how list items are displayed:

```yaml
list_as_text:
  text_list_prefix_type: alphabet  # Prefix type for items
  horizontal: false                # Layout direction
  alternating_shading: false       # Shade alternate turns
```

#### Prefix Types

| Option | Example | Best For |
|--------|---------|----------|
| `alphabet` | A. B. C. | Pairwise comparisons, options |
| `number` | 1. 2. 3. | Sequential turns, ordered lists |
| `bullet` | • • • | Unordered items |
| `none` | (no prefix) | Dialogue with speaker names in text |

#### Layout Options

| Option | Description |
|--------|-------------|
| `horizontal: false` | Vertical layout (default) - items stacked vertically |
| `horizontal: true` | Side-by-side layout - for pairwise comparison |
| `alternating_shading: true` | Shades every other turn for dialogue readability |

### Dialogue with Alternating Shading

For conversations, use `alternating_shading` to visually distinguish turns:

```yaml
list_as_text:
  text_list_prefix_type: none
  alternating_shading: true
```

This displays dialogue turns with alternating background colors and left borders, making it easy to follow the conversation flow.

### Pairwise Comparison Layout

For comparing two or more text variants, use horizontal layout:

```yaml
list_as_text:
  text_list_prefix_type: alphabet
  horizontal: true
```

This displays options side-by-side in styled containers, each with a distinct left border color.

## Example Configurations

### Dialogue Annotation

```yaml
annotation_task_name: Dialogue Analysis

data_files:
  - data/dialogues.json

item_properties:
  id_key: id
  text_key: text

list_as_text:
  text_list_prefix_type: none
  alternating_shading: true

annotation_schemes:
  - annotation_type: span
    name: certainty
    description: Highlight phrases that express certainty or uncertainty
    labels:
      - certain
      - uncertain
    sequential_key_binding: true

  - annotation_type: radio
    name: sentiment
    description: What kind of sentiment does the conversation hold?
    labels:
      - positive
      - neutral
      - negative
    sequential_key_binding: true
```

### Pairwise Text Comparison

```yaml
annotation_task_name: Text Comparison

data_files:
  - data/pairs.json

item_properties:
  id_key: id
  text_key: text

list_as_text:
  text_list_prefix_type: alphabet
  horizontal: true

annotation_schemes:
  - annotation_type: radio
    name: preference
    description: Which text is better?
    labels:
      - A is better
      - B is better
      - Equal
```

## Working Example

A complete working example is available in the [potato-showcase](https://github.com/davidjurgens/potato-showcase) repository under `dialogue_analysis/`:

```bash
# Clone the showcase repo for paper-specific examples
git clone https://github.com/davidjurgens/potato-showcase.git
cd potato-showcase/dialogue_analysis/configs
python ../../../potato/flask_server.py start dialogue-analysis.yaml -p 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

**Sample data format** (`data_files/dialogue-example.json`):
```json
{"id":"1","text":["Tom: Isn't this awesome?!", "Sam: Yes! I like you!", "Tom: great!", "Sam: Awesome! Let's party!"]}
{"id":"2","text":["Tom: I am so sorry for that", "Sam: No worries", "Tom: thanks for your understanding!"]}
```

## Tips

1. **Speaker Names**: Include speaker names in the text (e.g., "Tom: Hello") when using `text_list_prefix_type: none` for dialogue.

2. **Span Annotation**: When using span annotation with dialogue data, annotators can highlight text within any of the displayed turns.

3. **Prefix Choice**:
   - Use `none` for dialogue where speaker names are embedded in text
   - Use `number` when sequence order matters
   - Use `alphabet` for pairwise/comparison tasks

4. **Readability**: Enable `alternating_shading` for long dialogues to help annotators track which turn they're reading.

5. **Comparison Tasks**: Use `horizontal: true` with `alphabet` prefixes for side-by-side comparison of two text variants.
