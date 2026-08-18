# Admin Dashboard

## Overview

The admin dashboard is a web view of a running Potato project. It shows annotation progress, per-annotator timing and performance, per-instance statistics, and it lets you change assignment settings without restarting the server.

## Access and Authentication

### API Key Authentication

The admin dashboard requires an API key for access. The API key can be configured in several ways (in priority order):

1. **Config file**: Set `admin_api_key` in your YAML configuration
   ```yaml
   admin_api_key: your_secret_key_here
   ```

2. **Environment variable**: Set `POTATO_ADMIN_API_KEY`
   ```bash
   export POTATO_ADMIN_API_KEY=your_secret_key_here
   ```

3. **Auto-generated**: If no key is configured, Potato automatically generates a secure random key and saves it to `admin_api_key.txt` in your task directory. The key is logged to the console on server startup.

**Access Methods:**
1. **Direct Access**: Navigate to `/admin` and enter the API key when prompted
2. **Header Access**: Include `X-API-Key: <your_key>` in request headers
3. **Debug Mode**: When `debug: true` is set in config, no API key is required

### Finding Your Auto-Generated Key

If you didn't configure an API key explicitly, find it in one of these ways:
- Check the server console output for the message "Generated admin API key"
- Read the file `{task_dir}/admin_api_key.txt`

### Security Notes

- API keys are stored in the session for the duration of the browser session
- All admin API endpoints require the API key in headers
- The dashboard automatically redirects to login if no valid API key is provided
- Auto-generated keys are persisted across server restarts (stored in `admin_api_key.txt`)
- For production deployments, consider setting an explicit key via config or environment variable

## Dashboard Features

### 1. Overview Tab

The Overview tab holds project-wide counts and progress.

**Key Metrics:**
- **Total Users**: Number of registered annotators
- **Active Users**: Users currently in annotation phase
- **Total Annotations**: Completed annotations across all users
- **Completion Percentage**: Percentage of items with annotations
- **Total Items**: Items in the dataset
- **Working Time**: Total time spent by all annotators

**System Information:**
- Task name and configuration
- Assignment limits and strategy
- Debug mode status

### 2. Annotators Tab

The Annotators tab lists each annotator with their timing and throughput.

**Annotator Metrics:**
- **User ID**: Unique identifier for each annotator
- **Phase**: Current phase (LOGIN, ANNOTATION, DONE, etc.)
- **Annotations**: Total number of completed annotations
- **Working Time**: Total time spent annotating
- **Average Time/Annotation**: Mean time per annotation
- **Speed**: Annotations completed per hour
- **Completion %**: Percentage of assigned items completed
- **Last Activity**: Timestamp of last annotation activity

**Timing Analysis:**
- Individual annotator performance tracking
- Speed comparisons between annotators
- Time distribution analysis
- Current instance timing (if actively annotating)

### 3. Instances Tab

The Instances tab is a paginated list of every annotation instance and its statistics.

**Instance Metrics:**
- **Instance ID**: Unique identifier for each instance
- **Text Preview**: First 100 characters of the instance text
- **Annotations**: Number of annotations received
- **Completion %**: Percentage of target annotations reached
- **Most Frequent Label**: Most commonly selected label
- **Disagreement**: Measure of annotator disagreement (0-1 scale)
- **Average Time**: Mean time spent annotating this instance
- **Annotators**: List of users who annotated this instance

**Pagination and Sorting:**
- **Page Size**: 25, 50, or 100 instances per page
- **Sort Options**:
  - Annotation count (asc/desc)
  - Completion percentage (asc/desc)
  - Disagreement score (asc/desc)
  - Instance ID (asc/desc)
  - Average time (asc/desc)
- **Filtering**: Show all, completed only, or incomplete only

### 4. Questions Tab

The Questions tab aggregates responses for each annotation schema in your configuration.

**Analysis by Annotation Type:**

For **Radio/Select** questions:
- Response distribution histogram
- Most common label
- Agreement score (percentage of annotators selecting the same label)

For **Multiselect** questions:
- Label frequency histogram
- Co-occurrence analysis
- Average labels per item

For **Likert/Slider/Number** questions:
- Value distribution histogram
- Statistics: mean, median, min, max, standard deviation

For **Text** questions:
- Average response length and word count
- Most common words
- Empty response count

For **Span** questions:
- Average spans per item
- Items with spans
- Span range statistics

### 5. Behavioral Analytics Tab

The Behavioral Analytics tab reports what the interaction tracker recorded: how annotators worked, how they used AI assistance, and which sessions look like low effort.

**Summary Statistics:**
- **Users with Data**: Number of users with behavioral tracking data
- **Total Instances**: Total tracked annotation sessions
- **Avg Time**: Average time per annotation instance
- **Total Interactions**: All tracked interactions (clicks, focus, navigation)
- **Annotation Changes**: Total label modifications
- **AI Requests**: Total AI assistance requests

**AI Assistance Usage Section:**

AI assistance metrics, shown when there are any:
- **Total Requests**: Number of times annotators requested AI help
- **Accepted**: Number of AI suggestions accepted
- **Rejected**: Number of AI suggestions rejected
- **Accept Rate**: Percentage of suggestions accepted
- **Avg Decision Time**: Average time from seeing suggestion to making a decision

**Quality Indicators Section:**

Metrics that point at possible quality problems:
- **High Suspicion Users**: Count of users with suspicious behavior patterns
- **Fast Annotation Rate**: Percentage of annotations completed in under 2 seconds
- **Low Interaction Rate**: Percentage of instances with minimal interaction
- **No Change Rate**: Percentage of instances where no annotation changes were made

**Interaction Types Breakdown:**

The interaction types recorded:
- clicks, focus_in, focus_out, navigation, save, keypress, etc.

**Change Sources Breakdown:**

How each annotation change was made:
- `user`: Direct user interaction
- `ai_accept`: User accepted AI suggestion
- `keyboard`: Keyboard shortcut used
- `prefill`: Pre-filled from configuration

**Per-User Behavioral Table:**

Detailed behavioral metrics for each annotator:
- **User ID**: Annotator identifier
- **Instances**: Number of instances with behavioral data
- **Avg Time (s)**: Average annotation time in seconds
- **Interactions**: Total interaction count
- **Changes**: Number of annotation modifications
- **AI Requests**: Number of AI assistance requests
- **AI Accept Rate**: Percentage of AI suggestions accepted
- **Suspicion**: Suspicion score (0-100%, higher = more suspicious)

Users are sorted by suspicion score to help identify potentially problematic annotators.

**Quality Detection:**

The suspicion score is calculated based on:
1. **Fast Annotation Rate**: Annotations completed too quickly may indicate low effort
2. **Low Interaction Rate**: Very few interactions may indicate random clicking
3. **No Change Rate**: Never changing initial selections may indicate lack of careful consideration

Users with suspicion scores above 50% are highlighted in red.

**Writing Process Panel:**

Shown in the Behavioral tab only when
[keystroke logging](../advanced/keystroke_logging.md) is enabled. Reports how
each annotator produced their free-text responses:

- **Median IKI**: Typical inter-keystroke interval
- **Rhythm CV**: Dispersion of log inter-key intervals. Low = metronomic = the copy-typing signature
- **Pauses ≥2s /100ch**: Thinking pauses, normalized by response length
- **Pasted**: Share of characters that arrived by paste
- **Silent Insert**: Share of inserted characters with no corresponding keystroke
- **Flags**: Which detection rules fired, and how often
- **Risk**: `writing_process_risk`, a ranking aid

Each flagged session is listed beneath its annotator with the **evidence** that
fired it — the actual feature values, not just a verdict label.

`writing_process_risk` is deliberately kept **separate** from the suspicion
score above. Those four weights sum to 1.0 and every existing deployment's
numbers are calibrated against them; folding in a new term would silently
reinterpret historical scores.

!!! warning "A ranking, not a finding"
    Writing-process flags have innocent explanations — fast typists, mobile
    keyboards, IME users, dictation, assistive technology. The panel renders a
    caveat above the table for this reason. Read the per-session evidence, and
    see [false positives](../advanced/writing_process_detection.md#false-positives)
    before acting on any flag.

### 6. Crowdsourcing Tab

The Crowdsourcing tab breaks the same statistics out by platform for Prolific and Amazon Mechanical Turk (MTurk) workers.

**Summary Statistics:**
- **Total Workers**: All workers across platforms
- **Prolific Workers**: Workers from Prolific
- **MTurk Workers**: Workers from Amazon MTurk
- **Other Workers**: Direct access or non-platform workers
- **Prolific Studies**: Unique study IDs detected
- **MTurk HITs**: Unique HIT IDs detected

**Platform Sections:**

Each platform section displays:
- Total annotations by platform workers
- Average annotations per worker
- Average time per worker
- Completed vs. in-progress counts
- Study IDs (Prolific) or HIT IDs (MTurk)

**Worker Table:**
For each worker, displays:
- Worker ID
- Current phase
- Total annotations
- Time spent
- Annotations per hour
- Completion percentage
- Suspicious activity level
- Session ID (Prolific) or Assignment ID (MTurk)

This tab is particularly useful for:
- Monitoring crowdsourcing campaign progress
- Identifying low-quality workers
- Tracking multiple studies/HITs
- Ensuring workers receive completion codes

### 7. Configuration Tab

The Configuration tab changes assignment settings on a running server.

**Configurable Settings:**
- **Max Annotations per User**: Limit annotations per user (-1 for unlimited)
- **Max Annotations per Item**: Limit annotations per item (-1 for unlimited)
- **Assignment Strategy**:
  - `random`: Random assignment
  - `fixed_order`: Sequential assignment
  - `least_annotated`: Prioritize items with fewest annotations
  - `max_diversity`: Prioritize items with highest disagreement
  - `active_learning`: Serves the pool in active-learning order (needs `active_learning.enabled`)
  - `llm_confidence`: Not implemented — falls back to random selection

  The dashboard exposes this subset. See
  [Available Strategies](../configuration/configuration.md#available-strategies)
  for all eleven.

**Configuration Management:**
- Real-time updates without server restart
- Validation of configuration values
- Immediate application of changes

## API Endpoints

### Overview Data
```
GET /admin/api/overview
Headers: X-API-Key: admin_api_key
```

Returns user statistics, annotation progress, and a configuration summary.

### Annotators Data
```
GET /admin/api/annotators
Headers: X-API-Key: admin_api_key
```

Returns detailed information about all annotators including timing metrics and performance statistics.

### Instances Data
```
GET /admin/api/instances?page=1&page_size=25&sort_by=annotation_count&sort_order=desc&filter_completion=
Headers: X-API-Key: admin_api_key
```

Returns paginated instances data with sorting and filtering options.

**Query Parameters:**
- `page`: Page number (default: 1)
- `page_size`: Items per page (default: 25)
- `sort_by`: Sort field (annotation_count, completion_percentage, disagreement, id, average_time)
- `sort_order`: Sort order (asc, desc)
- `filter_completion`: Filter by completion (completed, incomplete, all)

### Questions Data
```
GET /admin/api/questions
Headers: X-API-Key: admin_api_key
```

Returns aggregate analysis for each annotation schema including visualizations appropriate to the annotation type.

### Crowdsourcing Data
```
GET /admin/api/crowdsourcing
Headers: X-API-Key: admin_api_key
```

Returns crowdsourcing platform statistics including:
- Summary counts for Prolific, MTurk, and other workers
- Per-platform statistics (annotations, time, completion)
- Individual worker details with platform-specific IDs
- Study IDs (Prolific) and HIT IDs (MTurk)

**Example Response:**
```json
{
  "summary": {
    "total_workers": 50,
    "prolific_workers": 30,
    "mturk_workers": 15,
    "other_workers": 5,
    "prolific_studies": 2,
    "mturk_hits": 3
  },
  "prolific": {
    "stats": {
      "count": 30,
      "total_annotations": 1200,
      "avg_annotations_per_worker": 40.0,
      "completed_count": 25,
      "in_progress_count": 5
    },
    "study_ids": ["study_abc123", "study_def456"],
    "workers": [...]
  },
  "mturk": {
    "stats": {...},
    "hit_ids": ["HIT123", "HIT456"],
    "workers": [...]
  }
}
```

### Behavioral Analytics
```
GET /admin/api/behavioral_analytics
Headers: X-API-Key: admin_api_key
```

Returns the behavioral analytics for every annotator.

**Response Structure:**
```json
{
  "aggregate_stats": {
    "total_users": 25,
    "total_instances": 500,
    "avg_time_per_instance_sec": 45.2,
    "total_interactions": 15000,
    "total_changes": 2500,
    "total_ai_requests": 150
  },
  "ai_usage": {
    "total_requests": 150,
    "total_accepts": 105,
    "total_rejects": 45,
    "accept_rate": 70.0,
    "avg_decision_time_ms": 3500
  },
  "quality_summary": {
    "high_suspicion_users": 2,
    "fast_annotation_rate": 5.5,
    "low_interaction_rate": 3.2,
    "no_change_rate": 8.1
  },
  "interaction_types": {
    "click": 8000,
    "focus_in": 3000,
    "focus_out": 3000,
    "navigation": 500,
    "save": 500
  },
  "change_sources": {
    "user": 2000,
    "ai_accept": 400,
    "keyboard": 100
  },
  "users": [
    {
      "user_id": "user_001",
      "total_instances": 50,
      "avg_time_sec": 45.2,
      "total_interactions": 600,
      "total_changes": 150,
      "ai_requests": 10,
      "ai_accept_rate": 0.7,
      "suspicion_score": 0.15
    }
  ],
  "writing_process": { "enabled": false }
}
```

The `writing_process` block is `{"enabled": false}` unless
[keystroke logging](../advanced/keystroke_logging.md) is configured.

### Writing Process
```
GET /admin/api/writing_process
Headers: X-API-Key: admin_api_key
```

The same `writing_process` block on its own, so the panel can refresh without
recomputing the whole behavioral rollup.

**Response Structure:**
```json
{
  "enabled": true,
  "fidelity": "events",
  "detection_enabled": true,
  "calibrated": false,
  "summary": {
    "total_users": 25,
    "total_sessions": 480,
    "users_with_flags": 3,
    "flag_totals": {"paste_dominant": 4, "silent_insertion": 4}
  },
  "users": [
    {
      "user_id": "user_017",
      "sessions": 20,
      "chars": 4820,
      "iki_median_ms": 133.0,
      "iki_log_cv": 0.145,
      "pause_2s_per_100_chars": 0.27,
      "pasted_char_fraction": 0.61,
      "mean_silent_insert_ratio": 0.58,
      "flag_counts": {"paste_dominant": 4},
      "flagged_sessions": [
        {
          "instance_id": "item_12",
          "schema": "rationale",
          "level": "suspect",
          "flags": ["paste_dominant"],
          "evidence": {"paste_dominant": {"pasted_fraction": 0.983}},
          "explanations": ["98% of the final text arrived by paste rather than typing."]
        }
      ],
      "writing_process_risk": 0.34
    }
  ],
  "caveat": "Writing-process flags are evidence for human review, not proof of misconduct..."
}
```

### Annotation History
```
GET /admin/api/annotation_history?user_id=<user>&instance_id=<instance>&minutes=<n>
Headers: X-API-Key: admin_api_key
```

Returns detailed annotation action history with optional filtering:
- `user_id`: Filter by specific user
- `instance_id`: Filter by specific instance
- `minutes`: Limit to actions within last N minutes

### Suspicious Activity
```
GET /admin/api/suspicious_activity
Headers: X-API-Key: admin_api_key
```

Returns the suspicious-activity analysis:
- Users with suspicious activity
- Suspicious actions details (fast actions, burst patterns)
- Suspicious scores and levels

### Configuration Management
```
GET /admin/api/config
Headers: X-API-Key: admin_api_key
```

Returns current system configuration.

```
POST /admin/api/config
Headers: X-API-Key: admin_api_key
Content-Type: application/json

{
  "max_annotations_per_user": 10,
  "max_annotations_per_item": 3,
  "assignment_strategy": "least_annotated"
}
```

Updates system configuration with provided values.

## Timing Data Analysis

### Annotator Timing Metrics

The dashboard tracks five timing figures for each annotator:

1. **Total Working Time**: Cumulative time spent across all annotations
2. **Average Time per Annotation**: Mean time per individual annotation
3. **Annotations per Hour**: Productivity rate
4. **Current Instance Time**: Time spent on currently active instance
5. **Time Distribution**: Analysis of time patterns across instances

### Instance Timing Analysis

For each instance, the dashboard calculates:

1. **Average Annotation Time**: Mean time across all annotators
2. **Time Variance**: Standard deviation of annotation times
3. **Outlier Detection**: Identification of unusually fast/slow annotations

### Timing Data Sources

Timing data is extracted from:
- Behavioral data stored in `instance_id_to_behavioral_data`
- Time strings in format "Time spent: 0d 0h 0m 5s"
- Parsed into seconds for analysis and calculations

## Performance Considerations

### Large Datasets

The dashboard reads the same in-memory item store and per-user state the
annotation server uses. It issues no SQL of its own, so nothing here is bounded
by a database index.

Two things do help on a large project: the instance list is paginated rather
than sent to the browser whole, and a tab's data is fetched only when you open
that tab.

One thing does not, and it is worth knowing before you point the dashboard at a
large corpus. `GET /admin/api/instances` computes a full row for **every**
instance — most frequent label, disagreement, average time, AI count — and
filters, sorts and paginates afterwards. Each of those three statistics loops
over every annotator's state, so the cost of one page is proportional to
instances × annotators no matter what `page_size` you ask for. On a 50k-item
project with 20 annotators, requesting 25 rows still walks the whole corpus
three times. The Instances tab is the slowest thing in the dashboard for that
reason; the Overview and Annotators tabs scale with the number of annotators
only.

The one cache in the admin surface is the remote data-source download cache,
cleared by `POST /admin/api/cache/clear`. API responses are not cached.

### Real-time Updates

Each section has a manual refresh button, switching tabs reloads that tab's
data, and configuration changes take effect immediately.

## Troubleshooting

### Common Issues

1. **API Key Not Working**
   - Check `admin_api_key.txt` in your task directory for the auto-generated key
   - If you set a custom key, verify it matches what's in your config or environment variable
   - Ensure the key is included in request headers (`X-API-Key: <your_key>`)
   - In debug mode (`debug: true`), no API key is required

2. **No Data Displayed**
   - Check if there are any users or instances in the system
   - Verify that annotations have been submitted
   - Check browser console for JavaScript errors

3. **Configuration Changes Not Applied**
   - Verify the configuration values are valid
   - Check server logs for error messages
   - Ensure the API key is included in the request

4. **Timing Data Missing**
   - Verify that behavioral data is being collected
   - Check that time strings are in the correct format
   - Ensure annotations are being submitted with timing data

### Debug Mode

When `debug: true` is set in the configuration:
- API key authentication is bypassed
- Additional debug information is displayed
- All admin endpoints are accessible without authentication

## Best Practices

### Monitoring workflow

Check the Overview tab for progress, the Annotators tab for anyone whose
metrics have drifted, and the Instances tab for items that are stuck or
contested. Adjust the assignment settings when a pattern shows up rather than
in advance.

### Reading the data

Unusual timing is worth a look in both directions: too fast suggests low
effort, too slow suggests a confusing item. A high disagreement score on many
items usually means the instructions are unclear rather than that the
annotators are careless. Watch completion percentages so work stays evenly
spread, and use the timing figures to pick an assignment strategy.

### Security

Keep the API key secret and replace it if it leaks. Give dashboard access only
to people who need it, log out when you are done so the session key is cleared,
and review admin actions periodically.

## Future Enhancements

Planned features for future versions:

1. **Real-time Notifications**: WebSocket-based real-time updates
2. **Advanced Analytics**: Statistical analysis and trend detection
3. **Export Functionality**: Data export in various formats
4. **User Management**: Direct user management from the dashboard
5. **Audit Logs**: Detailed logging of admin actions
6. **Custom Metrics**: User-defined performance metrics
7. **Integration APIs**: External system integration capabilities