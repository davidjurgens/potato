# Embedding Dashboard Visualization

The Embedding Visualization feature provides an interactive 2D visualization of your annotation data in the admin dashboard. Using UMAP dimensionality reduction on text embeddings, it allows you to:

- **Explore data patterns**: See clustering and distribution of your instances
- **Track annotation progress**: Visualize annotated vs. unannotated items
- **Prioritize annotation**: Select regions to prioritize for annotation
- **Understand label distribution**: Color points by predicted labels (MACE or majority vote)

## Requirements

The embedding visualization requires the following dependencies:

```bash
# Required dependencies
pip install umap-learn>=0.5.0
pip install sentence-transformers  # Already required for diversity_ordering
pip install scikit-learn  # Already required for diversity_ordering
```

Additionally, **diversity ordering must be enabled** in your configuration, as the visualization uses the embeddings computed by the DiversityManager.

## Configuration

Add the `embedding_visualization` section to your YAML config file:

```yaml
# Required: Enable diversity ordering for embeddings
diversity_ordering:
  enabled: true
  model_name: "all-MiniLM-L6-v2"
  num_clusters: 10

# Optional: Configure embedding visualization
embedding_visualization:
  enabled: true                    # Enable/disable visualization (default: true)
  sample_size: 1000               # Max instances to visualize (default: 1000)
  include_all_annotated: true     # Always include annotated items (default: true)
  embedding_model: "all-MiniLM-L6-v2"  # Text embedding model
  label_source: "mace"            # "mace" or "majority" (default: "mace")

  umap:                           # UMAP projection settings
    n_neighbors: 15               # Number of neighbors (default: 15)
    min_dist: 0.1                 # Minimum distance (default: 0.1)
    metric: "cosine"              # Distance metric (default: "cosine")
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `true` | Enable/disable the visualization |
| `sample_size` | int | 1000 | Maximum instances to visualize (for performance) |
| `include_all_annotated` | bool | `true` | Always include all annotated instances in the sample |
| `embedding_model` | string | "all-MiniLM-L6-v2" | Sentence-transformer model for text |
| `label_source` | string | "mace" | Label source: "mace" (MACE predictions) or "majority" (majority vote) |
| `umap.n_neighbors` | int | 15 | UMAP: Number of neighbors to consider |
| `umap.min_dist` | float | 0.1 | UMAP: Minimum distance between points (0-1) |
| `umap.metric` | string | "cosine" | UMAP: Distance metric (cosine, euclidean, manhattan, correlation) |

## Using the Visualization

### Accessing the Dashboard

1. Navigate to the Admin Dashboard (`/admin`)
2. Enter your admin API key (found in your task directory as `admin_api_key.txt` or set in config)
3. Click the **"Embeddings"** tab

### Understanding the Visualization

The scatter plot shows your instances projected into 2D space:

- **Position**: Similar instances appear close together based on their text embeddings
- **Color**: Points are colored by their predicted label
  - If using MACE: Colors reflect MACE's best prediction
  - If using majority vote: Colors reflect the most common annotation
  - Gray points are unannotated
- **Hover**: Hover over a point to see the instance preview in the side panel

### Selection Tools

Use the Plotly.js selection tools to select instances:

1. **Lasso Selection**: Click and drag to draw a free-form selection
2. **Box Selection**: Click and drag to select a rectangular region
3. **Click**: Click individual points to add them to your selection

### Priority Queue

The selection panel allows you to create a priority queue for annotation:

1. **Make a selection** using lasso or box tool
2. **Click "Add to Queue"** to add the selection as a priority group
3. **Repeat** to add multiple priority groups
4. **Click "Apply Reordering"** to reorder the annotation queue

When you apply reordering:
- Selected instances are moved to the front of the annotation queue
- Multiple selections are **interleaved** by priority
- Lower priority numbers come first in each round

### Interleaving Example

If you select two regions:
- Region 1 (Priority 1): `[A, B, C]`
- Region 2 (Priority 2): `[X, Y]`

The resulting order will be: `A, X, B, Y, C`

This ensures diverse annotation coverage even if annotators only complete part of the queue.

## API Endpoints

The visualization is powered by these admin API endpoints:

### GET /admin/api/embedding_viz/data

Returns visualization data including 2D coordinates, labels, and colors.

**Query Parameters:**
- `force_refresh`: If "true", recompute UMAP projection

**Response:**
```json
{
  "points": [
    {
      "instance_id": "item_001",
      "x": 0.234,
      "y": -1.456,
      "label": "Positive",
      "label_source": "mace",
      "preview": "This is the text content...",
      "preview_type": "text",
      "annotated": true,
      "annotation_count": 3
    }
  ],
  "labels": ["Positive", "Negative", "Neutral", null],
  "label_colors": {
    "Positive": "#22c55e",
    "Negative": "#ef4444",
    "Neutral": "#eab308",
    "null": "#94a3b8"
  },
  "stats": {
    "total_instances": 1000,
    "visualized_instances": 500,
    "annotated_instances": 342,
    "unannotated_instances": 658
  }
}
```

### POST /admin/api/embedding_viz/reorder

Reorder the annotation queue based on selections.

**Request Body:**
```json
{
  "selections": [
    {
      "instance_ids": ["item_005", "item_012", "item_023"],
      "priority": 1
    },
    {
      "instance_ids": ["item_101", "item_102"],
      "priority": 2
    }
  ],
  "interleave": true
}
```

**Response:**
```json
{
  "success": true,
  "reordered_count": 5,
  "new_order_preview": ["item_005", "item_101", "item_012", "item_102", "item_023"]
}
```

### POST /admin/api/embedding_viz/refresh

Force re-computation of embeddings and UMAP projection.

**Request Body:**
```json
{
  "force_recompute": true
}
```

### GET /admin/api/embedding_viz/stats

Returns statistics about the embedding visualization system.

**Response:**
```json
{
  "enabled": true,
  "umap_available": true,
  "numpy_available": true,
  "embeddings_available": true,
  "embedding_count": 1000,
  "cache_valid": true,
  "config": {
    "sample_size": 1000,
    "include_all_annotated": true,
    "label_source": "mace",
    "umap_n_neighbors": 15,
    "umap_min_dist": 0.1
  }
}
```

## Performance Considerations

### Large Datasets

For datasets with many instances:

1. **Sampling**: The visualization automatically samples instances based on `sample_size`
2. **Include Annotated**: Setting `include_all_annotated: true` ensures annotated items are always shown
3. **UMAP Parameters**: Lower `n_neighbors` values compute faster but may lose structure

### Caching

- UMAP projections are cached after first computation
- Cache is invalidated when new embeddings are added
- Use the "Refresh" button or `/refresh` endpoint to force recomputation

## Troubleshooting

### "Embedding visualization not enabled"

**Cause**: Missing dependencies or disabled in config.

**Solution**:
```bash
pip install umap-learn>=0.5.0
```

### "Diversity manager not available"

**Cause**: `diversity_ordering` is not enabled in config.

**Solution**: Add to your config:
```yaml
diversity_ordering:
  enabled: true
```

### "No embeddings available"

**Cause**: Embeddings haven't been computed yet.

**Solution**: Embeddings are computed when items are loaded. Ensure your data files are loaded and wait for embedding computation to complete.

### Visualization is slow

**Cause**: Large number of instances or first-time computation.

**Solutions**:
1. Reduce `sample_size` in config
2. Reduce `umap.n_neighbors`
3. Wait for initial computation to complete (subsequent loads use cache)

## Related Documentation

- [Diversity Ordering](diversity_ordering.md) - Required for embeddings
- [MACE Adjudication](mace.md) - Label predictions used for coloring
- [Admin Dashboard](admin_dashboard.md) - Dashboard overview
