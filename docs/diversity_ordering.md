# Diversity-Based Item Ordering

Maximize annotation variety by presenting items from different topic clusters.

## Overview

Diversity ordering uses sentence-transformer embeddings to cluster similar items together, then samples items round-robin from different clusters. This ensures annotators see diverse content rather than similar items in sequence, which can:

- **Reduce annotator fatigue** from repetitive content
- **Improve annotation quality** through varied context
- **Faster coverage** of the full topic space

## Quick Start

```yaml
# In your config.yaml
assignment_strategy: diversity_clustering

diversity_ordering:
  enabled: true
  prefill_count: 100
```

## How It Works

1. **Startup**: First N items are embedded using sentence-transformers and clustered with k-means
2. **Assignment**: Items are sampled round-robin from clusters, ensuring variety
3. **Annotation**: New items are embedded asynchronously as they're annotated
4. **Re-clustering**: When a user has sampled from all clusters, the system reclusters

### Visual Example

Without diversity ordering:
```
Item 1: Sports article
Item 2: Sports article
Item 3: Sports article  <- Annotator sees 3 similar items in a row
Item 4: Tech article
Item 5: Tech article
...
```

With diversity ordering:
```
Item 1: Sports article
Item 2: Tech article     <- From different cluster
Item 3: Travel article   <- From different cluster
Item 4: Food article     <- From different cluster
Item 5: Sports article   <- Back to sports, but after seeing variety
...
```

## Configuration Options

```yaml
diversity_ordering:
  # Enable diversity ordering
  enabled: true

  # Sentence-transformer model (default: all-MiniLM-L6-v2)
  # Options: all-MiniLM-L6-v2, paraphrase-MiniLM-L6-v2, etc.
  model_name: "all-MiniLM-L6-v2"

  # Clustering parameters
  num_clusters: 10              # Fixed cluster count (if auto_clusters=false)
  items_per_cluster: 20         # Target size (for auto_clusters=true)
  auto_clusters: true           # Auto-calculate based on data size

  # Prefill on startup (embeddings computed with progress bar)
  prefill_count: 100            # Items to embed at server start
  batch_size: 32                # Batch size for computation

  # Re-clustering behavior
  # When this fraction of clusters have been sampled, recluster
  recluster_threshold: 1.0      # 1.0 = recluster when all clusters sampled

  # Order preservation
  # Keep annotated and skipped items in their positions
  preserve_visited: true

  # AI integration
  # Trigger AI cache prefetch after reordering
  trigger_ai_prefetch: true

  # Cache location (optional override)
  cache_dir: null               # Uses output_annotation_dir/.diversity_cache
```

## Configuration Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | false | Enable diversity ordering |
| `model_name` | string | "all-MiniLM-L6-v2" | Sentence-transformers model |
| `num_clusters` | int | 10 | Number of clusters (when auto_clusters=false) |
| `items_per_cluster` | int | 20 | Target cluster size (when auto_clusters=true) |
| `auto_clusters` | bool | true | Automatically calculate cluster count |
| `prefill_count` | int | 100 | Items to embed at startup |
| `batch_size` | int | 32 | Batch size for embedding computation |
| `recluster_threshold` | float | 1.0 | Fraction of clusters to sample before reclustering |
| `preserve_visited` | bool | true | Keep visited/skipped items in place |
| `trigger_ai_prefetch` | bool | true | Trigger AI cache after reordering |
| `cache_dir` | string | null | Custom cache directory |

## Requirements

Install the required dependencies:

```bash
pip install sentence-transformers scikit-learn
```

These are optional dependencies that enable the diversity ordering feature. Without them, the feature will be disabled and a warning will be logged.

## Interaction with Other Features

### AI Support

When `trigger_ai_prefetch: true`, the system will automatically prefetch AI hints for reordered items. This ensures smooth performance even when items are reordered mid-session.

### Active Learning

Diversity ordering can be combined with active learning by using:
1. `diversity_clustering` for initial diverse coverage
2. Switching to `active_learning` after sufficient annotations

### Order Preservation

When `preserve_visited: true`, items the user has already seen (even if they skipped them) maintain their position. This prevents confusion when navigating back through previously viewed items.

## Performance Considerations

### Startup Time

The first startup will compute embeddings for `prefill_count` items. This typically takes:
- ~10 seconds for 100 items with all-MiniLM-L6-v2
- ~30 seconds for 500 items

Subsequent startups load from cache and are nearly instant.

### Memory Usage

Embeddings are stored in memory:
- all-MiniLM-L6-v2: 384 dimensions * 4 bytes = ~1.5 KB per item
- 10,000 items: ~15 MB

### Disk Cache

Embeddings are persisted to disk in `.diversity_cache/`:
- `embeddings.pkl`: Numpy arrays (pickle format)
- `cluster_labels.json`: Cluster assignments

## Troubleshooting

### "sentence-transformers not installed"

```
WARNING: Diversity ordering requested but manager not enabled.
Install sentence-transformers and scikit-learn
```

**Solution**: Install dependencies:
```bash
pip install sentence-transformers scikit-learn
```

### Slow startup with many items

**Solution**: Reduce `prefill_count` to compute fewer embeddings at startup. Remaining items will be embedded asynchronously as they're accessed.

### Items not diverse enough

**Solution**: Try:
1. Increasing `num_clusters` or decreasing `items_per_cluster`
2. Using a different embedding model
3. Checking that your data actually has diverse content

### Memory errors with large datasets

**Solution**:
1. Reduce `prefill_count`
2. Increase `batch_size` slightly for better GPU utilization
3. Use a smaller embedding model

## Example Projects

See `project-hub/simple_examples/simple-diversity/` for a complete working example.

## API Reference

### DiversityManager Methods

```python
from potato.diversity_manager import get_diversity_manager

dm = get_diversity_manager()

# Check if enabled
if dm and dm.enabled:
    # Get statistics
    stats = dm.get_stats()
    print(f"Clusters: {stats['cluster_count']}")
    print(f"Embeddings: {stats['embedding_count']}")

    # Generate diverse ordering for a user
    available_ids = ["item1", "item2", "item3"]
    annotated_ids = {"item1"}  # Already annotated
    diverse_order = dm.apply_to_user_ordering("user1", available_ids, annotated_ids)
```

### Admin Dashboard

The diversity manager statistics are included in the admin dashboard under the "System" section when enabled.
