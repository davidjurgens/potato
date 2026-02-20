# Coreference Chain Annotation

Coreference annotation allows annotators to group text spans that refer to the same entity. This is essential for tasks like entity resolution, pronoun resolution, and discourse analysis.

## Overview

A coreference chain is a collection of mentions (text spans) that all refer to the same real-world entity. For example, in the sentence:

> "**Marie Curie** was a physicist. **She** won the Nobel Prize. **The scientist** changed **her** field forever."

The spans "Marie Curie", "She", "The scientist", and "her" all refer to the same person and would form a single coreference chain.

## Quick Start

Coreference annotation requires two schema components:
1. A **span schema** for creating mentions
2. A **coreference schema** for grouping mentions into chains

```yaml
annotation_schemes:
  # First: Define span schema for creating mentions
  - annotation_type: span
    name: mentions
    description: Highlight all entity mentions
    labels:
      - name: MENTION
        tooltip: "Any reference to an entity"
    sequential_key_binding: true

  # Second: Define coreference schema for chaining mentions
  - annotation_type: coreference
    name: coref_chains
    description: Group mentions that refer to the same entity
    span_schema: mentions
    allow_singletons: true
```

## Configuration Options

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `annotation_type` | string | Must be `"coreference"` |
| `name` | string | Unique identifier for this schema |
| `description` | string | Instructions displayed to annotators |
| `span_schema` | string | Name of the span schema providing mentions |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `entity_types` | list | `[]` | List of entity type categories |
| `allow_singletons` | boolean | `true` | Allow chains with only one mention |
| `visual_display.highlight_mode` | string | `"background"` | Visual style: "background", "bracket", or "underline" |

## Example Configurations

### Basic Coreference

```yaml
annotation_schemes:
  - annotation_type: span
    name: mentions
    description: Highlight entity mentions
    labels:
      - name: MENTION

  - annotation_type: coreference
    name: entity_chains
    description: Link mentions that refer to the same entity
    span_schema: mentions
```

### With Entity Types

Classify chains by entity type (person, organization, location, etc.):

```yaml
annotation_schemes:
  - annotation_type: span
    name: ner
    description: Mark named entities
    labels:
      - name: ENTITY
        tooltip: "Any named entity mention"

  - annotation_type: coreference
    name: coref
    description: Create coreference chains
    span_schema: ner
    entity_types:
      - name: PERSON
        color: "#6E56CF"
      - name: ORGANIZATION
        color: "#22C55E"
      - name: LOCATION
        color: "#3B82F6"
      - name: OTHER
        color: "#F59E0B"
```

### Without Singletons

For tasks where every mention must be linked to at least one other mention:

```yaml
annotation_schemes:
  - annotation_type: span
    name: mentions
    description: Highlight co-referring mentions
    labels:
      - name: MENTION

  - annotation_type: coreference
    name: strict_coref
    description: All mentions must be part of a chain with at least 2 mentions
    span_schema: mentions
    allow_singletons: false
```

### Custom Visual Display

```yaml
annotation_schemes:
  - annotation_type: coreference
    name: coref
    description: Link coreference chains
    span_schema: mentions
    visual_display:
      highlight_mode: "underline"  # Options: background, bracket, underline
```

## User Interface

### Creating Chains

1. **Create mentions**: First, use the span annotation tool to highlight all entity mentions in the text
2. **Select mentions**: Click on the highlighted spans you want to chain together
3. **Create chain**: Click "New Chain" to group the selected mentions

### Managing Chains

- **Add to Chain**: Select additional mentions and click "Add to Chain" to add them to the active chain
- **Merge Chains**: Select multiple chains and click "Merge Chains" to combine them
- **Remove Mention**: Select a mention and click "Remove Mention" to remove it from its chain

### Chain Panel

The chain panel displays all coreference chains with:
- Chain ID and color indicator
- List of mentions in each chain
- Entity type (if configured)
- Quick actions for editing

## Visual Indicators

### Highlight Modes

| Mode | Description |
|------|-------------|
| `background` | Highlights chains with colored backgrounds |
| `bracket` | Shows chain membership with bracket notation |
| `underline` | Underlines mentions with chain color |

### Color Coding

Each chain is automatically assigned a distinct color from the palette. Mentions in the same chain share the same color, making it easy to visually identify chain membership.

Default color palette:
- Purple (#6E56CF)
- Red (#EF4444)
- Green (#22C55E)
- Blue (#3B82F6)
- Amber (#F59E0B)
- And 10 more distinct colors

## Output Format

Coreference annotations are saved as span links:

```json
{
  "span_links": [
    {
      "schema": "coref_chains",
      "link_type": "coreference",
      "span_ids": ["mentions_0_5_MENTION", "mentions_34_37_MENTION", "mentions_72_85_MENTION"],
      "entity_type": "PERSON"
    },
    {
      "schema": "coref_chains",
      "link_type": "coreference",
      "span_ids": ["mentions_15_23_MENTION", "mentions_95_97_MENTION"],
      "entity_type": "ORGANIZATION"
    }
  ]
}
```

Each chain contains:
- `schema`: The coreference schema name
- `link_type`: Always "coreference" for this schema
- `span_ids`: Array of span IDs that belong to this chain
- `entity_type`: (Optional) The entity type classification

## Workflow

### Recommended Annotation Process

1. **First pass - Create mentions**: Read through the text and highlight all entity mentions using the span schema
2. **Second pass - Create chains**: Group mentions into coreference chains
3. **Review**: Check that all mentions are correctly assigned and no chains are missing

### Tips for Annotators

- Start with the most prominent entity (often the main subject)
- Work through the text linearly, adding mentions to existing chains or creating new ones
- Pay attention to pronouns - they're easy to miss
- Consider definite descriptions ("the company", "the city") as potential mentions

## Use Cases

### Pronoun Resolution

Track which pronouns refer to which entities:

```yaml
annotation_schemes:
  - annotation_type: span
    name: all_mentions
    description: Highlight all nouns and pronouns
    labels:
      - name: NOUN
      - name: PRONOUN

  - annotation_type: coreference
    name: pronoun_coref
    description: Link pronouns to their referents
    span_schema: all_mentions
```

### Entity Linking Preparation

Create coreference chains as a preprocessing step for entity linking:

```yaml
annotation_schemes:
  - annotation_type: span
    name: entities
    description: Mark entity mentions for linking
    labels:
      - name: ENTITY
    entity_linking:
      enabled: true
      knowledge_bases:
        - name: wikidata
          type: wikidata

  - annotation_type: coreference
    name: coref
    description: Group mentions of the same entity before linking
    span_schema: entities
```

### Discourse Analysis

Analyze how entities are referenced throughout a document:

```yaml
annotation_schemes:
  - annotation_type: span
    name: discourse_mentions
    description: Mark all referring expressions
    labels:
      - name: DEFINITE
        tooltip: "Definite NPs (the X)"
      - name: INDEFINITE
        tooltip: "Indefinite NPs (a X)"
      - name: PRONOUN
        tooltip: "Pronouns"
      - name: PROPER
        tooltip: "Proper names"

  - annotation_type: coreference
    name: discourse_coref
    description: Create entity chains
    span_schema: discourse_mentions
    entity_types:
      - PERSON
      - PLACE
      - THING
      - ABSTRACT
```

## Best Practices

1. **Define clear mention boundaries**: Establish guidelines for what counts as a mention (e.g., include or exclude determiners?)

2. **Handle nested mentions**: Decide how to handle cases like "the CEO of Microsoft" - is this one mention or two?

3. **Consider generic references**: Determine whether generic references ("dogs bark") should be included

4. **Train annotators**: Coreference is complex - provide examples and practice rounds

5. **Use entity types sparingly**: Too many entity types can slow annotation without improving data quality

## Comparison with Other Tools

| Feature | Potato | brat | WebAnno |
|---------|--------|------|---------|
| Visual chain display | Yes | Partial | Yes |
| Chain merging | Yes | No | Yes |
| Entity types | Yes | Yes | Yes |
| Singleton support | Configurable | No | Yes |
| Keyboard shortcuts | Planned | Yes | Yes |

## Troubleshooting

### Chains Not Persisting

1. Verify the span schema name matches exactly in `span_schema`
2. Check that spans are being created before attempting to chain them
3. Look for JavaScript errors in browser console

### Visual Highlighting Not Showing

1. Verify `highlight_mode` is set correctly
2. Check that the coreference CSS is loaded
3. Ensure spans have the correct data attributes

### Cannot Add to Chain

1. Make sure a chain is selected (active)
2. Verify the mention isn't already in another chain
3. Check that the span belongs to the correct span schema

## Related Documentation

- [Span Annotation](schemas_and_templates.md#4-text-span-selection-span) - Creating text spans
- [Entity Linking](entity_linking.md) - Linking spans to knowledge bases
- [Span Linking](span_linking.md) - Other types of span relationships
