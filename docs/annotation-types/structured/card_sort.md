# Card Sorting / Grouping

The Card Sort schema groups items into categories by dragging them, tapping
them, or moving them with the keyboard. In **closed mode**, groups are predefined by the researcher. In **open mode**, annotators create and name their own groups. This is commonly used in information architecture research, taxonomy development, and content categorization.

## When to Use Card Sort

- **Taxonomy development**: Discover natural categories in a domain
- **Information architecture**: Test how users group content items
- **Content categorization**: Organize items into predefined topic groups
- **Concept mapping**: Group related ideas or terms

## Configuration

### Closed Mode (Predefined Groups)

```yaml
annotation_schemes:
  - annotation_type: card_sort
    name: topic_groups
    description: "Sort these items into topic groups"
    mode: closed
    groups: ["Science", "Politics", "Sports", "Entertainment"]
    items_field: "items"          # Field in data containing items to sort
    allow_empty_groups: true      # Whether empty groups are acceptable
```

### Open Mode (User-Created Groups)

```yaml
annotation_schemes:
  - annotation_type: card_sort
    name: user_categories
    description: "Create groups and sort these items"
    mode: open
    items_field: "items"
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `mode` | string | `"closed"` | `"closed"` (predefined groups) or `"open"` (user-created) |
| `groups` | list | `[]` | Group names for closed mode (required in closed mode) |
| `items_field` | string | `"items"` | Data field containing the list of items to sort |
| `allow_empty_groups` | boolean | `true` | Whether empty groups are acceptable |
| `allow_multiple` | boolean | `false` | Whether an item can appear in multiple groups |

## Data Format

### Input Data

```json
{"id": "1", "text": "Sort these headlines", "items": ["Climate study published", "Election results", "Championship game", "New movie release"]}
```

### Annotation Output

```json
{
  "topic_groups": {
    "Science": ["Climate study published"],
    "Politics": ["Election results"],
    "Sports": ["Championship game"],
    "Entertainment": ["New movie release"]
  }
}
```

## Usage

1. Items appear in the "Items to sort" panel on the left
2. Drag cards from the source panel to group containers on the right
3. Cards can be dragged between groups or back to the source
4. Group counters update automatically
5. In open mode: type a group name and click "+ Add Group" to create new groups
6. In open mode: click × on a group header to remove it (cards return to source)

### Without a mouse

Dragging is not the only way to sort, and on a phone or tablet it is not
available at all — HTML5 drag-and-drop does not work on touch.

Tap or click a card to pick it up, then tap the group to drop it in. The same
sequence works from the keyboard: Tab to a card, press Enter or Space to pick it
up, Tab to a group and press Enter to drop it. With a card picked up, a number
key sends it straight to that group — 1 is the first group on screen — and
Escape puts it back down. Focus lands on the card that just moved, so the next
Tab starts from there.

The drop zones show a dashed outline while a card is held, and each move is
announced to a screen reader ("Moved serious adverse events to Critical").

## Example

```bash
python potato/flask_server.py start examples/classification/card-sort/config.yaml -p 8000
```

## Related

- [Ranking](../comparison/ranking.md) — Order items by preference
- [Hierarchical Multiselect](hierarchical_multiselect.md) — Select from a tree taxonomy
- [Choosing Annotation Types](../choosing_annotation_types.md)
