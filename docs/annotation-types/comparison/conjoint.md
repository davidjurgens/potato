# Discrete Choice / Conjoint Analysis

The Conjoint schema presents annotators with side-by-side product/concept profiles and asks them to choose the preferred one. Each profile is defined by attribute-level combinations. This enables estimation of attribute importance through experimental design — a methodology widely used in market research, preference elicitation, and now increasingly in LLM evaluation.

## When to Use Conjoint

- **Preference elicitation**: Which AI assistant configuration do users prefer?
- **Attribute importance estimation**: Which features matter most?
- **Product/concept testing**: Compare multi-attribute alternatives
- **Trade-off analysis**: Understand how people weigh competing attributes

## Configuration

```yaml
annotation_schemes:
  - annotation_type: conjoint
    name: model_preference
    description: "Which AI assistant would you prefer?"
    profiles_per_set: 3
    attributes:
      - name: Response Length
        levels: ["Brief (1-2 sentences)", "Medium (1 paragraph)", "Detailed (multiple paragraphs)"]
      - name: Tone
        levels: ["Formal", "Conversational", "Technical"]
      - name: Includes Examples
        levels: ["Yes", "No"]
      - name: Cites Sources
        levels: ["Yes", "No"]
    show_none_option: true
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `profiles_per_set` | integer | `3` | Number of profiles shown per choice set (2-4) |
| `attributes` | list | (required*) | List of attributes with `name` and `levels` |
| `show_none_option` | boolean | `true` | Show "None of these" option |
| `profiles_field` | string | `null` | Data field with pre-specified profiles (null = use attributes to generate) |

*Either `attributes` or `profiles_field` is required.

### Where the profiles come from

With `attributes`, Potato builds the profiles by combining the levels you
declare, which is the classic design: the levels are the experimental
conditions. Each profile takes one level of every attribute at random. The
draw is seeded by annotator, item and scheme, so different annotators see
different designs and a reload shows the same cards. Profiles in one set are
distinct while the attributes allow enough combinations.

With `profiles_field`, each item carries its own profiles and Potato shows them
as they are. The rows are built from the keys the profiles use, so no
`attributes` block is needed. Every card gets a row for every key seen anywhere
in the set, which keeps the cards aligned when one profile omits a key: a
missing value shows as an em dash in the right row rather than shifting the rows
below it up.

Declaring `attributes` alongside `profiles_field` narrows the display to the
attributes you named, in the order you named them.

`profiles_per_set` is fixed for the scheme, but with `profiles_field` the data
decides how many profiles each item has. An item with fewer shows only the cards
it has, instead of padding the set with an empty option an annotator can select.
An item with more shows the first `profiles_per_set` of them and says on the page
how many it is showing. Set `profiles_per_set` to the largest set in your data.

```yaml
- annotation_type: conjoint
  name: platform
  description: "Which platform would you rather use?"
  profiles_field: profiles     # each item supplies its own
  profiles_per_set: 3
```

```json
{"id": "1", "profiles": [
  {"Hosting": "Self-hosted", "Cost": "Free"},
  {"Hosting": "Cloud", "Cost": "$20/mo"},
  {"Hosting": "Hybrid", "Cost": "$8/mo"}
]}
```

### Attributes Format

```yaml
attributes:
  - name: Speed           # Attribute name shown in profile cards
    levels: ["Fast", "Medium", "Slow"]  # Possible values
```

## Data Format

The stored answer is the number of the chosen card, or `none`:

```json
{"model_preference": "2"}
```

For a scheme built from `attributes`, the profiles that annotator saw are
recorded with the item's [presentation order](../../advanced/presentation_order.md),
under the scheme name, in card order:

```json
"instance_id_to_presentation_order": {
  "item_1": {
    "model_preference": [
      {"Response Length": "Brief (1-2 sentences)", "Tone": "Formal", "Includes Examples": "No", "Cites Sources": "Yes"},
      {"Response Length": "Detailed (multiple paragraphs)", "Tone": "Conversational", "Includes Examples": "Yes", "Cites Sources": "No"},
      {"Response Length": "Medium (1 paragraph)", "Tone": "Technical", "Includes Examples": "Yes", "Cites Sources": "Yes"}
    ]
  }
}
```

Card `"2"` is the second profile in that list. With `profiles_field`, the
profiles are the item's own data.

## UI Description

- Side-by-side profile cards (2-4 profiles)
- Each card shows attribute names and their levels in a clean table
- Radio button below each card for selection
- Selected card gets a highlight border
- Optional "None of these" option below the cards

## Example

```bash
python potato/flask_server.py start examples/classification/conjoint/config.yaml -p 8000
```

## Related

- [Pairwise Comparison](../schemas_and_templates.md) — Compare exactly two items
- [Best-Worst Scaling](../schemas_and_templates.md) — Select best and worst from a set
- [Ranking](ranking.md) — Order items by preference
- [Choosing Annotation Types](../choosing_annotation_types.md)
