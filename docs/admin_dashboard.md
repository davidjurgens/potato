# Admin Dashboard Documentation

## Overview

The Admin Dashboard provides comprehensive monitoring and management capabilities for the Potato annotation platform. It offers real-time insights into annotation progress, annotator performance, instance statistics, and system configuration management.

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

The Overview tab provides high-level system statistics and progress indicators.

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

The Annotators tab provides detailed information about each annotator's performance and timing.

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

The Instances tab provides a paginated view of all annotation instances with detailed statistics.

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

The Questions tab provides aggregate analysis for each annotation schema/question defined in your configuration.

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

The Behavioral Analytics tab provides comprehensive insights into annotator behavior patterns, AI assistance usage, and quality indicators derived from interaction tracking data.

**Summary Statistics:**
- **Users with Data**: Number of users with behavioral tracking data
- **Total Instances**: Total tracked annotation sessions
- **Avg Time**: Average time per annotation instance
- **Total Interactions**: All tracked interactions (clicks, focus, navigation)
- **Annotation Changes**: Total label modifications
- **AI Requests**: Total AI assistance requests

**AI Assistance Usage Section:**

Displays AI assistance metrics when available:
- **Total Requests**: Number of times annotators requested AI help
- **Accepted**: Number of AI suggestions accepted
- **Rejected**: Number of AI suggestions rejected
- **Accept Rate**: Percentage of suggestions accepted
- **Avg Decision Time**: Average time from seeing suggestion to making a decision

**Quality Indicators Section:**

Displays metrics that help identify potential quality issues:
- **High Suspicion Users**: Count of users with suspicious behavior patterns
- **Fast Annotation Rate**: Percentage of annotations completed in under 2 seconds
- **Low Interaction Rate**: Percentage of instances with minimal interaction
- **No Change Rate**: Percentage of instances where no annotation changes were made

**Interaction Types Breakdown:**

Visual display of interaction types recorded:
- clicks, focus_in, focus_out, navigation, save, keypress, etc.

**Change Sources Breakdown:**

Shows how annotation changes were made:
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

### 6. Crowdsourcing Tab

The Crowdsourcing tab provides dedicated monitoring for workers from crowdsourcing platforms like Prolific and Amazon Mechanical Turk (MTurk).

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

The Configuration tab allows administrators to modify system settings in real-time.

**Configurable Settings:**
- **Max Annotations per User**: Limit annotations per user (-1 for unlimited)
- **Max Annotations per Item**: Limit annotations per item (-1 for unlimited)
- **Assignment Strategy**:
  - `random`: Random assignment
  - `fixed_order`: Sequential assignment
  - `least_annotated`: Prioritize items with fewest annotations
  - `max_diversity`: Prioritize items with highest disagreement
  - `active_learning`: ML-based assignment with intelligent instance prioritization
  - `llm_confidence`: LLM-based assignment (placeholder)

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

Returns comprehensive system overview including user statistics, annotation progress, and configuration summary.

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

Returns comprehensive behavioral analytics data for all annotators.

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
      "ai_accept_rate": 70.0,
      "suspicion_score": 0.15
    }
  ]
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

Returns comprehensive suspicious activity analysis including:
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

The dashboard tracks comprehensive timing data for each annotator:

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

For projects with many instances or annotators:

1. **Pagination**: Instances are paginated to avoid overwhelming the browser
2. **Lazy Loading**: Data is loaded only when tabs are accessed
3. **Caching**: API responses can be cached for better performance
4. **Efficient Queries**: Database queries are optimized for large datasets

### Real-time Updates

The dashboard provides:
- Manual refresh buttons for each section
- Automatic data loading when switching tabs
- Real-time configuration updates

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

### Monitoring Workflow

1. **Regular Check-ins**: Monitor the overview tab regularly for progress
2. **Annotator Performance**: Review annotator metrics to identify issues
3. **Instance Analysis**: Use the instances tab to find problematic items
4. **Configuration Tuning**: Adjust settings based on observed patterns

### Data Analysis

1. **Timing Patterns**: Look for unusual timing patterns that might indicate issues
2. **Disagreement Analysis**: High disagreement scores may indicate unclear instructions
3. **Completion Tracking**: Monitor completion percentages to ensure even distribution
4. **Performance Optimization**: Use timing data to optimize assignment strategies

### Security

1. **API Key Management**: Keep the API key secure and change it if compromised
2. **Access Control**: Limit access to the admin dashboard to authorized personnel
3. **Session Management**: Log out when finished to clear session data
4. **Audit Logging**: Monitor admin actions for security purposes

## Future Enhancements

Planned features for future versions:

1. **Real-time Notifications**: WebSocket-based real-time updates
2. **Advanced Analytics**: Statistical analysis and trend detection
3. **Export Functionality**: Data export in various formats
4. **User Management**: Direct user management from the dashboard
5. **Audit Logs**: Detailed logging of admin actions
6. **Custom Metrics**: User-defined performance metrics
7. **Integration APIs**: External system integration capabilities