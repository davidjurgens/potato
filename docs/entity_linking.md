# Entity Linking

Entity linking enables annotators to connect span annotations to external knowledge bases (KBs) like Wikidata or UMLS. This creates semantic links between text mentions and canonical entities, which is valuable for tasks like named entity recognition, concept normalization, and knowledge graph construction.

## Overview

When entity linking is enabled for a span annotation schema:
1. Annotators highlight text and assign a label (e.g., "PERSON", "ORGANIZATION")
2. A link icon appears on the span
3. Clicking the icon opens a search modal to find matching KB entities
4. The selected entity ID is stored with the span annotation

## Quick Start

Enable entity linking by adding the `entity_linking` configuration to a span schema:

```yaml
annotation_schemes:
  - annotation_type: span
    name: ner
    description: Named Entity Recognition with KB linking
    labels:
      - PERSON
      - ORGANIZATION
      - LOCATION
    entity_linking:
      enabled: true
      knowledge_bases:
        - name: wikidata
          type: wikidata
          language: en
```

## Configuration Options

### Entity Linking Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable entity linking for this schema |
| `knowledge_bases` | list | `[]` | List of KB configurations |
| `auto_search` | boolean | `true` | Automatically search when span is created |
| `required` | boolean | `false` | Require entity link before saving span |

### Knowledge Base Configuration

Each knowledge base in the `knowledge_bases` list supports:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | string | required | Unique identifier for this KB |
| `type` | string | required | KB type: "wikidata", "umls", or "rest" |
| `api_key` | string | `null` | API key for authenticated services |
| `language` | string | `"en"` | Language code for search results |
| `timeout` | integer | `10` | Request timeout in seconds |

## Supported Knowledge Bases

### Wikidata

Wikidata is a free, open knowledge base with millions of entities across all domains. No API key required.

```yaml
entity_linking:
  enabled: true
  knowledge_bases:
    - name: wikidata
      type: wikidata
      language: en  # Supports: en, de, fr, es, etc.
```

**Features:**
- Search by name, alias, or description
- Multilingual support
- Links to Wikipedia articles
- Rich entity metadata (type, aliases, claims)

**Example entities:**
- `Q937` - Albert Einstein
- `Q9682` - World Health Organization
- `Q90` - Paris

### UMLS

The Unified Medical Language System provides medical and biomedical terminology. Requires an API key from the National Library of Medicine.

```yaml
entity_linking:
  enabled: true
  knowledge_bases:
    - name: umls
      type: umls
      api_key: ${UMLS_API_KEY}  # Use environment variable
```

**Features:**
- Medical concepts and terminology
- Semantic type filtering
- Cross-references to multiple medical vocabularies

**Obtaining an API Key:**
1. Register at [UTS (UMLS Terminology Services)](https://uts.nlm.nih.gov/uts/)
2. Request an API key from your profile
3. Set as environment variable: `export UMLS_API_KEY=your-key`

### Custom REST APIs

Connect to any REST API that supports entity search:

```yaml
entity_linking:
  enabled: true
  knowledge_bases:
    - name: my_kb
      type: rest
      base_url: https://api.example.com
      extra_params:
        search_endpoint: /search
        entity_endpoint: /entity/{entity_id}
        search_query_param: q
        results_path: data.results
        entity_id_field: id
        label_field: name
        description_field: description
```

**Configuration options for REST APIs:**

| Parameter | Description |
|-----------|-------------|
| `search_endpoint` | Path for search queries |
| `entity_endpoint` | Path for entity details (use `{entity_id}` placeholder) |
| `search_query_param` | Query parameter name for search |
| `results_path` | Dot-notation path to results array in response |
| `entity_id_field` | Field name for entity ID |
| `label_field` | Field name for entity label |
| `description_field` | Field name for entity description |

## Output Format

Entity-linked spans include additional fields in the annotation output:

```json
{
  "id": "span_abc123",
  "schema": "ner",
  "name": "PERSON",
  "start": 0,
  "end": 15,
  "kb_id": "Q937",
  "kb_source": "wikidata",
  "kb_label": "Albert Einstein"
}
```

| Field | Description |
|-------|-------------|
| `kb_id` | Entity identifier in the knowledge base |
| `kb_source` | Name of the knowledge base |
| `kb_label` | Human-readable label from the KB |

## User Interface

### Link Icon

Each span shows a link icon that indicates its linking status:
- **Outline icon**: No entity linked yet
- **Filled icon**: Entity already linked

### Search Modal

The search modal provides:
1. **KB selector**: Choose which knowledge base to search
2. **Search input**: Type to search for entities
3. **Results list**: Click to select an entity
4. **Current link display**: Shows currently linked entity with option to remove

### Tooltip on Hover

Hovering over a linked span shows:
- Knowledge base name
- Entity ID
- Entity label
- Description (when available)

## Multiple Knowledge Bases

You can configure multiple knowledge bases. Annotators can switch between them in the search modal:

```yaml
entity_linking:
  enabled: true
  knowledge_bases:
    - name: wikidata
      type: wikidata
      language: en
    - name: umls
      type: umls
      api_key: ${UMLS_API_KEY}
    - name: custom_kb
      type: rest
      base_url: https://my-api.example.com
```

## Best Practices

### For NER Tasks

1. **Use appropriate KB per entity type:**
   - PERSON, ORG, LOC: Wikidata
   - Medical concepts: UMLS
   - Domain-specific: Custom KB

2. **Consider making linking optional:**
   ```yaml
   entity_linking:
     required: false  # Don't block annotation if entity not found
   ```

3. **Enable auto-search for efficiency:**
   ```yaml
   entity_linking:
     auto_search: true  # Pre-populate search with span text
   ```

### For Biomedical Text

1. **Use UMLS for medical normalization:**
   ```yaml
   knowledge_bases:
     - name: umls
       type: umls
       api_key: ${UMLS_API_KEY}
   ```

2. **Combine with Wikidata for general entities:**
   ```yaml
   knowledge_bases:
     - name: umls
       type: umls
       api_key: ${UMLS_API_KEY}
     - name: wikidata
       type: wikidata
   ```

## API Endpoints

The entity linking feature exposes these API endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/entity_linking/search` | GET | Search a knowledge base |
| `/api/entity_linking/entity/<kb>/<id>` | GET | Get entity details |
| `/api/entity_linking/configured_kbs` | GET | List configured KBs |
| `/api/entity_linking/update_span` | POST | Update span with entity link |

## Example Project

A complete example is available at:
```
project-hub/simple_examples/simple-entity-linking/
```

Run it with:
```bash
python potato/flask_server.py start project-hub/simple_examples/simple-entity-linking/config.yaml -p 8000 --debug --debug-phase annotation
```

## Troubleshooting

### "Knowledge base not configured"

Ensure the KB name in your search matches a configured KB:
```yaml
knowledge_bases:
  - name: wikidata  # This name must match
    type: wikidata
```

### UMLS API errors

1. Verify your API key is set: `echo $UMLS_API_KEY`
2. Check key validity at [UTS website](https://uts.nlm.nih.gov/uts/)
3. Ensure key has not expired

### No search results

1. Try simpler search terms
2. Check language setting matches your text
3. Verify KB API is reachable

### Slow search responses

Increase timeout for slow connections:
```yaml
knowledge_bases:
  - name: wikidata
    type: wikidata
    timeout: 30  # Increase from default 10
```

## See Also

- [Span Annotation](schemas_and_templates.md#span-labeling)
- [Named Entity Recognition](schemas_and_templates.md#span-labeling)
- [Configuration Reference](configuration.md)
