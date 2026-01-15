# Annotation History and Timestamps

Potato provides comprehensive tracking of all annotation actions with fine-grained timestamp metadata. This enables performance analysis, quality assurance, and detailed audit trails.

## Overview

The annotation history system tracks:

- **Every annotation action**: Label selections, span annotations, text inputs
- **Precise timestamps**: Server and client-side timestamps
- **Action metadata**: User, instance, schema, old/new values
- **Performance metrics**: Processing times, action rates
- **Suspicious activity**: Unusually fast or burst activity patterns

## Features

### Action Tracking

Every annotation change is recorded as an `AnnotationAction` with:

| Field | Description |
|-------|-------------|
| `action_id` | Unique UUID for each action |
| `timestamp` | Server-side timestamp |
| `client_timestamp` | Browser-side timestamp (if available) |
| `user_id` | User who performed the action |
| `instance_id` | Instance being annotated |
| `action_type` | Type of action performed |
| `schema_name` | Annotation schema name |
| `label_name` | Specific label within the schema |
| `old_value` | Previous value (for updates/deletes) |
| `new_value` | New value (for adds/updates) |
| `span_data` | Span details for span annotations |
| `session_id` | Browser session identifier |
| `server_processing_time_ms` | Server processing time |
| `metadata` | Additional context (browser info, etc.) |

### Action Types

The system tracks these action types:

- `add_label` - New label selection
- `update_label` - Label value changed
- `delete_label` - Label removed
- `add_span` - New span annotation created
- `update_span` - Span annotation modified
- `delete_span` - Span annotation removed

## Configuration

Annotation history tracking is enabled by default. No additional configuration required.

### Accessing History Data

Annotation history is saved with user state and can be accessed via the admin dashboard or API.

## Performance Metrics

The system calculates performance metrics from action history:

```python
from potato.annotation_history import AnnotationHistoryManager

# Get metrics for a list of actions
metrics = AnnotationHistoryManager.calculate_performance_metrics(actions)

# Returns:
{
    'total_actions': 150,
    'average_action_time_ms': 45.2,
    'fastest_action_time_ms': 12,
    'slowest_action_time_ms': 234,
    'actions_per_minute': 8.5,
    'total_processing_time_ms': 6780
}
```

### Metrics Explained

| Metric | Description |
|--------|-------------|
| `total_actions` | Total number of annotation actions |
| `average_action_time_ms` | Mean server processing time |
| `fastest_action_time_ms` | Minimum processing time |
| `slowest_action_time_ms` | Maximum processing time |
| `actions_per_minute` | Rate of annotation activity |
| `total_processing_time_ms` | Sum of all processing times |

## Suspicious Activity Detection

The system can detect potentially problematic annotation patterns:

```python
from potato.annotation_history import AnnotationHistoryManager

# Analyze actions for suspicious patterns
analysis = AnnotationHistoryManager.detect_suspicious_activity(
    actions,
    fast_threshold_ms=500,      # Actions faster than this are flagged
    burst_threshold_seconds=2   # Actions closer than this are flagged
)

# Returns:
{
    'suspicious_actions': [...],
    'fast_actions_count': 5,
    'burst_actions_count': 12,
    'fast_actions_percentage': 3.3,
    'burst_actions_percentage': 8.0,
    'suspicious_score': 15.2,
    'suspicious_level': 'Low'
}
```

### Suspicious Levels

| Score | Level | Interpretation |
|-------|-------|----------------|
| 0-10 | Normal | Typical annotation behavior |
| 10-30 | Low | Some fast actions, likely acceptable |
| 30-60 | Medium | Notable pattern, may warrant review |
| 60-80 | High | Concerning pattern, review recommended |
| 80-100 | Very High | Likely quality issue, immediate review |

### Detection Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fast_threshold_ms` | 500 | Actions faster than this are flagged |
| `burst_threshold_seconds` | 2 | Actions closer together than this are flagged |

## API Reference

### AnnotationAction

```python
from potato.annotation_history import AnnotationAction

# Create an action
action = AnnotationAction(
    action_id="uuid-here",
    timestamp=datetime.now(),
    user_id="annotator1",
    instance_id="doc_001",
    action_type="add_label",
    schema_name="sentiment",
    label_name="positive",
    old_value=None,
    new_value=True,
    span_data=None,
    session_id="session_123",
    client_timestamp=None,
    server_processing_time_ms=45,
    metadata={"browser": "Chrome"}
)

# Serialize to dictionary
data = action.to_dict()

# Deserialize from dictionary
action = AnnotationAction.from_dict(data)
```

### AnnotationHistoryManager

```python
from potato.annotation_history import AnnotationHistoryManager

# Create a new action with current timestamp
action = AnnotationHistoryManager.create_action(
    user_id="annotator1",
    instance_id="doc_001",
    action_type="add_label",
    schema_name="sentiment",
    label_name="positive",
    old_value=None,
    new_value=True
)

# Filter actions by time range
filtered = AnnotationHistoryManager.get_actions_by_time_range(
    actions,
    start_time=datetime(2024, 1, 1),
    end_time=datetime(2024, 1, 31)
)

# Filter actions by instance
instance_actions = AnnotationHistoryManager.get_actions_by_instance(
    actions,
    instance_id="doc_001"
)

# Filter actions by type
label_actions = AnnotationHistoryManager.get_actions_by_type(
    actions,
    action_type="add_label"
)

# Calculate performance metrics
metrics = AnnotationHistoryManager.calculate_performance_metrics(actions)

# Detect suspicious activity
analysis = AnnotationHistoryManager.detect_suspicious_activity(actions)
```

## Use Cases

### Quality Assurance

Monitor annotator behavior for quality issues:

```python
# Check for suspiciously fast annotators
for user_id in get_all_users():
    user_actions = get_user_actions(user_id)
    analysis = AnnotationHistoryManager.detect_suspicious_activity(user_actions)

    if analysis['suspicious_level'] in ['High', 'Very High']:
        flag_for_review(user_id, analysis)
```

### Performance Analysis

Identify annotation bottlenecks:

```python
# Find slow schemas
schema_times = defaultdict(list)
for action in all_actions:
    schema_times[action.schema_name].append(action.server_processing_time_ms)

for schema, times in schema_times.items():
    avg_time = sum(times) / len(times)
    print(f"{schema}: {avg_time:.1f}ms average")
```

### Audit Trail

Track changes for regulatory compliance:

```python
# Get complete history for an instance
instance_actions = AnnotationHistoryManager.get_actions_by_instance(
    all_actions, "doc_001"
)

# Export for audit
audit_log = [action.to_dict() for action in instance_actions]
with open("audit_doc_001.json", "w") as f:
    json.dump(audit_log, f, indent=2)
```

### Time Analysis

Understand annotation timing patterns:

```python
# Actions by hour of day
from collections import Counter

hours = Counter(action.timestamp.hour for action in all_actions)
print("Peak annotation hours:", hours.most_common(5))
```

## Data Storage

Annotation history is stored in the user state files:

```
output/
  annotations/
    user_state_annotator1.json  # Includes action history
    user_state_annotator2.json
```

### Export Format

Actions are serialized with ISO 8601 timestamps:

```json
{
  "action_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-15T10:30:45.123456",
  "user_id": "annotator1",
  "instance_id": "doc_001",
  "action_type": "add_label",
  "schema_name": "sentiment",
  "label_name": "positive",
  "old_value": null,
  "new_value": true,
  "span_data": null,
  "session_id": "session_abc123",
  "client_timestamp": "2024-01-15T10:30:45.100000",
  "server_processing_time_ms": 23,
  "metadata": {"browser": "Chrome 120"}
}
```

## Best Practices

1. **Regular monitoring**: Check suspicious activity reports periodically
2. **Threshold tuning**: Adjust detection thresholds based on your task complexity
3. **Export backups**: Regularly export history for long-term storage
4. **Privacy compliance**: Consider data retention policies for timestamps

## Related Documentation

- [Admin Dashboard](admin_dashboard.md) - View annotation statistics
- [Annotator Stats](annotator_stats.md) - Per-annotator metrics
- [User and Collaboration](user_and_collaboration.md) - User management
