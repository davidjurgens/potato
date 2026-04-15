# Best-Worst Scaling (BWS)

Best-Worst Scaling (also called MaxDiff) is an annotation method where annotators select the **best** and **worst** items from a set of K items (typically 4). This produces more reliable rankings than direct rating scales and is widely used in NLP for tasks like sentiment intensity measurement, word similarity, and semantic evaluation.

## Overview

Potato's BWS implementation:

1. **Loads individual items** from your data file (one item per row)
2. **Generates tuples** by randomly sampling K items per tuple
3. **Presents tuples** to annotators who select the best and worst items
4. **Computes scores** using counting, Bradley-Terry, or Plackett-Luce methods

## Quick Start

```bash
python potato/flask_server.py start examples/classification/best-worst-scaling/config.yaml -p 8000
```

## Configuration

### Data File

Each row is a single item with an ID and text:

```jsonl
{"id": "s001", "text": "I absolutely love this product!"}
{"id": "s002", "text": "It's okay, nothing special."}
{"id": "s003", "text": "Terrible experience, would not recommend."}
```

### Config YAML

```yaml
annotation_task_name: "Sentiment Intensity BWS"
task_dir: .

data_files:
  - data/sentiment_pool.jsonl

output_annotation_dir: annotation_output/bws/

item_properties:
  id_key: id
  text_key: text

# BWS tuple generation
bws_config:
  tuple_size: 4              # Items per tuple (2-26)
  num_tuples: null            # Auto-calculate if null
  seed: 42                    # Random seed
  min_item_appearances: 8     # Minimum appearances per item across tuples
  scoring:
    method: counting          # counting | bradley_terry | plackett_luce

# Annotation schema
annotation_schemes:
  - annotation_type: bws
    name: sentiment_bws
    description: "Sentiment Intensity"
    best_description: "Which sentence expresses the MOST positive sentiment?"
    worst_description: "Which sentence expresses the LEAST positive sentiment?"
    tuple_size: 4
    sequential_key_binding: true

user_config:
  allow_all_users: true
```

### BWS Config Options

| Option | Default | Description |
|--------|---------|-------------|
| `tuple_size` | 4 | Number of items per tuple. Must be >= 2. |
| `num_tuples` | auto | Number of tuples to generate. If null, auto-calculated. |
| `seed` | 42 | Random seed for reproducible tuple generation. |
| `min_item_appearances` | `2 * tuple_size` | Minimum times each item appears across tuples. Used for auto-calculation. |
| `scoring.method` | `counting` | Default scoring method: `counting`, `bradley_terry`, or `plackett_luce`. |

### Schema Options

| Option | Default | Description |
|--------|---------|-------------|
| `best_description` | "Which is BEST?" | Question text for best selection. |
| `worst_description` | "Which is WORST?" | Question text for worst selection. |
| `tuple_size` | 4 | Must match `bws_config.tuple_size`. |
| `sequential_key_binding` | true | Enable keyboard shortcuts (1-9 for best, a-z for worst). |

## Tuple Generation

### How Tuples Are Generated

Items are sampled **without replacement within each tuple** (no duplicates in a single tuple) but **with replacement across tuples** (items appear in multiple tuples). This follows standard BWS methodology.

### Auto-Calculation Formula

When `num_tuples` is null, the number of tuples is calculated as:

```
num_tuples = ceil(pool_size * min_item_appearances / tuple_size)
```

With defaults (`min_item_appearances = 2 * tuple_size`):

| Pool Size | Tuple Size | Tuples Generated |
|-----------|-----------|-----------------|
| 20 | 4 | 40 |
| 50 | 4 | 100 |
| 100 | 4 | 200 |
| 100 | 5 | 200 |

### Controlling Annotator Overlap

**Shared tuples** — all annotators see the same tuples:

```yaml
assignment_strategy:
  name: fixed_order
max_annotations_per_item: -1
```

**Unique tuples** — different annotators see different subsets:

```yaml
bws_config:
  num_tuples: 200    # Generate more tuples
assignment_strategy:
  name: random
max_annotations_per_item: 1
```

## Scoring Methods

### 1. Counting (Default)

```
score(item) = (best_count - worst_count) / appearance_count
```

- Range: [-1, 1]
- No dependencies required
- Simple, transparent, and deterministic
- Standard baseline in BWS literature

### 2. Bradley-Terry

Converts each BWS annotation to pairwise comparisons:
- Best item beats every other item (K-1 comparisons per annotation)
- Every item beats the worst item (K-1 comparisons per annotation)

Fits a Bradley-Terry model via `choix.ilsr_pairwise()`. Produces log-scale strength parameters.

**Requires:** `pip install choix`

### 3. Plackett-Luce

Converts BWS to partial rankings:
- [best] > [middle items] > [worst]

Fits a Plackett-Luce model. Most statistically sophisticated option.

**Requires:** `pip install choix`

## Scoring via CLI

```bash
# Counting method (no dependencies)
python -m potato.bws_scoring --config config.yaml --method counting

# Bradley-Terry (requires choix)
python -m potato.bws_scoring --config config.yaml --method bradley_terry

# Custom output path
python -m potato.bws_scoring --config config.yaml --method counting --output scores.tsv
```

### Output Format

The output file (`bws_scores.tsv`) contains:

```
item_id	text	score	best_count	worst_count	appearances	rank
s006	Amazing quality and great...	0.875000	7	0	8	1
s001	I absolutely love this...	0.625000	6	1	8	2
```

## Scoring via Admin Dashboard

When BWS is configured, the admin dashboard shows a **BWS Scoring** tab with:

1. Summary statistics (total items, annotations, method)
2. A "Generate Scores" button
3. Method selector (counting / Bradley-Terry / Plackett-Luce)
4. Results table with item scores, ranks, and counts

Clicking "Generate Scores" computes scores and writes `bws_scores.tsv` to the output directory.

## Keyboard Shortcuts

When `sequential_key_binding: true`:

| Key | Action |
|-----|--------|
| `1` | Select item A as best |
| `2` | Select item B as best |
| `3` | Select item C as best |
| `4` | Select item D as best |
| `a` | Select item A as worst |
| `b` | Select item B as worst |
| `c` | Select item C as worst |
| `d` | Select item D as worst |

## Annotation Storage

BWS annotations are stored using Potato's standard label model:

```json
{
  "sentiment_bws": {
    "best": "B",
    "worst": "D"
  }
}
```

Where "B" and "D" are position labels corresponding to items in the tuple.

## Related Documentation

- [Configuration Reference](../../configuration/configuration.md)
- [Schemas and Templates](../schemas_and_templates.md)
- [Admin Dashboard](../../administration/admin_dashboard.md)
