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

Potato supports six assignment strategies, four fully implemented and two placeholders for future development.

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

### Placeholder Strategies

#### 5. Active Learning Assignment (`active_learning`)

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

See [Active Learning Guide](active_learning_guide.md) for full configuration.

#### 6. LLM Confidence Assignment (`llm_confidence`)

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
| `assignment_strategy` | string | One of: `random`, `fixed_order`, `least_annotated`, `max_diversity`, `active_learning`, `llm_confidence` |
| `max_annotations_per_user` | integer | Maximum annotations per user (-1 = unlimited) |
| `max_annotations_per_item` | integer | Target annotations per item (-1 = unlimited) |
| `assignment.random_seed` | integer | Seed for reproducible random assignment |

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

See [Active Learning Guide](active_learning_guide.md) for complete configuration options.

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

See [Admin Dashboard](admin_dashboard.md) for more details.

---

## Related Documentation

- [Active Learning Guide](active_learning_guide.md) - ML-based assignment prioritization
- [Quality Control](quality_control.md) - Attention checks and gold standards
- [Admin Dashboard](admin_dashboard.md) - Real-time configuration management
- [Crowdsourcing](crowdsourcing.md) - MTurk and Prolific integration
