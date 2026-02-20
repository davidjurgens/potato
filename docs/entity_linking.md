# Entity Linking

Entity linking enables annotators to connect span annotations to external knowledge bases (KBs) like Wikidata or UMLS. This creates semantic links between text mentions and canonical entities, which is valuable for tasks like named entity recognition, concept normalization, and knowledge graph construction.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [Supported Knowledge Bases](#supported-knowledge-bases)
  - [Wikidata](#wikidata)
  - [UMLS](#umls)
  - [Custom REST APIs](#custom-rest-apis)
- [Multi-Select Mode](#multi-select-mode)
- [Multiple Knowledge Bases](#multiple-knowledge-bases)
- [User Interface](#user-interface)
- [Data Format](#data-format)
- [API Endpoints](#api-endpoints)
- [Extending with Custom Clients](#extending-with-custom-clients)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

When entity linking is enabled for a span annotation schema:
1. Annotators highlight text and assign a label (e.g., "PERSON", "ORGANIZATION")
2. A link icon appears on the span's control bar
3. Clicking the icon opens a search modal to find matching KB entities
4. The selected entity ID is stored with the span annotation
5. Linked spans display a filled icon and show entity details on hover

## Quick Start

Enable entity linking by adding the `entity_linking` configuration to a span schema:

```yaml
annotation_schemes:
  - annotation_type: span
    name: ner
    description: Named Entity Recognition with KB linking
    labels:
      - name: PERSON
        tooltip: "People's names"
      - name: ORGANIZATION
        tooltip: "Companies, agencies, institutions"
      - name: LOCATION
        tooltip: "Places, cities, countries"
    entity_linking:
      enabled: true
      knowledge_bases:
        - name: wikidata
          type: wikidata
          language: en
```

Run the example:
```bash
python potato/flask_server.py start examples/span/entity-linking/config.yaml -p 8000
```

## Configuration Reference

### Entity Linking Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable entity linking for this schema |
| `knowledge_bases` | list | `[]` | List of KB configurations (see below) |
| `auto_search` | boolean | `true` | Automatically search when the modal opens |
| `required` | boolean | `false` | Require entity link before saving span |
| `multi_select` | boolean | `false` | Allow linking to multiple entities (see [Multi-Select Mode](#multi-select-mode)) |

### Knowledge Base Configuration

Each knowledge base in the `knowledge_bases` list supports:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | string | required | Unique identifier for this KB (shown in dropdown) |
| `type` | string | required | KB type: `wikidata`, `umls`, or `rest` |
| `api_key` | string | `null` | API key for authenticated services |
| `base_url` | string | `null` | Base URL for REST APIs |
| `language` | string | `"en"` | Language code for search results |
| `timeout` | integer | `10` | Request timeout in seconds |
| `extra_params` | dict | `{}` | Additional parameters (type-specific) |

## Supported Knowledge Bases

### Wikidata

[Wikidata](https://www.wikidata.org/) is a free, open knowledge base with millions of entities across all domains. No API key required.

```yaml
entity_linking:
  enabled: true
  knowledge_bases:
    - name: wikidata
      type: wikidata
      language: en  # Supports: en, de, fr, es, zh, ja, ru, etc.
```

**Features:**
- 100+ million entities across all domains
- Multilingual labels and descriptions
- Entity aliases for better search (e.g., "NYC" finds "New York City")
- Links to Wikipedia articles
- Rich metadata (entity types, claims, sitelinks)

**Example Entities:**
| Entity ID | Label |
|-----------|-------|
| Q937 | Albert Einstein |
| Q9682 | World Health Organization |
| Q90 | Paris |
| Q5 | Human (type) |
| Q35120 | Company (type) |

**Search Behavior:**
- Multi-word queries search both the full phrase and individual words
- For "Albert Einstein", searches: "Albert Einstein", "Albert", "Einstein"
- Results are deduplicated and combined
- Aliases are included in search (Q60 matches "NYC", "New York", "Big Apple")

### UMLS

The [Unified Medical Language System](https://www.nlm.nih.gov/research/umls/) provides comprehensive medical and biomedical terminology. **Requires a free API key.**

```yaml
entity_linking:
  enabled: true
  knowledge_bases:
    - name: umls
      type: umls
      api_key: ${UMLS_API_KEY}  # Use environment variable
      # Or hardcode (not recommended for shared configs):
      # api_key: "your-api-key-here"
```

**Features:**
- Medical concepts, drugs, diseases, procedures, anatomy
- Concept Unique Identifiers (CUIs)
- Semantic type classification (Disease, Drug, Procedure, etc.)
- Cross-references to 200+ source vocabularies (SNOMED CT, ICD-10, MeSH, RxNorm)

**Obtaining an API Key:**
1. Create an account at [UTS (UMLS Terminology Services)](https://uts.nlm.nih.gov/uts/)
2. Sign the UMLS Metathesaurus License Agreement
3. Generate an API key from your profile page
4. Set as environment variable:
   ```bash
   export UMLS_API_KEY=your-api-key-here
   ```

**Example Concepts:**
| CUI | Preferred Term | Semantic Type |
|-----|---------------|---------------|
| C0011849 | Diabetes Mellitus | Disease or Syndrome |
| C0004057 | Aspirin | Pharmacologic Substance |
| C0018787 | Heart | Body Part, Organ |

### Custom REST APIs

Connect to any knowledge base with a REST API using the generic REST client:

```yaml
entity_linking:
  enabled: true
  knowledge_bases:
    - name: internal_kb
      type: rest
      base_url: https://api.example.com
      api_key: optional_api_key  # Sent as ?api_key= parameter
      timeout: 15
      extra_params:
        # Endpoint configuration
        search_endpoint: /search           # Appended to base_url
        entity_endpoint: /entity/{entity_id}  # {entity_id} is replaced
        search_query_param: q              # Query parameter name for search

        # Response field mapping (supports dot notation for nested JSON)
        results_path: data.results         # Path to results array
        entity_id_field: id                # Field containing entity ID
        label_field: name                  # Field containing display name
        description_field: description     # Field containing description
        aliases_field: aliases             # Field containing alias array
        type_field: type                   # Field containing entity type
        url_field: url                     # Field containing entity URL

        # Additional query parameters (prefix with param_)
        param_format: json                 # Adds ?format=json
        param_version: v2                  # Adds ?version=v2
```

**Expected Search Response Format:**
```json
{
  "data": {
    "results": [
      {
        "id": "ENT001",
        "name": "Example Entity",
        "description": "A sample entity for demonstration",
        "aliases": ["Example", "Sample Entity"],
        "type": "concept",
        "url": "https://example.com/entity/ENT001"
      },
      {
        "id": "ENT002",
        "name": "Another Entity",
        "description": "Another sample entity",
        "aliases": [],
        "type": "person",
        "url": "https://example.com/entity/ENT002"
      }
    ]
  }
}
```

**Expected Entity Detail Response Format:**
```json
{
  "id": "ENT001",
  "name": "Example Entity",
  "description": "Detailed description of the entity with additional context",
  "aliases": ["Example", "Sample Entity", "Demo"],
  "type": "concept",
  "url": "https://example.com/entity/ENT001"
}
```

**Configuration Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `search_endpoint` | `/search` | Path appended to base_url for search queries |
| `entity_endpoint` | `/entity/{entity_id}` | Path for entity details (`{entity_id}` is replaced) |
| `search_query_param` | `q` | Query parameter name for search text |
| `results_path` | `results` | Dot-notation path to results array (e.g., `data.items`) |
| `entity_id_field` | `id` | Field name for entity ID in results |
| `label_field` | `label` | Field name for entity display name |
| `description_field` | `description` | Field name for entity description |
| `aliases_field` | `aliases` | Field name for alias array |
| `type_field` | `type` | Field name for entity type |
| `url_field` | `url` | Field name for entity URL |

## Multi-Select Mode

Enable multi-select to allow annotators to link a span to multiple entities. This is useful for:
- **Ambiguous mentions** that could refer to multiple entities
- **Cross-KB linking** where the same concept exists in multiple knowledge bases
- **Uncertainty handling** when annotators aren't sure which entity is correct

```yaml
entity_linking:
  enabled: true
  multi_select: true  # Enable multiple entity selection
  knowledge_bases:
    - name: wikidata
      type: wikidata
      language: en
```

**UI Changes with Multi-Select:**

| Feature | Single Select | Multi-Select |
|---------|---------------|--------------|
| Selection | Click to select & close | Checkbox to toggle |
| Confirmation | Immediate | "Save Selection" button |
| Current links | Shows one entity | Shows all selected |
| Visual indicator | Filled icon | Filled icon (primary) |

**Visual Indicators:**
- **Green background + checkmark badge**: Entity is currently linked to this span
- Linked entities appear at the top of relevance-sorted results
- Checkboxes show selection state

**Data Storage:**
The primary (first selected) entity is stored in the standard fields:
- `kb_id`: Primary entity ID
- `kb_source`: Primary entity's knowledge base
- `kb_label`: Primary entity's label

Future versions may support storing the full list in `linked_entities`.

## Multiple Knowledge Bases

Configure multiple knowledge bases to let annotators choose the most appropriate source for each entity:

```yaml
entity_linking:
  enabled: true
  knowledge_bases:
    # General knowledge - people, places, organizations
    - name: wikidata
      type: wikidata
      language: en

    # Medical terminology
    - name: umls
      type: umls
      api_key: ${UMLS_API_KEY}

    # Internal company database
    - name: company_entities
      type: rest
      base_url: https://internal.company.com/api/entities
      api_key: ${INTERNAL_API_KEY}
```

A dropdown in the search modal lets annotators switch between configured knowledge bases. The first KB is selected by default.

## User Interface

### Link Icon on Spans

Each annotated span shows a link icon in its control bar (next to the delete button):

| Icon State | Meaning |
|------------|---------|
| Outline icon (unfilled) | No entity linked yet |
| Filled icon | Entity is linked |

### Search Modal

Clicking the link icon opens a modal with:

1. **Selected Text**: Shows the annotated span text
2. **KB Selector**: Dropdown to choose which knowledge base to search
3. **Search Input**: Text field for entity search (auto-filled with span text)
4. **Search Button**: Triggers search (also triggered by Enter key)
5. **Results List**: Matching entities with:
   - Entity label (display name)
   - Entity ID (e.g., Q937, C0011849)
   - Description (if available)
   - Aliases (up to 3 shown)
   - "View in KB" link
   - Green "Currently Linked" badge (if this entity is already linked)
6. **Current Link Section**: Shows currently linked entity with "Remove Link" button

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Enter | Submit search |
| Escape | Close modal |
| Click outside | Close modal |

### Tooltip on Hover

Hovering over a linked span shows a tooltip with:
- Knowledge base name (e.g., "wikidata")
- Entity ID (e.g., "Q937")
- Entity label (e.g., "Albert Einstein")
- Description (loaded asynchronously if not cached)

## Data Format

### Span Annotation with Entity Link

Entity-linked spans include additional fields:

```json
{
  "id": "ner_PERSON_0_15",
  "schema": "ner",
  "name": "PERSON",
  "title": "PERSON",
  "start": 0,
  "end": 15,
  "kb_id": "Q937",
  "kb_source": "wikidata",
  "kb_label": "Albert Einstein"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `kb_id` | string | Entity identifier in the knowledge base |
| `kb_source` | string | Name of the knowledge base (matches config name) |
| `kb_label` | string | Human-readable label from the KB |

### Output in Annotation Files

When exporting annotations, entity links appear in the span data:

```json
{
  "id": "instance_001",
  "text": "Albert Einstein was born in Ulm, Germany in 1879.",
  "annotations": {
    "ner": {
      "spans": [
        {
          "text": "Albert Einstein",
          "start": 0,
          "end": 15,
          "label": "PERSON",
          "kb_id": "Q937",
          "kb_source": "wikidata",
          "kb_label": "Albert Einstein"
        },
        {
          "text": "Ulm",
          "start": 28,
          "end": 31,
          "label": "LOCATION",
          "kb_id": "Q3012",
          "kb_source": "wikidata",
          "kb_label": "Ulm"
        },
        {
          "text": "Germany",
          "start": 33,
          "end": 40,
          "label": "LOCATION",
          "kb_id": "Q183",
          "kb_source": "wikidata",
          "kb_label": "Germany"
        }
      ]
    }
  }
}
```

## API Endpoints

The entity linking feature exposes these REST API endpoints:

### Search Entities

```
GET /api/entity_linking/search?q=<query>&kb=<kb_name>&limit=<max_results>
```

**Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `q` | Yes | - | Search query text |
| `kb` | Yes | - | Knowledge base name (from config) |
| `limit` | No | 10 | Maximum results to return |

**Response:**
```json
{
  "results": [
    {
      "entity_id": "Q937",
      "kb_source": "wikidata",
      "label": "Albert Einstein",
      "description": "German-born theoretical physicist",
      "aliases": ["Einstein", "A. Einstein"],
      "url": "https://www.wikidata.org/wiki/Q937"
    }
  ]
}
```

### Get Entity Details

```
GET /api/entity_linking/entity/<kb_name>/<entity_id>
```

**Response:**
```json
{
  "entity": {
    "entity_id": "Q937",
    "kb_source": "wikidata",
    "label": "Albert Einstein",
    "description": "German-born theoretical physicist (1879-1955)",
    "aliases": ["Einstein", "A. Einstein", "Albert Einstein"],
    "entity_type": "Q5",
    "url": "https://en.wikipedia.org/wiki/Albert_Einstein"
  }
}
```

### List Configured Knowledge Bases

```
GET /api/entity_linking/configured_kbs
```

**Response:**
```json
{
  "knowledge_bases": [
    {"name": "wikidata", "type": "wikidata"},
    {"name": "umls", "type": "umls"}
  ]
}
```

### Update Span Entity Link

```
POST /api/entity_linking/update_span
Content-Type: application/json

{
  "instance_id": "instance_001",
  "span_id": "ner_PERSON_0_15",
  "kb_id": "Q937",
  "kb_source": "wikidata",
  "kb_label": "Albert Einstein"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Span ner_PERSON_0_15 linked to wikidata:Q937"
}
```

To remove a link, send `null` values:
```json
{
  "instance_id": "instance_001",
  "span_id": "ner_PERSON_0_15",
  "kb_id": null,
  "kb_source": null,
  "kb_label": null
}
```

## Extending with Custom Clients

To add support for a new knowledge base type, create a client class that extends `KnowledgeBaseClient`:

```python
# my_kb_client.py
from potato.knowledge_base import (
    KnowledgeBaseClient,
    KnowledgeBaseConfig,
    KBEntity,
    register_kb_client
)
from typing import List, Optional
import requests

class MyKBClient(KnowledgeBaseClient):
    """Client for My Custom Knowledge Base."""

    API_URL = "https://my-kb.example.com/api/v1"

    def search(
        self,
        query: str,
        limit: int = 10,
        entity_type: Optional[str] = None
    ) -> List[KBEntity]:
        """Search the knowledge base for entities matching the query."""
        if not query.strip():
            return []

        params = {
            "q": query,
            "limit": limit,
            "lang": self.config.language
        }
        if entity_type:
            params["type"] = entity_type

        response = requests.get(
            f"{self.API_URL}/search",
            params=params,
            timeout=self.config.timeout
        )
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("results", []):
            results.append(KBEntity(
                entity_id=item["id"],
                kb_source=self.config.name,
                label=item["name"],
                description=item.get("description", ""),
                aliases=item.get("aliases", []),
                entity_type=item.get("type"),
                url=item.get("url")
            ))
        return results

    def get_entity(self, entity_id: str) -> Optional[KBEntity]:
        """Get detailed information about a specific entity."""
        if not entity_id:
            return None

        response = requests.get(
            f"{self.API_URL}/entity/{entity_id}",
            timeout=self.config.timeout
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json()

        return KBEntity(
            entity_id=item["id"],
            kb_source=self.config.name,
            label=item["name"],
            description=item.get("description", ""),
            aliases=item.get("aliases", []),
            entity_type=item.get("type"),
            url=item.get("url")
        )

# Register the client type
register_kb_client("my_kb", MyKBClient)
```

Then use in your configuration:
```yaml
knowledge_bases:
  - name: my_custom_kb
    type: my_kb  # Matches the registered name
    language: en
    timeout: 15
```

**Integration:** Import your custom client module before starting the server, or add it to Potato's `knowledge_base.py`.

## Best Practices

### General Recommendations

1. **Enable auto-search** for efficiency:
   ```yaml
   entity_linking:
     auto_search: true  # Pre-populate search with span text
   ```

2. **Don't require linking** unless essential:
   ```yaml
   entity_linking:
     required: false  # Don't block annotation if entity not found
   ```

3. **Set appropriate timeouts** for slow networks:
   ```yaml
   knowledge_bases:
     - name: wikidata
       type: wikidata
       timeout: 20  # Increase from default 10
   ```

### For NER Tasks

Match KB to entity type:

| Entity Type | Recommended KB |
|-------------|----------------|
| PERSON | Wikidata |
| ORGANIZATION | Wikidata |
| LOCATION | Wikidata |
| DATE/TIME | Usually no linking needed |
| Medical terms | UMLS |
| Domain-specific | Custom REST API |

### For Biomedical Text

1. **Use UMLS for medical normalization:**
   ```yaml
   knowledge_bases:
     - name: umls
       type: umls
       api_key: ${UMLS_API_KEY}
   ```

2. **Combine UMLS with Wikidata** for non-medical entities:
   ```yaml
   knowledge_bases:
     - name: umls
       type: umls
       api_key: ${UMLS_API_KEY}
     - name: wikidata
       type: wikidata
   ```

### For Ambiguous Entities

Enable multi-select when entities might be ambiguous:
```yaml
entity_linking:
  multi_select: true
```

This is useful for:
- Abbreviations (e.g., "WHO" = World Health Organization or rock band The Who)
- Common names (e.g., "John Smith" = many possible people)
- Polysemous terms (e.g., "Python" = snake, programming language, comedy group)

## Troubleshooting

### "Knowledge base not configured"

**Cause:** The KB name in the search request doesn't match any configured KB.

**Solution:** Ensure the `name` in your config matches:
```yaml
knowledge_bases:
  - name: wikidata  # This exact name must be used
    type: wikidata
```

### Wikidata Returns 403 Forbidden

**Cause:** Missing User-Agent header (required by Wikimedia API policy).

**Solution:** This is handled automatically by Potato. If you're behind a corporate proxy that strips headers, configure your proxy to allow the User-Agent header.

### UMLS Authentication Errors

**Causes:**
1. API key not set or invalid
2. UMLS license not accepted
3. API key expired

**Solutions:**
1. Verify key is set: `echo $UMLS_API_KEY`
2. Log into [UTS](https://uts.nlm.nih.gov/uts/) and accept the license
3. Generate a new API key if expired

### No Search Results

**Causes:**
1. Query too specific
2. Wrong language setting
3. Network connectivity issue

**Solutions:**
1. Try simpler/shorter search terms
2. Verify language code matches your text:
   ```yaml
   knowledge_bases:
     - name: wikidata
       type: wikidata
       language: en  # Change to match your text
   ```
3. Check server logs for network errors

### Entity Links Not Persisting

**Causes:**
1. Span ID mismatch between frontend and backend
2. JavaScript errors

**Solutions:**
1. Check browser console for errors (F12 → Console)
2. Check server logs for API errors
3. Verify the span has a valid ID in the DOM

### Slow Search Responses

**Causes:**
1. Network latency
2. Complex queries
3. KB service slowdown

**Solutions:**
1. Increase timeout:
   ```yaml
   knowledge_bases:
     - name: wikidata
       type: wikidata
       timeout: 30
   ```
2. Use simpler queries
3. Check KB service status

### Custom REST API Not Working

**Debugging steps:**
1. Test the API directly with curl:
   ```bash
   curl "https://api.example.com/search?q=test"
   ```
2. Verify `results_path` matches your response structure
3. Check that field names match your API response
4. Ensure CORS is enabled if API is on different domain

## Example Project

A complete working example is available at:
```
examples/span/entity-linking/
```

**Files:**
- `config.yaml` - Configuration with entity linking enabled
- `data/entity-linking-example.json` - Sample data with text to annotate

**Run it:**
```bash
python potato/flask_server.py start examples/span/entity-linking/config.yaml -p 8000 --debug --debug-phase annotation
```

Then open http://localhost:8000 in your browser.

## See Also

- [Span Annotation](schemas_and_templates.md#span-labeling) - Basic span annotation setup
- [Configuration Reference](configuration.md) - Full configuration options
- [Admin Dashboard](admin_dashboard.md) - Monitoring annotation progress
