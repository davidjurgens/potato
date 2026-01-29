# Behavioral Tracking and Analytics

## Overview

Potato's behavioral tracking system captures detailed interaction data during annotation sessions, enabling researchers to analyze annotator behavior, timing patterns, AI assistance usage, and decision-making processes. This data is invaluable for understanding annotation quality, identifying problematic annotators, and improving annotation workflows.

## What Gets Tracked

### 1. Interaction Events

Every user interaction with the annotation interface is captured:

| Event Type | Description | Example Target |
|------------|-------------|----------------|
| `click` | Mouse clicks on elements | `label:positive`, `nav:next` |
| `focus_in` | Element receives focus | `textbox:explanation` |
| `focus_out` | Element loses focus | `label:negative` |
| `keypress` | Keyboard shortcuts | `key:1`, `nav:ArrowRight` |
| `navigation` | Instance navigation | `next`, `prev`, `instance_load` |
| `save` | Annotation save events | `instance:123` |
| `annotation_change` | Label modifications | `schema:sentiment` |

### 2. AI Assistance Usage

Complete lifecycle tracking for AI-assisted annotation:

```json
{
  "request_timestamp": 1706500010.0,
  "response_timestamp": 1706500012.5,
  "schema_name": "sentiment",
  "suggestions_shown": ["positive", "neutral"],
  "suggestion_accepted": "positive",
  "time_to_decision_ms": 3500
}
```

**Tracked metrics:**
- When AI assistance was requested
- Response latency
- Which suggestions were shown
- Whether the suggestion was accepted or rejected
- Time from seeing suggestion to making a decision

### 3. Annotation Changes

Detailed change history for all annotations:

```json
{
  "timestamp": 1706500002.5,
  "schema_name": "sentiment",
  "label_name": "positive",
  "action": "select",
  "old_value": null,
  "new_value": true,
  "source": "user"
}
```

**Source types:**
- `user` - Direct user interaction
- `ai_accept` - User accepted AI suggestion
- `keyboard` - Keyboard shortcut used
- `prefill` - Pre-filled from configuration

### 4. Timing and Focus Data

- **Focus time by element**: Time spent focused on each UI element
- **Scroll depth**: Maximum scroll percentage reached
- **Session timing**: Start/end timestamps and total duration
- **Navigation history**: Complete path through instances

## Data Format

### Behavioral Data Structure

Each annotation instance includes a `behavioral_data` object:

```json
{
  "id": "instance_123",
  "annotations": {
    "sentiment": {"positive": true}
  },
  "behavioral_data": {
    "instance_id": "instance_123",
    "session_start": 1706500000.0,
    "session_end": 1706500045.0,
    "total_time_ms": 45000,
    "interactions": [
      {
        "event_type": "click",
        "timestamp": 1706500002.5,
        "target": "label:positive",
        "instance_id": "instance_123",
        "client_timestamp": 1706500002500,
        "metadata": {"x": 150, "y": 320}
      }
    ],
    "ai_usage": [
      {
        "request_timestamp": 1706500010.0,
        "response_timestamp": 1706500012.5,
        "schema_name": "sentiment",
        "suggestions_shown": ["positive"],
        "suggestion_accepted": "positive",
        "time_to_decision_ms": 3500
      }
    ],
    "annotation_changes": [
      {
        "timestamp": 1706500002.5,
        "schema_name": "sentiment",
        "label_name": "positive",
        "action": "select",
        "old_value": null,
        "new_value": true,
        "source": "user"
      }
    ],
    "navigation_history": [
      {
        "action": "next",
        "from_instance": "instance_122",
        "to_instance": "instance_123",
        "timestamp": 1706500000.0
      }
    ],
    "focus_time_by_element": {
      "label:positive": 2500,
      "label:negative": 1200,
      "textbox:explanation": 8000
    },
    "scroll_depth_max": 75.5,
    "keyword_highlights_shown": [
      {"text": "excellent", "label": "positive", "type": "keyword"}
    ]
  }
}
```

### Storage Location

Behavioral data is stored in:
1. **User state files**: `annotation_output/<user_id>/user_state.json`
2. **Exported annotations**: Included with annotation data when exported

## Configuration

### Enabling Behavioral Tracking

Behavioral tracking is enabled by default. No additional configuration is required.

### Frontend Debug Mode

To enable debug logging for the interaction tracker:

```javascript
// In browser console
window.interactionTracker.setDebugMode(true);
```

### Flush Interval

The default flush interval is 5 seconds. Events are also flushed on page navigation.

## API Endpoints

### Track Interactions

```http
POST /api/track_interactions
Content-Type: application/json

{
  "instance_id": "instance_123",
  "events": [...],
  "focus_time": {"element": ms},
  "scroll_depth": 75.5
}
```

### Track AI Usage

```http
POST /api/track_ai_usage
Content-Type: application/json

{
  "instance_id": "instance_123",
  "schema_name": "sentiment",
  "event_type": "request|response|accept|reject",
  "suggestions": [...],
  "accepted_value": "positive"
}
```

### Get Behavioral Data

```http
GET /api/behavioral_data/<instance_id>
```

Returns the complete behavioral data for an instance.

## Analysis Examples

### Loading Behavioral Data

```python
import json
from pathlib import Path

def load_behavioral_data(annotation_dir: str) -> dict:
    """Load all behavioral data from annotation output directory."""
    data = {}

    for user_dir in Path(annotation_dir).iterdir():
        if not user_dir.is_dir():
            continue

        state_file = user_dir / 'user_state.json'
        if state_file.exists():
            with open(state_file) as f:
                user_state = json.load(f)

            user_id = user_state.get('user_id')
            behavioral = user_state.get('instance_id_to_behavioral_data', {})
            data[user_id] = behavioral

    return data
```

### Analyzing Annotation Time

```python
def analyze_annotation_time(behavioral_data: dict) -> dict:
    """Calculate annotation time statistics per user."""
    stats = {}

    for user_id, instances in behavioral_data.items():
        times = []
        for instance_id, bd in instances.items():
            if 'total_time_ms' in bd:
                times.append(bd['total_time_ms'] / 1000)  # Convert to seconds

        if times:
            stats[user_id] = {
                'mean_time': sum(times) / len(times),
                'min_time': min(times),
                'max_time': max(times),
                'total_instances': len(times)
            }

    return stats
```

### AI Assistance Analysis

```python
def analyze_ai_usage(behavioral_data: dict) -> dict:
    """Analyze AI assistance usage patterns."""
    ai_stats = {
        'total_requests': 0,
        'total_accepts': 0,
        'total_rejects': 0,
        'avg_decision_time_ms': 0,
        'by_schema': {}
    }

    decision_times = []

    for user_id, instances in behavioral_data.items():
        for instance_id, bd in instances.items():
            for ai_event in bd.get('ai_usage', []):
                ai_stats['total_requests'] += 1

                schema = ai_event.get('schema_name', 'unknown')
                if schema not in ai_stats['by_schema']:
                    ai_stats['by_schema'][schema] = {'accepts': 0, 'rejects': 0}

                if ai_event.get('suggestion_accepted'):
                    ai_stats['total_accepts'] += 1
                    ai_stats['by_schema'][schema]['accepts'] += 1
                else:
                    ai_stats['total_rejects'] += 1
                    ai_stats['by_schema'][schema]['rejects'] += 1

                if ai_event.get('time_to_decision_ms'):
                    decision_times.append(ai_event['time_to_decision_ms'])

    if decision_times:
        ai_stats['avg_decision_time_ms'] = sum(decision_times) / len(decision_times)

    return ai_stats
```

### Detecting Suspicious Behavior

```python
def detect_suspicious_annotators(behavioral_data: dict,
                                  min_time_threshold: float = 2.0,
                                  min_interactions_threshold: int = 2) -> list:
    """
    Identify annotators with potentially low-quality behavior.

    Flags:
    - Very fast annotation times (< min_time_threshold seconds)
    - Very few interactions per instance
    - No annotation changes (just clicking through)
    """
    suspicious = []

    for user_id, instances in behavioral_data.items():
        fast_count = 0
        low_interaction_count = 0
        no_change_count = 0

        for instance_id, bd in instances.items():
            time_sec = bd.get('total_time_ms', 0) / 1000
            interactions = len(bd.get('interactions', []))
            changes = len(bd.get('annotation_changes', []))

            if time_sec < min_time_threshold:
                fast_count += 1
            if interactions < min_interactions_threshold:
                low_interaction_count += 1
            if changes == 0:
                no_change_count += 1

        total = len(instances)
        if total > 0:
            fast_rate = fast_count / total
            low_rate = low_interaction_count / total
            no_change_rate = no_change_count / total

            if fast_rate > 0.5 or low_rate > 0.5 or no_change_rate > 0.8:
                suspicious.append({
                    'user_id': user_id,
                    'fast_rate': fast_rate,
                    'low_interaction_rate': low_rate,
                    'no_change_rate': no_change_rate,
                    'total_instances': total
                })

    return suspicious
```

## Integration with Admin Dashboard

The Admin Dashboard includes a **Behavioral Analytics** tab that provides:

1. **User Interaction Heatmap**: Visual representation of interaction patterns
2. **AI Assistance Metrics**: Accept/reject rates, decision times
3. **Timing Distribution**: Histogram of annotation times
4. **Suspicious Activity Alerts**: Flagged annotators requiring review

See [Admin Dashboard Documentation](admin_dashboard.md) for details.

## Best Practices

### For Researchers

1. **Baseline Establishment**: Collect behavioral data from known-good annotators to establish baselines
2. **Quality Metrics**: Use behavioral data alongside annotation agreement for quality assessment
3. **Training Evaluation**: Compare pre- and post-training behavioral patterns
4. **AI Impact Analysis**: Measure how AI assistance affects annotation quality and speed

### For Annotation Projects

1. **Monitor in Real-Time**: Use the admin dashboard to spot issues early
2. **Set Thresholds**: Define acceptable ranges for timing and interaction metrics
3. **Provide Feedback**: Use behavioral insights to provide targeted annotator feedback
4. **Iterate on Guidelines**: Identify confusing instances through interaction patterns

## Jupyter Notebook Tutorial

For a hands-on tutorial on analyzing behavioral data, see the example notebook:

```
examples/behavioral_analysis/analyze_behavioral_data.ipynb
```

This notebook demonstrates:
- Loading and parsing behavioral data
- Visualizing interaction patterns
- Analyzing AI assistance effectiveness
- Detecting quality issues
- Generating reports

## Troubleshooting

### No Behavioral Data Being Collected

1. Verify `interaction_tracker.js` is loaded (check browser Network tab)
2. Check browser console for JavaScript errors
3. Verify API endpoints are accessible (`/api/track_interactions`)

### Data Not Persisting

1. Check that user state is being saved (look for `user_state.json`)
2. Verify serialization is working (check server logs)
3. Ensure the annotation output directory is writable

### High Network Traffic

1. Increase the flush interval in `interaction_tracker.js`
2. Filter out unnecessary events
3. Use sampling for high-volume deployments

## See Also

- [Admin Dashboard](admin_dashboard.md) - Real-time monitoring
- [Annotation History](annotation_history.md) - Detailed change tracking
- [Quality Control](quality_control.md) - Automated quality checks
- [Data Format](data_format.md) - Output file formats
