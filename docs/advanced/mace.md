# MACE Annotator Competence Estimation

## Overview

MACE (Multi-Annotator Competence Estimation) is a Variational Bayes EM algorithm that jointly estimates **true labels** for each item and **annotator competence** scores. It models each annotator as either "knowing" (produces correct labels) or "guessing" (produces random labels), yielding a competence score between 0.0 and 1.0 for each annotator.

MACE is useful when you have multiple annotators labeling the same items and want to:
- Identify which annotators are most reliable
- Produce higher-quality predicted labels by weighting annotator contributions
- Detect low-quality annotators (spammers) automatically
- Measure label uncertainty (entropy) per item

MACE works with categorical annotation types: `radio`, `likert`, `select`, and `multiselect`. It does not apply to free-text, span, slider, or numeric annotations.

### What MACE computes

1. **Data extraction**: Potato collects all annotations for each schema across all annotators, building an items-by-annotators matrix.
2. **EM algorithm**: MACE runs multiple random restarts of the Variational Bayes EM algorithm, keeping the solution with the best log-likelihood.
3. **Output**: For each schema, MACE produces predicted labels, label entropy (uncertainty), and per-annotator competence scores.
4. **Triggering**: MACE runs automatically after every N new annotations (configurable), or can be triggered manually via the admin API.

For multiselect schemas, MACE runs a separate binary classification (yes/no) for each option, then merges results.

---

## Configuration

MACE is configured through the `mace` section of your project's YAML config file.

```yaml
# MACE competence estimation configuration
mace:
  # Enable or disable MACE.
  # Type: bool
  # Default: false
  enabled: true

  # Run MACE after every N new annotations across all users.
  # Lower values give more frequent updates but cost more compute.
  # Type: int
  # Default: 10
  trigger_every_n: 10

  # Minimum number of annotators per item required before including
  # that item in the MACE computation. Items with fewer annotations
  # are excluded.
  # Type: int
  # Default: 3 (must be >= 2)
  min_annotations_per_item: 3

  # Minimum number of eligible items required before MACE will run.
  # Prevents running on too little data.
  # Type: int
  # Default: 5
  min_items: 5

  # Number of random restarts for the EM algorithm. More restarts
  # reduce the chance of finding a local optimum but increase runtime.
  # Type: int
  # Default: 10
  num_restarts: 10

  # Number of EM iterations per restart.
  # Type: int
  # Default: 50
  num_iters: 50

  # Prior parameter for annotator spamming (Beta distribution).
  # Lower values produce more peaked priors.
  # Type: float
  # Default: 0.5
  alpha: 0.5

  # Prior parameter for guessing strategy (Dirichlet distribution).
  # Lower values produce more peaked priors.
  # Type: float
  # Default: 0.5
  beta: 0.5
```

### Minimal Configuration

```yaml
mace:
  enabled: true
```

This uses all defaults: triggers every 10 annotations, requires 3 annotators per item, minimum 5 eligible items, 10 restarts with 50 iterations each.

---

## Admin API Endpoints

All MACE endpoints require admin authentication via the `X-API-Key` header. The API key is set in your config's `admin_api_key` field.

### GET /admin/api/mace/overview

Returns a summary of MACE status, annotator competence scores, and schema information.

**Request:**
```bash
curl http://localhost:8000/admin/api/mace/overview \
  -H "X-API-Key: your-admin-key"
```

**Response (before MACE has run):**
```json
{
  "enabled": true,
  "has_results": false,
  "schemas": [],
  "annotator_competence": {},
  "total_annotations": 0,
  "annotations_until_next_run": 10
}
```

**Response (after MACE has run):**
```json
{
  "enabled": true,
  "has_results": true,
  "schemas": [
    {
      "key": "sentiment",
      "schema_name": "sentiment",
      "option_name": null,
      "num_annotators": 3,
      "num_instances": 120,
      "log_likelihood": -184.2,
      "timestamp": "2026-01-14T09:31:07",
      "label_mapping": {"0": "negative", "1": "positive"},
      "reliability": {
        "num_items": 120,
        "num_answers": 360,
        "label_counts": {"negative": 108, "positive": 252},
        "majority_label_share": 0.7,
        "constant_annotators": [],
        "min_items_configured": 5,
        "trustworthy": true,
        "warnings": []
      }
    }
  ],
  "annotator_competence": {
    "user_1": {"average": 0.92, "scores": {"sentiment": 0.92}},
    "user_2": {"average": 0.85, "scores": {"sentiment": 0.85}},
    "user_3": {"average": 0.45, "scores": {"sentiment": 0.45}}
  },
  "reliability_warnings": [],
  "total_annotations": 30,
  "annotations_until_next_run": 0
}
```

An annotator who gave the same answer to every item on any schema also carries
`constant_response` in `annotator_competence`, listing the schema, the answer
and how many items. `reliability_warnings` collects every schema's warnings in
one place, so a caller can check one field rather than walking the schema list.
Read [Reliability and label skew](#reliability-and-label-skew) before acting on
a competence score.

### GET /admin/api/mace/predictions

Returns predicted labels and entropy for a specific schema, optionally filtered by instance.

**Request (all items for a schema):**
```bash
curl "http://localhost:8000/admin/api/mace/predictions?schema=sentiment" \
  -H "X-API-Key: your-admin-key"
```

**Response:**
```json
{
  "schema": "sentiment",
  "predicted_labels": {
    "item_1": "positive",
    "item_2": "negative",
    "item_3": "positive"
  },
  "label_entropy": {
    "item_1": 0.02,
    "item_2": 0.15,
    "item_3": 0.01
  }
}
```

**Request (single instance):**
```bash
curl "http://localhost:8000/admin/api/mace/predictions?schema=sentiment&instance_id=item_1" \
  -H "X-API-Key: your-admin-key"
```

**Response:**
```json
{
  "schema": "sentiment",
  "instance_id": "item_1",
  "predicted_label": "positive",
  "entropy": 0.02
}
```

### POST /admin/api/mace/trigger

Manually trigger a MACE computation, regardless of annotation count.

**Request:**
```bash
curl -X POST http://localhost:8000/admin/api/mace/trigger \
  -H "X-API-Key: your-admin-key"
```

**Response:**
```json
{
  "status": "success",
  "schemas_processed": 1,
  "schemas": ["sentiment"]
}
```

---

## Adjudication Integration

When both MACE and adjudication are enabled, MACE predicted labels are included in adjudication items as an additional signal. The `mace_predictions` field appears in the adjudication API response for each item, showing MACE's predicted label for each schema.

```yaml
adjudication:
  enabled: true
  adjudicator_users: ["admin"]
  min_annotations: 2

mace:
  enabled: true
  trigger_every_n: 10
  min_annotations_per_item: 2
```

---

## Interpreting Results

### Annotator Competence

- **0.9 - 1.0**: Highly reliable annotator. Consistently produces correct labels.
- **0.7 - 0.9**: Good annotator. Occasional disagreements but generally reliable.
- **0.5 - 0.7**: Moderate annotator. May benefit from additional training or guideline clarification.
- **Below 0.5**: Potential spammer or confused annotator. Review their annotations and consider retraining.

### Reliability and label skew

MACE explains an answer as either the annotator trying or the annotator spamming from a fixed strategy. An annotator whose fixed strategy is the majority class is nearly indistinguishable from a competent one, because both explanations predict the same answers. On a corpus where one label holds most of the answers, the scores can rank a constant-response annotator at the top.

Measured on synthetic data, 40 trials per cell, with one annotator always giving the majority-class answer:

| label prior | items | spammer ranked last |
|---|---|---|
| 50/50 | 30 | 95% |
| 50/50 | 300 | 100% |
| 67/33 | 30 | 75% |
| 67/33 | 300 | 100% |
| 80/20 | 30 | 32% |
| 80/20 | 300 | 10% |

At 2:1 more data fixes it. At 4:1 it does not, and the ranking gets worse as items are added, because the model grows more confident in the wrong explanation. Rare-event schemes such as toxicity, hate speech and misinformation usually sit at that skew or beyond.

`/admin/api/mace/overview` reports this beside the scores. Each schema carries a `reliability` block with the item count, the label distribution, any annotator who gave the same answer to every item, and a `trustworthy` flag with the reasons. Neither of the last two checks needs a model: a constant answer is visible by looking, and skew is a count.

`min_items` defaults to 5, which is enough to run a fit and not enough to publish a per-annotator score. Around 30 items on balanced data is where the estimates start tracking true accuracy. Potato reports the item count rather than refusing below it, so a study that relies on MACE today keeps working.

### Label Entropy

- **Near 0.0**: High confidence. MACE is very certain about the predicted label.
- **Above 0.5**: Moderate uncertainty. The item may be genuinely ambiguous.
- **Near log(num_labels)**: Maximum uncertainty. No consensus among annotators.

---

## Troubleshooting

### MACE never runs

- Check that `mace.enabled` is `true` in your config.
- Ensure you have enough annotators per item (`min_annotations_per_item`, default 3).
- Ensure you have enough eligible items (`min_items`, default 5).
- Check server logs for MACE-related messages.

### All competence scores are similar

- This is expected when all annotators agree perfectly. MACE differentiates annotators primarily through disagreements.
- Try lowering `min_annotations_per_item` to include more data.

### MACE results don't update

- MACE only re-runs after `trigger_every_n` new annotations. Use the manual trigger endpoint to force an update.
- Results are cached in memory and persist across annotation sessions.
