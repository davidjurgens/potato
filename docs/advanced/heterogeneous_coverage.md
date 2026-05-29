# Heterogeneous Annotator Coverage

By default Potato assigns the same number of annotators to every item.
For most NLP projects, the right design is the textbook recipe:

> One annotator handles most items, with two or three annotators overlapping
> on a 5 to 10 percent sample to monitor quality.

This page explains how to express that and several related patterns through
the `num_annotators_per_item` and `per_annotator_quota` config blocks.

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
| continuous (slider, number, multirate, constant_sum, soft_label) | Pearson r, MAE, RMSE, Krippendorff's α (interval), ICC(2,k) |
| multi-label (multiselect, hierarchical_multiselect, card_sort) | mean Jaccard, MASI-α |
| ranking (ranking, bws, pairwise) | Kendall's τ, Spearman footrule |
| span (span, error_span, event_annotation, coreference, extractive_qa) | token-level κ (BIO), span F1 (exact + partial), Krippendorff's α<sub>U</sub>, γ (Mathet) |

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
