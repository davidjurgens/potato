# Multi-Document Event Annotation

Annotate **events that span many documents**. Instead of labeling one document at
a time, annotators build *events* — first-class records that aggregate evidence
drawn from across a corpus into a shared template. This matches how cross-document
event corpora (ECB+, GVC, ERE) are actually constructed: the event is a node above
the documents, and each document contributes evidence to it.

A typical task: a corpus of disaster news reports, where a single event (e.g.
"2011 Central Thailand Floods") is described across dozens of articles. Annotators
fill template slots (event type, who was affected, what was damaged, where, when)
by citing text from the relevant documents.

Two cooperating pieces make this work:

- **Event template** (`event_template`) — the admin-defined slot schema plus the
  cross-document **event registry** that stores events, their member documents,
  and per-slot evidence citations. Works on the normal annotation page.
- **Corpus map** (`corpus_map`) — an optional 2D cluster-map navigation surface.
  At startup the corpus is embedded, clustered, projected to 2D, and each
  document's k-nearest-neighbors are precomputed. Annotators navigate by clicking
  points, browsing clusters, or following "similar documents".

## Quick start

```bash
python potato/flask_server.py start \
  examples/advanced/multi-document-events/config.yaml -p 8000
```

Open the annotation page to create events and cite evidence. With `corpus_map`
enabled, open `/corpus/map` for the 2D navigation surface (map + cluster browser
on the left, the document reader and event form on the right).

## Data model

Each document is its own instance (it gets its own embedding, cluster, and KNN).
Events live in a separate registry file, `event_registry.json`, in your
`output_annotation_dir`:

```json
{
  "version": 1,
  "events": {
    "evt_ab12cd34ef56": {
      "title": "2011 Central Thailand Floods",
      "template_name": "disaster_event",
      "slot_values": { "event_type": "flood", "where": "Ayutthaya" },
      "member_doc_ids": ["doc_01", "doc_02", "doc_17"],
      "evidence": [
        { "slot_name": "where", "doc_id": "doc_02",
          "span_start": 24, "span_end": 33, "quoted_text": "Ayutthaya" }
      ],
      "provenance": "annotator",
      "created_by": "alice"
    }
  }
}
```

Evidence is stored here (not in the per-document span store), so event data can
never corrupt span serialization. Citing evidence from a document automatically
adds that document to the event's membership.

## Configuration

### `event_template`

```yaml
event_template:
  enabled: true
  name: disaster_event
  allow_annotator_create: true          # annotators may create new events
  seed_events: data/seed_events.json    # optional: admin-seeded events
  slots:
    - { name: event_type,   description: "Kind of disaster", type: text }
    - { name: who_affected, description: "People/communities affected", type: text }
    - { name: what_damaged, description: "Property/infrastructure/economy", type: text }
    - { name: where,        description: "Location", type: text }
    - { name: when,         description: "When it occurred", type: text }
```

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Turn the event registry on. |
| `name` | `event_template` | Template name recorded on each event. |
| `allow_annotator_create` | `true` | If false, annotators may only fill/attach admin-seeded events. |
| `seed_events` | — | A JSON file (or inline list) of pre-created events. Loaded once, id-idempotent: annotator edits are never clobbered on restart. |
| `slots` | *(required)* | List of `{name, description, type}`. Slot names must be unique. |

Add a matching `multi_document_event` annotation scheme so the event form appears
on the annotation page:

```yaml
annotation_schemes:
  - annotation_type: multi_document_event
    name: events
    description: "Group documents into events and fill each slot with evidence"
    slots: [...]                  # same slots as the template
    allow_annotator_create: true
```

Give the document field `span_target: true` so evidence can be cited by selecting
text:

```yaml
instance_display:
  fields:
    - key: text
      type: text
      span_target: true
```

### `corpus_map` (optional)

Requires `sentence-transformers`, `scikit-learn`, and (for the nicest layout)
`umap-learn`. If UMAP is unavailable the map falls back to a numpy PCA projection.

```yaml
corpus_map:
  enabled: true
  build_on_start: true                     # build the map in a background thread
  embedding_model: all-MiniLM-L6-v2
  clustering: { num_clusters: auto, items_per_cluster: 6 }
  umap: { n_neighbors: 10, min_dist: 0.1, metric: cosine }
  knn: { k: 5 }
  cluster_labeling: { enabled: true, use_llm: false }
```

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Turn the corpus map on. |
| `build_on_start` | `true` | Build in the background at boot; the page polls `/corpus/api/build_status`. |
| `embedding_model` | `all-MiniLM-L6-v2` | Sentence-transformer model. |
| `clustering.num_clusters` | `auto` | `auto` sizes clusters from `items_per_cluster`, or set an integer. |
| `knn.k` | `10` | Number of nearest neighbors precomputed per document. |
| `cluster_labeling.use_llm` | `false` | If false, clusters are labeled with their most distinctive terms (offline, deterministic). |

Derived artifacts are cached under `output_annotation_dir/.corpus_map_cache/`. Use
the **Rebuild** button (admins) or `POST /corpus/api/rebuild` to recompute.

## Assignment

Cross-document events require every annotator to reach any document, so the corpus
map bypasses the per-user assignment queue — clicking a point assigns that
document to the annotator on demand. A restrictive `per_annotator_quota` alongside
`corpus_map.enabled` will hide documents from the reader; Potato warns about this
at startup.

## Concurrency

Events are a shared pool: any annotator can edit any event. Slot edits use
optimistic locking — if two annotators edit the same event, the second save is
rejected (HTTP 409) and the form reloads the latest version instead of silently
overwriting.

## HTTP API

All state-changing routes require an authenticated session and pass a same-origin
(CSRF) check.

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/corpus/api/event_template` | Template slots + `allow_annotator_create`. |
| GET | `/corpus/api/events?doc_id=<id>` | Events (optionally for one document). |
| POST | `/corpus/api/event` | Create an event. |
| POST | `/corpus/api/event/<id>/slot` | Set a slot value (`expected_updated_at` enables optimistic locking). |
| POST | `/corpus/api/event/<id>/member` | Attach/detach a document. |
| POST | `/corpus/api/event/<id>/evidence` | Cite a `(doc, span)` for a slot. |
| DELETE | `/corpus/api/event/<id>` | Delete an event. |
| GET | `/corpus/map` | The annotator map page. |
| GET | `/corpus/api/map_data` | Cluster-colored points + clusters. |
| GET | `/corpus/api/clusters` | Cluster list for the sidebar. |
| GET | `/corpus/api/knn/<doc_id>` | K nearest neighbors of a document. |
| POST | `/corpus/api/goto` | Point the reader at a document (assigns on demand). |
| POST | `/corpus/api/rebuild` | Rebuild the map (admin). |

## Related

- [Embedding Visualization](embedding_visualization.md) — the admin-side corpus scatter used to prioritize the annotation queue.
- [Task Assignment](task_assignment.md) — assignment strategies.
