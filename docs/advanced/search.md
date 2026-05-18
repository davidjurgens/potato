# Search

Universal full-text search over instance text, backed by SQLite **FTS5**.
Not gated to QDA Mode — admins/adjudicators can search any project to
locate instances. An optional, guarded **annotator search-and-claim**
lets annotators pull rare candidates into their own queue.

## Overview

- Lexical search via a `SearchBackend` abstraction. FTS5 ships now; a
  `VectorBackend` stub documents the contract for future semantic search.
- The index is built from instance text on server start and lives in the
  universal `<task_dir>/project.sqlite` (`instance_fts` table).
- If the SQLite build lacks FTS5, search is cleanly disabled (endpoints
  return `503`); the rest of Potato is unaffected.

## Configuration

```yaml
search:
  enabled: true            # default true (universal)
  backend: fts5            # only fts5 in this release
  max_instances: 100000    # cap on indexed instances
  annotator_claim: false   # opt-in annotator search-and-claim (guarded)
```

| Option | Default | Description |
|--------|---------|-------------|
| `search.enabled` | `true` | Build the index and enable endpoints. |
| `search.backend` | `fts5` | Search backend. |
| `search.max_instances` | `100000` | Maximum instances indexed. |
| `search.annotator_claim` | `false` | Enable annotator-facing search + claim (see guard below). |

## Endpoints

- `GET /admin/api/search?q=<query>&limit=<n>` — admin/adjudicator,
  **read-only**. Always safe (no self-selection). Requires the admin
  API key (`X-API-Key`) or adjudicator status.
- `GET /api/search?q=` — annotator search (only when
  `annotator_claim: true`).
- `POST /api/search/claim {instance_id}` — pull a matching instance into
  the annotator's queue (only when `annotator_claim: true`).

User queries are tokenized and quoted before hitting FTS5, so arbitrary
punctuation (including injection attempts) is safe and never interpreted
as FTS5 syntax.

## Annotator search-and-claim: compatibility guard

Letting annotators search and **claim** instances is *self-selection*,
which corrupts designs where the platform — not the annotator — must
choose the next item. When `search.annotator_claim: true`, Potato
**refuses to start** (raises a configuration error naming the conflict)
if any of these are also configured:

| Conflicting feature | Why |
|---------------------|-----|
| `assignment_strategy`: random / diversity_clustering / max_diversity / active_learning / llm_confidence / least_annotated / category_based | Self-selection breaks sampling/ordering |
| `max_annotations_per_item` / `num_annotators_per_item` / `min_annotators_per_instance` > 1 | IAA overlap can't be guaranteed |
| `attention_checks.enabled` / `gold_standards.enabled` | QC items could be located/avoided |
| `icl_labeling.enabled` | Blind LLM-verification tasks must not be findable |
| `adjudication.enabled` | The adjudication queue is curated |
| MTurk / Prolific backend | HIT = the assigned unit; breaks payment/coverage |

Annotator claim is supported with **solo_mode/qda_mode** (single coder
over the whole corpus), or **`fixed_order`** assignment without overlap,
QC injection, ICL verification, adjudication, or a crowd backend. For
every other design, use read-only admin search instead.

> Note: under `fixed_order` the whole corpus is typically pre-assigned to
> a user, so claim is most useful when per-user assignment is capped
> (`max_annotations_per_user`) or instances are assigned incrementally.

## Example

```bash
python potato/flask_server.py start examples/advanced/search-example/config.yaml -p 8000
# then, with the admin key from the config:
curl -H "X-API-Key: search-example-key" \
  "http://localhost:8000/admin/api/search?q=rare"
```

## Related

- [Memos](memos.md)
- [Task Assignment](task_assignment.md)
- [Data Export](../data-export/export_formats.md)
