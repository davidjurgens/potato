# Presentation Order and Position Bias

Judges, human and model alike, favour the option offered first. When every
annotator sees the same options in the same order, that pull does not cancel
across annotators: it inflates agreement while biasing the estimate, so the
reliability figure comes out confidently wrong. For a tool whose job is telling
researchers whether their annotations are reliable, that is a worse failure
than it would be for a tool that only collects them.

Potato records which order every annotator saw, and can randomise it.

---

## Quick start

```yaml
annotation_schemes:
  - annotation_type: radio
    name: tone
    description: Tone
    randomize_order: true
    labels: [very positive, positive, neutral, negative, very negative]
```

Two annotators on the same item see different arrangements. The same annotator
returning to the same item sees the one they answered against.

---

## The record

Randomisation only helps data collected after you switch it on. Recording the
order helps data you already have: an analyst can condition on what each
annotator saw and correct for the bias afterwards.

So the order is written down for every ordered scheme regardless.
`randomize_order: false` records "shown as configured", which is worth having.

The record lands in two places:

- `user_state.json`, under `instance_id_to_presentation_order`
- each item's behavioural data, under `presentation_order`, so every export and
  analysis path that reads behavioural data gets it

```json
"instance_id_to_presentation_order": {
  "d1": {
    "tone": ["neutral", "very negative", "positive", "negative", "very positive"],
    "topic": ["service", "product", "price"]
  }
}
```

The first render is what is kept. A later re-render, after you edit the config
say, does not rewrite history and make a stored answer look as though it was
given under a different arrangement.

---

## Where it applies

| Scheme | Order recorded | Can be randomised |
|---|---|---|
| `radio`, `multiselect`, `select`, `multirate` | ✅ | ✅ |
| `pairwise` | ✅ (source indices) | ✅ |
| `hierarchical_multiselect`, `ranking`, `bws`, `rollout_evaluation`, `trajectory_eval`, `conjoint` | ✅ | ❌ not yet |

Asking to randomise a scheme in the bottom row logs a warning rather than
silently pretending to. The order is still recorded, so the data stays
correctable, and a researcher who believed their study was de-biased when it
was not is worse off than one who was told.

### Pairwise is different

A pairwise scheme's two candidates come from the item's own data rather than
from the scheme's labels, and the client lays them out in the order it receives
them. Potato permutes that list before it reaches the page, and records source
indices rather than label names:

```json
"better": [1, 0]
```

The candidates differ per item, so "this annotator saw the item that was second
in the data first" is the only fact an analyst can condition on.

---

## Choosing the order

Deterministically, from `(user_id, instance_id, scheme_name)`, hashed with
blake2b.

All three parts matter. Seeding on the annotator alone gives one person the
same arrangement on every item, so their first-position preference lands on the
same label every time and is correlated across the whole study rather than
averaged out.

!!! note "Not Python's `hash()`"
    String hashing is salted per process unless `PYTHONHASHSEED` is pinned, so
    a builtin hash re-orders every option set on every server restart and an
    annotator returning to an item is asked a different question.

    `option_randomization` — the older key — still works and is honoured
    identically.

---

## Is your LLM judge just picking the first option?

The same question for models. The usual check is to swap the positions so the
judge cannot always pick the first, then hand-label a sample to see whether it
is any good at all. The second half is human work; the first half is
arithmetic.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"schema": "sentiment", "max_items": 50}' \
     http://localhost:8000/admin/api/judge-position-bias
```

Every sampled item is judged twice, once with the allowed labels in configured
order and once reversed. Nothing about the item changes, so any difference in
the verdict is attributable to the order.

The report separates three failure modes, since they have different fixes:

| Reading | What it means | What to do |
|---|---|---|
| High flip rate **and** high first-position rate in both runs | A systematic position preference | Randomise, and correct the existing data |
| High flip rate, no first-position pull | The judge is inconsistent rather than biased | Randomising does not help; fix the rubric |
| Zero flips, one label on almost everything | Order-invariant and uninformative | Check the label distribution before trusting anything |

The result feeds the `position` slot on the [judge eval
card](../ai-intelligence/judge_calibration.md), which had been empty since it
was written.

!!! warning "This is the most expensive action in Potato"
    Two model calls per item per schema. It samples rather than covering the
    project, and the response says how many items it used. See
    [AI Costs](../ai-intelligence/ai_costs.md).

Probes under twenty usable pairs are reported but flagged unreliable. A small
probe saying "5 items, 2 flips" beats silence, and nobody should quote it as a
finding.

---

## Correcting existing data

With the recorded order and the stored answer, "how often did this annotator
pick whatever was first" is a one-line computation:

```python
from potato.server_utils.presentation_order import position_of

order = user_state.get_presentation_order(instance_id)["tone"]
position_of(order, chosen_label)   # 0 means they picked the first option
```

---

## Related

- [Agreement Over Time](agreement_drift.md) — the other way an agreement number
  can be confidently wrong
- [Behavioral Tracking](behavioral_tracking.md) — where the order is stored
- [Judge Calibration](../ai-intelligence/judge_calibration.md)
