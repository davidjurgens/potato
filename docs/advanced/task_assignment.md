# Task Assignment

Potato provides flexible task assignment strategies to control how annotation instances are distributed to annotators. This guide covers all available strategies and configuration options.

## Table of Contents

1. [Overview](#overview)
2. [Assignment Strategies](#assignment-strategies)
3. [Configuration](#configuration)
4. [Legacy Configuration](#legacy-configuration)
5. [Test Questions](#test-questions)
6. [Examples](#examples)

---

## Overview

Task assignment controls:
- **Which items** each annotator sees
- **How many items** each annotator completes
- **How many annotations** each item receives
- **The order** in which items are presented

### Key Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `assignment_strategy` | Strategy for assigning items | `random` |
| `max_annotations_per_user` | Maximum items per annotator | unlimited |
| `max_annotations_per_item` | Target annotations per item | 3 |

---

## Assignment Strategies

Potato supports eight assignment strategies.

### Fully Implemented Strategies

#### 1. Random Assignment (`random`)

Assigns items randomly to annotators, ensuring unbiased distribution.

```yaml
assignment_strategy: random
max_annotations_per_item: 3
```

**Best for**: General annotation tasks where order doesn't matter.

#### 2. Fixed Order Assignment (`fixed_order`)

Assigns items in the order they appear in the dataset.

```yaml
assignment_strategy: fixed_order
max_annotations_per_item: 2
```

**Best for**: Tasks where annotators should see items in a specific sequence.

#### 3. Least-Annotated Assignment (`least_annotated`)

Prioritizes items with the fewest existing annotations, ensuring even distribution.

```yaml
assignment_strategy: least_annotated
max_annotations_per_item: 5
```

**Best for**: Ensuring all items receive adequate coverage before any item gets excessive annotations.

#### 4. Max-Diversity Assignment (`max_diversity`)

Prioritizes items with the highest disagreement among existing annotations.

```yaml
assignment_strategy: max_diversity
max_annotations_per_item: 4
```

**How it works**: Calculates a disagreement score based on the ratio of unique annotations to total annotations. Higher disagreement items are assigned first.

**Best for**: Quality control and resolving ambiguous items.

#### 5. Diversity Clustering Assignment (`diversity_clustering`)

Uses sentence-transformer embeddings to cluster similar items, then presents items round-robin from different clusters to maximize variety.

```yaml
assignment_strategy: diversity_clustering

diversity_ordering:
  enabled: true
  model_name: "all-MiniLM-L6-v2"
  num_clusters: 10
  prefill_count: 100
  recluster_threshold: 1.0
```

**How it works**:
1. Items are embedded using a sentence-transformer model
2. K-means clustering groups similar items together
3. Items are sampled round-robin from different clusters
4. When all clusters are sampled, reclustering occurs

**Best for**: Tasks where annotator fatigue from similar content is a concern, or when early coverage of the full topic space is important.

See [Diversity Ordering](../workflow/diversity_ordering.md) for full configuration.

#### 6. Batch Assignment (`batch`)

Restricts assignment to explicit annotator/item cohorts. This is intended for
repeat-round study designs where the same annotators who saw a first-round item
batch must receive the corresponding second-round batch.

```yaml
assignment_strategy: batch
num_annotators_per_item: 4

batch_assignment:
  groups:
    - name: round1_batch_a
      annotators: ["u1", "u2", "u3", "u4"]
      instances: ["r2_item_001", "r2_item_002"]
```

For long batches, move the instance list into a separate data file. If the
batch file is already a full Potato input data file, use `data_file`: Potato
will load the items and use the same file to define the group order. This lets
one config point each annotator cohort at a specific input file:

```yaml
assignment_strategy: batch
num_annotators_per_item: 4
data_files: []

batch_assignment:
  groups:
    - name: round1_batch_a
      annotators: ["u1", "u2", "u3", "u4"]
      data_file: batches/round1_batch_a.csv
    - name: round1_batch_b
      annotators: ["u5", "u6", "u7", "u8"]
      data_file: batches/round1_batch_b.csv
```

If the file contains only IDs and the items are loaded through top-level
`data_files`, use `instances_file` instead. `data_file` and `instances_file`
support the same local formats as `data_files` (`json`, `jsonl`, `csv`, `tsv`,
or `parquet`) and IDs are read using `item_properties.id_key`.

When annotator IDs are not known ahead of time, such as a fresh Prolific launch,
enable automatic cohort assignment. Potato assigns each first-arriving user to
the least-filled batch group and keeps that user's group stable for the session.
Group size defaults to `num_annotators_per_item`/`max_annotations_per_item`, or
you can set `max_annotators` per group:

```yaml
assignment_strategy: batch
num_annotators_per_item: 4
data_files: []

batch_assignment:
  auto_assign_annotators: true
  groups:
    - name: batch_a
      data_file: batches/batch_a.csv
    - name: batch_b
      data_file: batches/batch_b.csv
    - name: batch_c
      data_file: batches/batch_c.csv
      max_annotators: 6
```

Items can also define their allowed annotators directly. This is useful when
round-2 data is generated from round-1 annotations:

```yaml
assignment_strategy: batch

batch_assignment:
  annotator_key: round1_annotators
```

```json
{
  "id": "r2_item_001",
  "text": "Round 2 item text",
  "round1_annotators": ["u1", "u2", "u3", "u4"]
}
```

Users outside configured cohorts receive no items under this strategy.

### ML-Based Strategies

#### 7. Active Learning Assignment (`active_learning`)

Uses machine learning to prioritize uncertain instances. Integrates with `ActiveLearningManager` for intelligent reordering.

```yaml
assignment_strategy: active_learning

active_learning:
  enabled: true
  schema_names: ["sentiment"]
  min_annotations_per_instance: 2
  min_instances_for_training: 20
  update_frequency: 10
```

See [Active Learning Guide](../ai-intelligence/active_learning_guide.md) for full configuration.

#### 8. LLM Confidence Assignment (`llm_confidence`)

Uses LLM confidence scores to prioritize items. Currently falls back to random assignment.

```yaml
assignment_strategy: llm_confidence
```

---

## Configuration

### Modern Configuration (Recommended)

```yaml
# Strategy selection
assignment_strategy: random

# Limits
max_annotations_per_user: 10    # -1 for unlimited
max_annotations_per_item: 3     # -1 for unlimited

# Optional: nested configuration
assignment:
  strategy: random
  max_annotations_per_item: 3
  random_seed: 1234
```

### Configuration Options Reference

| Field | Type | Description |
|-------|------|-------------|
| `assignment_strategy` | string | One of: `random`, `fixed_order`, `least_annotated`, `max_diversity`, `diversity_clustering`, `batch`, `active_learning`, `llm_confidence` |
| `max_annotations_per_user` | integer | Maximum annotations per user (-1 = unlimited) |
| `max_annotations_per_item` | integer | Target annotations per item (-1 = unlimited) |
| `assignment.random_seed` | integer | Seed for reproducible random assignment |

### Reclaiming Abandoned Assignments

For crowdsourcing batches, workers can return, time out, or fail quality checks after
receiving a batch of assigned items. Potato reclaims assigned-but-unannotated items
so they can be assigned again. Completed annotations are kept by default.

```yaml
instance_reclaim:
  enabled: true
  timeout_hours: 24
  preserve_completed_annotations: true
```

Reclaiming happens automatically for stale assignments when assignment runs, and for
Prolific workers whose submissions become `RETURNED`, `TIMED-OUT`, or `REJECTED`
when Prolific submission status is refreshed. Users blocked by attention-check
failure also release their unannotated assignments immediately.

You can choose whether completed annotations from reclaimed users are preserved.
This can be useful when you trust partial work from timed-out Prolific workers but
want to discard all work from users blocked by quality control:

```yaml
instance_reclaim:
  enabled: true
  timeout_hours: 24

  # Default for reclaim reasons not overridden below.
  preserve_completed_annotations: true

  prolific:
    preserve_completed_annotations: true
    status_policies:
      TIMED-OUT:
        preserve_completed_annotations: true
      RETURNED:
        preserve_completed_annotations: true
      REJECTED:
        preserve_completed_annotations: false

  quality_control:
    preserve_completed_annotations: false
```

When `preserve_completed_annotations` is `false`, Potato clears that user's
annotations for their assigned items, removes their annotator credit from those
items, and returns the items to the assignment pool. The failed attention-check
response that triggers a block is never kept.

---

## Legacy Configuration

The older `automatic_assignment` configuration is still supported for backwards compatibility:

```yaml
automatic_assignment:
  on: true
  output_filename: task_assignment.json
  sampling_strategy: random    # 'random' or 'ordered'
  labels_per_instance: 3       # Number of labels per instance
  instance_per_annotator: 5    # Instances per annotator
  test_question_per_annotator: 0  # Test questions per annotator
```

### Legacy Options

| Field | Description | Default |
|-------|-------------|---------|
| `on` | Enable automatic assignment | `false` |
| `output_filename` | Output file for assignments | `task_assignment.json` |
| `sampling_strategy` | `random` or `ordered` | `random` |
| `labels_per_instance` | Target annotations per item | 3 |
| `instance_per_annotator` | Items per annotator | 5 |
| `test_question_per_annotator` | Test questions to insert | 0 |

**Note**: If `on` is `false`, all instances will be displayed to each participant.

---

## Test Questions

You can insert test questions (attention checks) into the annotation queue. These are typically easy instances with known correct answers.

### Defining Test Questions

Add `_testing` to the instance ID in your data file:

```csv
text,id
"This is test question 1",0_testing
"This is test question 2",1_testing
"This is test question 3",2_testing
"Hello world",dkjfd
"Hello tomorrow",998ds
```

Or in JSON format:

```json
[
  {"id": "0_testing", "text": "This is a test question with an obvious answer"},
  {"id": "1_testing", "text": "Another test question"},
  {"id": "regular_item_1", "text": "Normal annotation item"}
]
```

### Configuration

```yaml
automatic_assignment:
  on: true
  test_question_per_annotator: 2  # Insert 2 test questions per annotator
```

Potato will:
1. Identify instances with `_testing` in their ID
2. Randomly sample N test questions for each annotator
3. Insert them into the annotation queue

---

## Examples

### Basic Random Assignment

```yaml
annotation_task_name: "Sentiment Analysis"
assignment_strategy: random
max_annotations_per_user: 20
max_annotations_per_item: 3
```

### Quality-Focused Assignment

Use max-diversity to focus on items with disagreement:

```yaml
annotation_task_name: "Quality Annotation"
assignment_strategy: max_diversity
max_annotations_per_item: 5
max_annotations_per_user: 50
```

### Crowdsourcing Setup

For MTurk or Prolific:

```yaml
annotation_task_name: "Crowdsourced Task"
assignment_strategy: random
max_annotations_per_user: 10
max_annotations_per_item: 3

# Crowdsourcing settings
hide_navbar: true
jumping_to_id_disabled: true

login:
  type: url_direct
  url_argument: workerId  # or PROLIFIC_PID
```

### Active Learning Setup

For intelligent prioritization:

```yaml
assignment_strategy: active_learning

active_learning:
  enabled: true
  schema_names: ["sentiment", "topic"]
  min_annotations_per_instance: 2
  min_instances_for_training: 20
  update_frequency: 10
  classifier_name: "sklearn.linear_model.LogisticRegression"
  vectorizer_name: "sklearn.feature_extraction.text.TfidfVectorizer"
```

See [Active Learning Guide](../ai-intelligence/active_learning_guide.md) for complete configuration options.

---

## Admin Dashboard Integration

You can monitor and adjust assignment settings through the Admin Dashboard:

1. Navigate to `/admin`
2. Go to the **Configuration** tab
3. Modify:
   - Max Annotations per User
   - Max Annotations per Item
   - Assignment Strategy

Changes take effect immediately without server restart.

See [Admin Dashboard](../administration/admin_dashboard.md) for more details.

---

## Related Documentation

- [Diversity Ordering](../workflow/diversity_ordering.md) - Embedding-based diverse item presentation
- [Active Learning Guide](../ai-intelligence/active_learning_guide.md) - ML-based assignment prioritization
- [Quality Control](../workflow/quality_control.md) - Attention checks and gold standards
- [Admin Dashboard](../administration/admin_dashboard.md) - Real-time configuration management
- [Crowdsourcing](../deployment/crowdsourcing.md) - MTurk and Prolific integration
