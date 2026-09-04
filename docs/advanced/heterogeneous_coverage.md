# Heterogeneous Annotator Coverage

By default Potato assigns the same number of annotators to every item.
For most NLP projects, the right design is the textbook recipe:

> One annotator handles most items, with two or three annotators overlapping
> on a 5 to 10 percent sample to monitor quality.

That design, and several related ones, are expressed through the
`num_annotators_per_item` and `per_annotator_quota` config blocks.

## The canonical config key

`num_annotators_per_item` is the canonical key for setting per-item annotator
caps. It accepts either:

1. **An integer** &mdash; the same cap for every item:

   ```yaml
   num_annotators_per_item: 1
   ```

2. **A structured mapping** &mdash; a default, an overlap sample, and an
   optional adaptive boost:

   ```yaml
   num_annotators_per_item:
     default: 1
     overlap_sample:
       fraction: 0.1
       count: 3
       stratify_by: domain
       seed: 42
     adaptive:
       enabled: true
       disagreement_threshold: 0.5
       boost_to: 3
     min: 1
   ```

`max_annotations_per_item` is now a deprecated alias for
`num_annotators_per_item: <int>`. Setting both is an error if they disagree;
otherwise the legacy key emits a `DeprecationWarning`.

## Overlap sample

The `overlap_sample` block lets you raise the cap on a deterministic subset
of items for quality monitoring. Sampling happens once at startup; the
chosen items are stamped with `required_annotations: <count>` so the
assignment logic transparently treats them as high-coverage.

| Field | Type | Description |
|---|---|---|
| `fraction` | float in (0, 1] | proportion of items to sample |
| `count` | int >= 2 | annotator cap for sampled items (must exceed `default`) |
| `stratify_by` | string (optional) | item-data field used to stratify the sample |
| `seed` | int (optional) | RNG seed; defaults to the global `random_seed` |

When `stratify_by` is set, the fraction is applied **per stratum**, so every
category contributes proportionally to the overlap sample.

## Adaptive boost

Adaptive boost expands the cap on an item whose early annotators disagreed.
When `register_annotator` records an annotation:

1. If `adaptive.enabled` is true, the item already has at least 2 annotations,
   and its current cap is less than `boost_to`,
2. The disagreement score (ratio of distinct labels per schema across the
   item's annotators, max over schemas) is recomputed,
3. If the score crosses `disagreement_threshold`, the item's cap is raised
   to `boost_to`, the item is removed from `completed_instance_ids`, and it
   re-enters the assignment queue.

The boost is one-shot per item.

## Per-annotator quota

`per_annotator_quota` controls *how many items each annotator gets assigned*
&mdash; orthogonal to per-item caps. It resolves a quota for each user in
order:

```yaml
per_annotator_quota:
  default: 100
  by_user:
    alice: 30
    bob: 30
  by_user_role:
    expert: 30
    novice: 200

user_roles:
  alice: expert
  bob: expert
  carol: novice
  dave: novice
```

Resolution: `by_user[uid]` → `by_user_role[user_roles[uid]]` →
`default` → legacy `max_annotations_per_user`.

## Adjudication auto-routing

When the adjudication block is enabled, overlap-sample items that reach their
cap are automatically scored and pushed into the adjudication queue if
agreement is below `adjudication.agreement_threshold`. This means low-quality
items surface *as soon as* the sample saturates, not when an adjudicator
manually rebuilds the queue.

```yaml
adjudication:
  enabled: true
  adjudicator_users: [admin]
  min_annotations: 2
  agreement_threshold: 0.75
```

## Inspecting IAA

Once overlap-sample items saturate, agreement statistics are available at
`/admin/iaa`. The view computes the metric set appropriate to each schema's
`annotation_type`:

| Schema kind | Metrics |
|---|---|
| nominal (radio, single-label multiselect, triage) | percent agreement, Cohen's κ, Fleiss' κ, Krippendorff's α (nominal) |
| ordinal (likert, confidence, semantic_differential, range_slider, VAS) | weighted κ (linear, quadratic), Spearman's ρ, Krippendorff's α (ordinal) |
| continuous (slider, number) | Pearson r, MAE, RMSE, Krippendorff's α (interval), ICC(2,k) |
| matrix (multirate, constant_sum, soft_label, bws, multi-dimension pairwise) | the nominal, ordinal or continuous set above, once per sub-answer and once pooled |
| multi-label (multiselect, hierarchical_multiselect, card_sort) | mean Jaccard, MASI-α |
| ranking (ranking) | Kendall's τ, Spearman footrule |
| span (span, error_span, event_annotation, coreference, extractive_qa) | token-level κ (BIO), span F1 (exact + partial), Krippendorff's α<sub>U</sub>, γ (Mathet) |
| geometry (image_annotation) | mean agreement, mean matched IoU, detection F1, mean object count difference |
| temporal (audio_annotation, video_annotation) | mean agreement, mean matched IoU (temporal), detection F1, mean segment count difference |

An item is scored only once it reaches its **full** cap, not as soon as it has
two annotators, because a partly-annotated item's agreement moves as the rest
arrive. With `num_annotators_per_item: 3` and two annotators finished, every
schema reports null.

That output used to be identical to a study nobody had touched. The report now
carries `n_items_below_cap`, counting items with two or more annotators that
are still short, and `/admin/iaa` says so above the tables — so "not yet" and
"nothing" are legible apart.

### Schemas that hold several answers at once

A `multirate` asks N questions on one scale; `constant_sum` and `soft_label`
spread a quantity over N options. The unit a reader cares about is the
sub-answer, so each row is scored on its own and then pooled:

```json
"handling": {
  "kind": "matrix",
  "metrics": {
    "Reproducibility": {"alpha_ordinal": 1.0,   "n_items": 4},
    "Customer tone":   {"alpha_ordinal": 0.774, "n_items": 4},
    "Urgency":         {"alpha_ordinal": 0.741, "n_items": 4},
    "pooled":          {"alpha_ordinal": 0.820, "n_items": 12},
    "n_rows": 3, "scale": "ordinal"
  }
}
```

`pooled` is the headline, and its unit is the (item, row) pair — four items
rated on three rows is twelve judgements, not four. It is the number ten
separate likert schemes would have given you. The per-row numbers are the
reason to prefer the compact widget: "they agree about urgency and not about
tone" is the finding, and a pooled 0.4 hides it.

`scale` says which set was used. It is read from the stored values rather than
the declared type, because a multirate over `[Low, Medium, High]` is ordinal
over label names while `constant_sum` stores points.

`bws` and a `multi_dimension` pairwise are the same shape with a third scale.
BWS stores a best and a worst pick; multi-dimension pairwise stores one pick per
dimension. Both hold item names, which have no order, so they are scored as
`nominal` per sub-answer. Reporting them as a ranking, which is what Potato did
before v2.8.3, put a weighted κ on categories where a two-step disagreement does
not exist.

### Schema types that store the answer in the value

Most schema types put the answer in the *key*: a radio stores
`{"positive": true}` and a likert stores `{"5": "5"}`, so the option's name is
what was chosen. A handful invert that and store one fixed key whose value
carries the whole answer:

| Type | Stored as |
|---|---|
| `hierarchical_multiselect` | `{"selected_labels": "Annotation,People,Experts"}` |
| `ranking` | `{"rank_order": "Cost,Agreement,Accuracy"}` |
| `card_sort` | `{"<schema>": "{\"Group A\": [\"card1\"]}"}` |
| `conjoint` | `{"<schema>": "2"}` |
| `pairwise` (binary) | `{"selection": "A"}` |
| `pairwise` (scale) | `{"scale_value": "-2"}` |

Before v2.8.3 the agreement code read all of these the first way, which returned
the key name for every annotator on every item. A taxonomy study reported a
perfect mean Jaccard of 1.0 no matter what anyone selected, because every set
gathered as `{"selected_labels"}`. Recompute any of these against a current
build; the earlier numbers do not describe your data.

A `card_sort` is compared as the set of (group, card) placements rather than the
set of group names. Every annotator sees the same groups, so group names would
agree perfectly by construction.

### Ordering a scale of word labels

Every ordinal measure needs to know that `Serious` sits between `Minor` and
`Critical`. Potato takes that from the schema's own `labels` list, so write the
scale in order:

```yaml
- annotation_type: likert
  name: severity
  labels: [Trivial, Minor, Serious, Critical, Blocker]
```

Without a `labels` block the label names are sorted instead, which is only
right when they sort into their own order — `[Low, Medium, High]` sorts to
High &lt; Low &lt; Medium, and a one-step disagreement is then scored as a
two-step one.

### Agreement over drawn and timed annotations

Boxes, polygons, masks, points, and audio/video segments are compared by
**overlap**, not equality — two annotators never produce byte-identical
geometry. Objects are paired across annotators with the Hungarian algorithm at a
0.5 IoU threshold (the Pascal VOC / COCO detection convention), and four numbers
are reported because annotators disagree in distinguishable ways:

| Metric | Question it answers |
|---|---|
| `mean_agreement` | Overall, penalizing both sloppy boundaries and missed objects. This is the number adjudication routes on. |
| `mean_matched_iou` | *Given* both annotators found the object, do they agree where it is? |
| `detection_f1` | Did they find the same objects at all? |
| `mean_object_count_diff` | The crudest signal, and often the first to move. |

Reading them together is the point. High `mean_matched_iou` with low
`detection_f1` means your annotators draw well but miss things — a coverage
problem, fixed with better instructions. The reverse means they find everything
but trace it carelessly — a precision problem, fixed with training.

An item where **both** annotators marked nothing is counted, not scored. It
appears as `n_empty_pairs` beside `n_scored_pairs`, and the four measures are
computed over the scored pairs alone — the same convention COCO-style AP uses
for an image with no ground truth and no predictions. Two blank answers are not
evidence of agreement, and treating them as a perfect pair gave a task where
nobody drew anything a `detection_f1` of 1.0. When nothing was scored at all,
the measures read `n/a` with a note saying why.

!!! note "Why not Krippendorff's α over IoU?"

    Because IoU distance is bounded in [0, 1], randomly paired shapes saturate
    at distance ≈ 1, expected disagreement collapses to ≈ 1, and α degenerates
    to `1 − mean distance` — the chance correction does no work. Worse, it
    misleads: Braylan, Alonso & Lease
    ([WWW 2022](https://arxiv.org/abs/2212.09503)) measured α ranking L2 (0.687)
    *above* IoU (0.505) and GIoU (0.507) on bounding boxes, inverting the
    ordering their distribution-based measures give. α remains sound for
    detection and classification agreement, where a real base rate exists.

Free-text schemas are **omitted** from the report rather than scored. Absent is
honest; a number would not be.

Set `?format=html` for the rendered table:

```
GET /admin/iaa?format=html
X-API-Key: <your admin api key>
```

The HTML view colors metrics by interpretive convention (≥0.6 green, &lt;0.2
red for κ-family scores) and lists per-item annotator counts beneath the
schema tables.

## Example

A runnable demonstration lives at
`examples/advanced/heterogeneous-coverage/`. From the repo root:

```bash
python potato/flask_server.py start examples/advanced/heterogeneous-coverage/config.yaml -p 8000
```

The example uses 20 items split across two domains (`product`, `movie`),
samples 20% for 3-annotator overlap stratified by domain, enables adaptive
boost at threshold 0.5, defines two expertise tiers, and pipes
low-agreement overlap items into adjudication.

## Related

- [Task Assignment](task_assignment.md) &mdash; assignment strategies
- [Adjudication](../administration/adjudication.md) &mdash; the adjudication queue this feature feeds
- [Quality Control](../workflow/quality_control.md) &mdash; gold standards and attention checks
