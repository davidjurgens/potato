# Ranking / Drag-and-Drop

The ranking schema lets annotators reorder a list of items by dragging them into their preferred sequence. Unlike Best-Worst Scaling which samples from a pool, ranking presents all candidate items simultaneously and elicits a complete ordering. This is suitable when the full item set is small enough to compare holistically (typically 3–8 items).

## Overview

Annotators see a vertical list of items with drag handles. They reorder the list from best (top) to worst (bottom) by dragging items to their desired position. Optionally, items at equal rank can be grouped as ties.

Key differences from Best-Worst Scaling:

| Feature | Ranking | BWS |
|---------|---------|-----|
| Items per annotation | All at once | Subset (tuple) |
| Suitable pool size | 3–8 items | Any size |
| Ties allowed | Optional | No |
| Output | Complete order | Best/worst pair |
| Annotation effort | Higher | Lower |

## Research Basis

- Kiritchenko, S., & Mohammad, S. M. (2017). "Best-Worst Scaling More Reliable than Rating Scales: A Case Study on Sentiment Intensity Annotation." *ACL 2017*. Compares full ranking, BWS, and rating scales; full ranking is reliable for small item sets but does not scale to large pools.
- Thurstone, L. L. (1927). "A Law of Comparative Judgment." *Psychological Review 34*(4). Foundational comparative judgment theory underlying ranking and paired comparison methods.

## Configuration

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_type` | — | Must be `ranking` |
| `name` | — | Schema identifier (required) |
| `description` | — | Task instruction |
| `labels` | — | List of item names to rank (required, minimum 2) |
| `allow_ties` | `false` | Allow annotators to place items at equal rank |
| `items_key` | `null` | Data field containing dynamic items (overrides `labels`) |
| `sequential_key_binding` | `false` | Enable keyboard shortcut reordering |
| `label_requirement.required` | `false` | Require a complete ranking before proceeding |

### YAML Example — Static Item List

```yaml
annotation_schemes:
  - annotation_type: ranking
    name: response_quality
    description: "Drag the responses to rank them from best (top) to worst (bottom)."
    allow_ties: false
    labels:
      - Response A
      - Response B
      - Response C
      - Response D
    label_requirement:
      required: true
```

### YAML Example — Dynamic Items from Data

When the items to rank come from the instance data (different items per row):

```yaml
annotation_schemes:
  - annotation_type: ranking
    name: translation_rank
    description: "Rank these machine translations from most to least fluent."
    items_key: translations
    allow_ties: true
```

With corresponding data:

```json
{"id": "t001", "source": "The cat sat on the mat.", "translations": ["Le chat était assis sur le tapis.", "Le chat s'est assis sur le tapis.", "Chat sur tapis."]}
```

### Ties Configuration

```yaml
annotation_schemes:
  - annotation_type: ranking
    name: summary_quality
    description: "Rank these summaries. Use the tie button to group equally good summaries."
    allow_ties: true
    labels:
      - Summary A
      - Summary B
      - Summary C
```

## Output Format

The final rank order is stored as a comma-separated string of item identifiers, from rank 1 (best) to rank N (worst):

```json
{
  "response_quality": {
    "rank_order": "B,D,A,C"
  }
}
```

When ties are enabled, tied items are grouped with a `=` separator:

```json
{
  "response_quality": {
    "rank_order": "B,D=A,C"
  }
}
```

This means B is ranked 1st, D and A are tied at 2nd, and C is ranked 4th.

## Use Cases

- **LLM response evaluation** — rank multiple model outputs for quality, relevance, or safety
- **Translation ranking** — order machine translation hypotheses by fluency or adequacy
- **Summarization evaluation** — rank document summaries by informativeness or conciseness
- **Argument strength** — order arguments from most to least persuasive
- **Search result relevance** — annotate the relevance ranking of retrieved documents
- **RLHF preference data** — collect full rankings as richer training signal than pairwise

## Troubleshooting

**Annotators find full ranking of 6+ items tiring:** Consider switching to Best-Worst Scaling for large item pools. BWS achieves similar statistical efficiency with much lower per-item cognitive load.

**Dynamic items from data have different lengths per instance:** Use `items_key` with `allow_ties: false` and ensure your data preprocessing produces consistent list lengths if downstream analysis requires it.

## Related Documentation

- [Best-Worst Scaling](bws.md) — scalable comparative annotation for large item pools
- [Pairwise Comparison](pairwise_annotation.md) — head-to-head comparison of two items
- [Iterative BWS](iterative_bws.md) — adaptive BWS for fine-grained ordinal rankings
- [Schema Gallery](../schemas_and_templates.md) — all annotation types with examples
