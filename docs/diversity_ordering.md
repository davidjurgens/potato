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

## Example Project

A complete working example is available at `examples/advanced/diversity-test/`.

### Running the Example

```bash
# From the repository root
python potato/flask_server.py start examples/advanced/diversity-test/config.yaml -p 8000
```

### Example Configuration

The example includes:
- 100 items across 5 themes (Sports, Technology, Food, Travel, Health)
- 20 items per theme
- 5 clusters (matching the 5 themes)
- Radio button annotation with keyboard shortcuts (1-5)

```yaml
annotation_task_name: "Diversity Ordering Test (100 items, 5 themes)"

assignment_strategy: diversity_clustering

diversity_ordering:
  enabled: true
  model_name: "all-MiniLM-L6-v2"
  num_clusters: 5
  auto_clusters: false
  prefill_count: 100
  batch_size: 16
  recluster_threshold: 1.0
  preserve_visited: true

annotation_schemes:
  - annotation_type: radio
    name: topic
    description: "What is the main topic of this text?"
    labels:
      - name: Sports
        tooltip: "Content about athletic competitions, teams, or players"
      - name: Technology
        tooltip: "Content about computers, software, gadgets, or tech companies"
      - name: Food
        tooltip: "Content about cooking, restaurants, or culinary topics"
      - name: Travel
        tooltip: "Content about destinations, tourism, or journeys"
      - name: Health
        tooltip: "Content about medicine, fitness, or wellness"
```

### Verifying Diversity Ordering

When testing the example:

1. **Startup logs**: Look for embedding computation progress:
   ```
   Prefilling 100 embeddings for diversity ordering...
   Computing embeddings: 100%|████████| 100/100
   Clustered 100 items into 5 clusters
   ```

2. **Item variety**: As you annotate, items should come from different clusters:
   - First item might be about Sports
   - Second item about Technology
   - Third item about Food
   - And so on, rotating through clusters

3. **Order preservation**: Navigate back to previous items - they should stay in their original positions

4. **Re-clustering**: After sampling from all 5 clusters, the server logs will show:
   ```
   Reclustering for user: <username>
   ```

## Keyboard Shortcuts

The annotation interface supports keyboard shortcuts for efficient annotation:

### Navigation
- **Left Arrow** or **A**: Go to previous item
- **Right Arrow** or **D**: Go to next item

### Radio Button Selection
- **Number keys 1-9**: Select the corresponding radio option
  - For a schema with 5 labels, keys 1-5 select each option
  - The shortcut is shown in brackets: `Sports [1]`, `Technology [2]`, etc.

### Tips for Fast Annotation
1. Use number keys to select options (no mouse needed)
2. Press Right Arrow to advance to the next item
3. The system automatically saves annotations when you navigate

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

## Testing

### Unit Tests

```bash
# Run diversity manager unit tests
pytest tests/unit/test_diversity_manager.py -v
```

### Integration Tests

```bash
# Run diversity ordering integration tests
pytest tests/server/test_diversity_ordering.py -v
```

### Selenium Tests

```bash
# Run browser-based UI tests
pytest tests/selenium/test_diversity_ordering_ui.py -v
```

The test suite covers:
- Configuration loading and validation
- Embedding computation and caching
- Cluster formation and round-robin sampling
- Order preservation for annotated items
- Multi-user concurrent access
- UI navigation and annotation flow

## Related Documentation

- [Task Assignment Strategies](task_assignment.md) - Other assignment strategies
- [AI Support](ai_support.md) - AI label suggestions that integrate with diversity ordering
- [Active Learning Guide](active_learning_guide.md) - ML-based prioritization
