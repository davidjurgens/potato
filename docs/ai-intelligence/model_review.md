# Reviewing Model Output

Model pre-labels, then human QC — check the least confident, correct what is
wrong, ship. This is how most annotation pipelines run once there is a model
worth running.

Potato had the parts and not the workflow. `ai_prelabel` writes predictions,
active learning ranks by uncertainty, curation slices the data, and
adjudication compares one human against another. Comparing a human against the
model had no home.

---

## Quick start

```yaml
assignment_strategy: model_review
pre_annotation:
  enabled: true
  field: predictions
```

Annotators are now served prelabelled items least-confident first. The report:

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/admin/model-review
```

```json
{
  "n_items": 12,
  "n_prelabelled": 9,
  "queue": ["r00", "r01", "r02", "..."],
  "worst_first": ["r00", "r01"],
  "empty_prediction_ids": ["r03", "r07", "r11"],
  "n_empty": 3,
  "metrics": { "precision": null, "recall": null, "..." : "..." }
}
```

---

## Two separate review jobs

### Worst-first review

An item's rank is its **lowest** prediction confidence. One bad box makes an
item worth reviewing even beside nine good ones, and a mean would average that
signal away.

Items whose predictions carry no confidence sort after the ones that do. A
model that does not report confidence is not thereby unsure, and treating it as
confidence zero fills the worst-first queue with items nobody has a reason to
doubt.

The convention is to check the worst 10–20%. `worst_first` is the least
confident 20% of the queue, and never fewer than one item.

### Items the model said nothing about

A wrong prediction is visible in a review UI. It is right there, wrong. A
missing prediction is invisible: the reviewer sees an empty item and moves on.

A confidence-ordered queue cannot surface one either, since an item with no
prediction has no confidence to be low. So missing detections survive review
unless someone goes looking for them.

Potato ships a built-in slice for that, with no configuration:

```bash
curl -H "X-API-Key: $KEY" \
  "http://localhost:8000/curation/api/slices/model-found-nothing/resolve"
```

It appears in `/admin/catalog` alongside your own slices, and can become a
review dataset through the normal slice-to-dataset path.

!!! note "An empty prediction list is an answer"
    `"predictions": {"boxes": []}` means the model looked and found nothing.
    That is what puts an item in the pool. An item with no `predictions` key at
    all counts the same way.

---

## Verdicts

A reviewer's judgement of a prelabel is stored separately from an annotation:

```bash
curl -X POST -H "Content-Type: application/json" \
     -d '{"instance_id": "r00", "verdict": "accept", "schema_name": "tone"}' \
     http://localhost:8000/api/model-review/verdict
```

| Verdict | Meaning |
|---|---|
| `accept` | The model was right |
| `correct` | Partly right; the human changed something |
| `reject` | Wrong |

"The model was right" and "a human independently chose this label" are
different facts. Storing the first as the second makes model precision
unmeasurable, because every accepted prelabel then looks like human work.

Re-reviewing replaces a verdict rather than appending, so an annotator who
changes their mind is counted once. An unknown verdict is refused: a silently
stored typo would make the precision denominator wrong with nothing to show
for it.

---

## Precision and recall

**Precision** is the accepted share of reviewed prelabels. A *corrected*
prelabel does not count as a true positive — it was partly wrong, and counting
corrections as correct lets a model that is always nearly-right score
perfectly.

**Recall** requires someone to have opened the empty-prediction pool. Until
they have, Potato reports:

```json
"recall": null,
"recall_note": "The empty-prediction pool was not reviewed, so there is no
                evidence about what the model missed and recall cannot be
                computed. Sample it from the empty-prediction slice."
```

A recall computed over an unreviewed denominator would be an assumption
reported as a measurement.

Once the pool is sampled, a verdict on an empty item can only mean the reviewer
found something the model had not, so each is a confirmed false negative and
recall becomes computable. Only items a human actually opened count; anything
else moves recall by assumption.

Verdicts on empty items stay out of the precision denominator, so the model is
not penalised for a prediction it never made.

---

## Assignment behaviour

`assignment_strategy: model_review` serves the queue. Items with no prediction
are excluded from assignment; review those through the slice instead.

The strategy is incompatible with `search.annotator_claim`, which lets
annotators reorder a queue whose order is what makes it useful.

---

## Related

- [AI Support](ai_support.md) — generating the prelabels
- [Active Learning](active_learning_guide.md) — a different use of the same
  uncertainty signal
- [Near-Duplicate Detection](../advanced/near_duplicates.md) — the other
  curation pass worth running before annotation starts
- [AI Costs](ai_costs.md)
