# Admin Dashboard Documentation

## Overview

The Admin Dashboard provides comprehensive monitoring and management capabilities for the Potato annotation platform. It offers real-time insights into annotation progress, annotator performance, instance statistics, and system configuration management.

## Access and Authentication

### API Key Authentication

The admin dashboard requires an API key for access. The default API key is `admin_api_key`.

**Access Methods:**
1. **Direct Access**: Navigate to `/admin` and enter the API key when prompted
2. **Header Access**: Include `X-API-Key: admin_api_key` in request headers
3. **Debug Mode**: When `debug: true` is set in config, no API key is required

### Security Notes

- API keys are stored in the session for the duration of the browser session
- All admin API endpoints require the API key in headers
- The dashboard automatically redirects to login if no valid API key is provided

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

### 4. Configuration Tab

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
   - Verify the API key is `admin_api_key`
   - Check that debug mode is disabled
   - Ensure the key is included in request headers

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