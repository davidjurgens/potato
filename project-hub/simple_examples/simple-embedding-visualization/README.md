# Embedding Visualization Demo

This example demonstrates the **Embedding Visualization** feature in the Potato admin dashboard. It includes pre-annotated synthetic data to show how label coloring and clustering works.

## Features Demonstrated

- **UMAP 2D Projection**: Text embeddings projected to 2D space using UMAP
- **Label Coloring**: Points colored by majority vote sentiment labels
- **Clustering**: Similar texts (positive, negative, neutral) cluster together
- **Interactive Selection**: Lasso/box selection for prioritizing annotation
- **Preview on Hover**: See instance text when hovering over points

## Quick Start

### 1. Install Dependencies

```bash
pip install umap-learn>=0.5.0 sentence-transformers
```

### 2. Start the Server

From the repository root:

```bash
python potato/flask_server.py start project-hub/simple_examples/simple-embedding-visualization/config.yaml -p 8000
```

### 3. Access the Admin Dashboard

1. Navigate to: http://localhost:8000/admin
2. Enter the admin API key: `demo-admin-key-12345`
3. Click the **"Embeddings"** tab

### 4. Explore the Visualization

- **Wait for loading**: UMAP projection takes a few seconds on first load
- **View clusters**: Notice how positive, negative, and neutral texts group together
- **Hover for preview**: Move mouse over points to see text in the preview panel
- **Select points**: Use lasso or box select tools to select regions
- **Add to queue**: Click "Add to Queue" to prioritize selected items
- **Apply reordering**: Click "Apply Reordering" to update the annotation queue

## Dataset

The dataset contains 52 synthetic product/service reviews:

| Category | Positive | Negative | Neutral |
|----------|----------|----------|---------|
| General  | 10       | 10       | 10      |
| Food     | 3        | 3        | 2       |
| Tech     | 3        | 3        | 2       |
| Travel   | 2        | 2        | 2       |

### Pre-populated Annotations

Three simulated annotators have already labeled ~30 items each:
- **annotator1**: 30 annotations (10 pos, 10 neg, 10 neutral)
- **annotator2**: 37 annotations with some disagreement
- **annotator3**: 25 annotations

This creates a realistic scenario where:
- Some items have majority vote labels (colored points)
- Some items are unannotated (gray points)
- You can see annotation coverage at a glance

## Configuration Highlights

```yaml
# Required for embedding visualization
diversity_ordering:
  enabled: true
  model_name: "all-MiniLM-L6-v2"
  num_clusters: 5

# Visualization settings
embedding_visualization:
  enabled: true
  sample_size: 1000
  label_source: "majority"  # or "mace"
  umap:
    n_neighbors: 15
    min_dist: 0.1
    metric: "cosine"
```

## Testing the Reordering Feature

1. Use lasso tool to select a cluster of unannotated (gray) points
2. Click "Add to Queue" (Priority 1)
3. Select another cluster
4. Click "Add to Queue" (Priority 2)
5. Click "Apply Reordering"
6. Go to the annotation interface to verify the new order

## Troubleshooting

### "Embedding visualization not enabled"
- Ensure `umap-learn` is installed: `pip install umap-learn>=0.5.0`

### Visualization is slow
- First load computes UMAP projection (takes 5-10 seconds)
- Subsequent loads use cached projection

### No colored points
- Ensure the pre-populated annotations are in `annotation_output/`
- Check that `label_source` is set to "majority"

## Related Documentation

- [Embedding Visualization Guide](../../../docs/embedding_visualization.md)
- [Diversity Ordering](../../../docs/diversity_ordering.md)
