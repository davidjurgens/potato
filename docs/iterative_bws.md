# Iterative Best-Worst Scaling (IBWS)

Iterative Best-Worst Scaling extends standard BWS with an adaptive, Quicksort-like loop that produces fine-grained ordinal rankings with O(n log n) comparisons instead of O(n²).

Based on: *"Baby Bear: Seeking a Just Right Rating Scale for Scalar Annotations"* ([arxiv 2408.09765](https://arxiv.org/abs/2408.09765))

## How It Works

Standard BWS generates all tuples upfront and produces relative rankings. IBWS adds rounds:

1. **Round 1**: Generate tuples from the full item pool. Annotators select best/worst from each tuple.
2. **Score & Partition**: Score all items using the chosen method (counting, Bradley-Terry, or Plackett-Luce). Partition items into upper/middle/lower thirds by score.
3. **Round 2**: Generate new tuples *within each bucket*. Items only compete against others in the same bucket, refining the ranking.
4. **Repeat**: Each round splits buckets into 3 sub-buckets. After K rounds, items are sorted into up to 3^K buckets.
5. **Stop**: When all buckets have fewer items than the tuple size (terminal), or `max_rounds` is reached.

The result is an ordinal ranking derived from bucket positions plus within-bucket scores.

## Configuration

Add an `ibws_config` block to your YAML config instead of `bws_config`:

```yaml
ibws_config:
  tuple_size: 4                    # Items per tuple (default: 4)
  max_rounds: null                 # null = auto-stop when all terminal
  seed: 42                         # Random seed for reproducibility
  scoring_method: counting         # counting | bradley_terry | plackett_luce
  tuples_per_item_per_round: 2     # Appearances per item per round

annotation_schemes:
  - annotation_type: bws
    name: sentiment_ibws
    best_description: "Which expresses the MOST positive sentiment?"
    worst_description: "Which expresses the LEAST positive sentiment?"
    tuple_size: 4
    sequential_key_binding: true
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `tuple_size` | int | 4 | Number of items per tuple. Must be >= 2. |
| `max_rounds` | int or null | null | Maximum rounds. `null` = auto-stop when all buckets are terminal. |
| `seed` | int | 42 | Random seed for tuple generation. |
| `scoring_method` | string | "counting" | How to score items between rounds. Options: `counting`, `bradley_terry`, `plackett_luce`. |
| `tuples_per_item_per_round` | int | 2 | Minimum number of tuples each item appears in per round. Higher values = more reliable scores per round but more annotation effort. |

### Important Notes

- `ibws_config` and `bws_config` are **mutually exclusive**. Use one or the other.
- The annotation scheme must use `annotation_type: bws`. IBWS reuses the BWS frontend unchanged.
- `max_annotations_per_user` is automatically set to unlimited when IBWS is active.

## Comparison with Standard BWS

| Feature | Standard BWS | Iterative BWS |
|---------|-------------|---------------|
| Tuple generation | All upfront | Per-round, within buckets |
| Comparisons | O(n²) | O(n log n) |
| Output | Continuous scores | Ordinal ranking (buckets + scores) |
| Rounds | Single | Multiple adaptive rounds |
| User experience | Fixed number of tuples | Tuples appear in waves |

## Running the Example

```bash
python potato/flask_server.py start examples/classification/iterative-bws/config.yaml -p 8000
```

For debug mode (skips login):

```bash
python potato/flask_server.py start examples/classification/iterative-bws/config.yaml -p 8000 --debug --debug-phase annotation
```

## Admin API

### Get Round Status

```
GET /admin/api/ibws_status
```

Returns:

```json
{
  "current_round": 2,
  "max_rounds": null,
  "total_tuples_this_round": 12,
  "active_buckets": 3,
  "terminal_buckets": 2,
  "total_items": 20,
  "terminal_items": 5,
  "completed": false
}
```

### Get Ranking

```
GET /admin/api/ibws_ranking
```

Returns:

```json
{
  "completed": true,
  "current_round": 3,
  "ranking": [
    {"item_id": "s013", "rank": 1, "bucket_position": 0, "text": "I'm in love with this!..."},
    {"item_id": "s001", "rank": 2, "bucket_position": 0, "text": "I absolutely love..."},
    ...
  ]
}
```

## Interpreting Results

- **Bucket position**: Items in earlier buckets (lower index) scored higher in earlier rounds.
- **Rank within bucket**: Ordering within a bucket is based on the most recent scores available.
- **Terminal buckets**: Buckets with fewer items than `tuple_size` that can't be further subdivided. These items are effectively "tied" within their bucket.
- The ranking becomes more granular with each round. With 20 items and tuple_size=4, expect 2-3 rounds.

## Troubleshooting

**Q: Users see "no items to annotate" briefly between rounds.**
A: This shouldn't happen — the system checks for round completion before advancing the user's phase. If it does occur, it means the round completion check is racing with the phase advancement. File a bug.

**Q: Scores seem noisy with few annotations per round.**
A: Increase `tuples_per_item_per_round`. The default of 2 is minimal; 3-4 gives more reliable per-round scores.

**Q: How many rounds will there be?**
A: Roughly log₃(n/tuple_size) rounds, where n is the pool size. For 20 items with tuple_size=4, expect ~2-3 rounds.

## Related Documentation

- [Schemas and Templates](schemas_and_templates.md) — BWS annotation type reference
- [Quality Control](quality_control.md) — attention checks and gold standards
