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
1. **Direct Access**: Navigate to `/admin` and enter the API key when prompted. The form says where this server's key comes from: the config file, the environment variable, or `admin_api_key.txt`
2. **Header Access**: Include `X-API-Key: <your_key>` in request headers
3. **Debug Mode**: When `debug: true` is set, requests from the machine the server runs on (`http://localhost:<port>`) need no API key. Requests from other machines, or through a proxy, still do

A request to `/admin` that carries a wrong key gets HTTP 403, and the form shows "That API key wasn't recognized".

**Logout** in the header removes the key from the browser session (`POST /admin/logout`) and returns you to the key form. An annotator login in the same browser is not affected.

### Finding Your Auto-Generated Key

If you didn't configure an API key explicitly, find it in one of these ways:
- Check the server console output for the message "Generated admin API key"
- Read the file `{task_dir}/admin_api_key.txt`

### Security Notes

- API keys are stored in the session for the duration of the browser session
- Admin API endpoints accept the key in the `X-API-Key` header, or the session set by the `/admin` form
- The dashboard automatically redirects to login if no valid API key is provided
- Auto-generated keys are persisted across server restarts (stored in `admin_api_key.txt`)
- For production deployments, consider setting an explicit key via config or environment variable

## Dashboard Features

### Navigation

The bar under the header links to the other admin pages. A link appears only when its page has something to show for this project:

| Link | Shown when |
|---|---|
| Agreement (IAA) | always |
| Adjudication | `adjudication.enabled: true` |
| Review board | `review_workflow.enabled: true` |
| Triage queue | `triage.enabled: true` |
| Judge alignment | `judge_alignment.enabled: true` |
| Annotation integrity | the project has a radio, multiselect, select or likert scheme |

The Tools group links Datasets, Judge Calibration, Automation, Catalog and Arena when each is enabled, and Publish Dataset always.

The selected tab is kept in the URL (`/admin#instances`), so a reload or a shared link opens the same tab. The tab strip takes the arrow keys, Home and End.

### 1. Overview Tab

The Overview tab holds project-wide counts and progress.

**Summary row:**
- **Items**: Items in the dataset, and how many have at least one annotation
- **Annotations**: Total annotations, and the mean per item
- **Annotators**: Registered annotators, how many are in the annotation phase, and how many have finished. Being in the annotation phase does not mean someone is annotating right now
- **Working Time**: Time summed over all annotators, shown as `7m` or `1h 12m`
- **Open issues**: Shown when [memos](../advanced/memos.md) are on: issues raised from the Notes panel that are still open, and how many are resolved
- **Over-collected**: Shown only when some items hold more annotations than the per-item cap

**Agreement:** One number per schema, computed over items that have two or more annotators. The measure is Krippendorff's alpha where the schema has one. Otherwise it is the first chance-corrected coefficient in the schema's list, then a correlation, then raw overlap such as mean Jaccard. Percent agreement is never used here. Values from 0.6 to 0.8 are labelled *substantial*, above 0.8 *strong*, and below 0.2 *poor*, as in the scale legend on `/admin/iaa`. The full table is at **Full report**, which opens `/admin/iaa`.

**System Information:** Task name, assignment limits ("No limit" when unset), assignment strategy and debug mode.

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
- **Max Instances**: The most items this annotator can be assigned. Type a number and press **Set**, or leave the field empty for no limit. The value cannot go below the number of items the annotator has already done; the server raises it to that number and the message says so. A message with **Undo** confirms each change
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
- **Most Frequent Label**: The most common answer to each question, written `schema: label (count/total)`
- **Disagreement**: The share of annotations that did not choose the modal
  label, pooled over all questions, so 0.0 is unanimity and 0.67 is three
  annotators picking three different labels. Shaded green at 0, amber above 0,
  and red at 0.5 or more; "—" when fewer than two people annotated the item.
  With adjudication enabled, the value links to the item in `/adjudicate`
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

Distributions are drawn as horizontal bars, with the count and share at the right.

For **Radio/Select** questions:
- Response distribution
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
- **Interactions**: All tracked interactions (clicks, focus, navigation), and the number of instances they were counted over. Annotations that were imported or seeded have label changes but no interaction log. Those instances read **Not recorded** (per user: "not recorded") instead of 0
- **Annotation Changes**: Total label modifications
- **AI Requests**: Total AI assistance requests

**AI Assistance Usage Section:**

AI assistance metrics, shown when there are any:
- **Total Requests**: Number of times annotators requested AI help
- **Accepted**: Number of AI suggestions accepted
- **Rejected**: Number of AI suggestions rejected
- **Accept Rate**: Share of the suggestions the annotator decided on that they accepted. A suggestion with no decision yet counts as pending, not rejected
- **Avg Decision Time**: Average time from seeing suggestion to making a decision

**Quality Indicators Section:**

Metrics that point at possible quality problems:
- **High Suspicion Users**: Count of users with suspicious behavior patterns
- **Fast Annotation Rate**: Share of annotators with at least one instance finished in under 5 seconds
- **Low Interaction Rate**: Share of annotators with at least one instance of fewer than 3 interactions
- **No Change Rate**: Share of annotators with at least one instance where no annotation changes were made

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
- **Avg Time (s)**: Average time on an instance, in seconds. "n/a" when no time was measured

Time on an instance is the sum of the gaps between its interaction events. A gap
longer than five minutes counts as five minutes, and the time between leaving an
instance and coming back to it does not count. An instance with fewer than two
events has no measured time and is left out of the averages rather than counted
as zero.
- **Interactions**: Total interaction count
- **Changes**: Number of annotation modifications
- **AI Requests**: Number of AI assistance requests
- **AI Accept Rate**: Percentage of AI suggestions accepted
- **Suspicion**: Suspicion score (0-100%, higher = more suspicious)

Users are sorted by suspicion score to help identify potentially problematic annotators.

**Quality Detection:**

The suspicion score is calculated based on:
1. **Fast Annotation Rate**: Annotations completed too quickly may indicate low effort. Measured over the instances with a recorded time; with none it drops out and the other weights are rescaled
2. **Low Interaction Rate**: Very few interactions may indicate random clicking. Measured over the instances that have an interaction log; with none it drops out like the fast rate. An instance with label changes but no interaction events at all has no log, since the tracker records every click and keypress
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

### 6. Throughput Tab

How fast each annotator works, and how often their work is sent back.

- **Items per active hour** and **median time per item**, for the project and
  for each annotator. Active time comes from the annotator's own interaction
  events: the gaps between events, each capped at five minutes so an idle tab
  does not count as work. An item labelled on the [grid](../advanced/grid_view.md)
  has no events of its own; it counts an equal share of its page's active time
  and is dated by when it was saved.
- Only saved items count. Time on an item that was opened and left counts
  towards nothing.
- Attention-check and gold items are not work on the data, so they are
  counted apart (**Check items**) and left out of every rate.
- **Time per item**: a histogram of active time per item over fixed bins
  (under 5 s, 5–10 s, up to 10 minutes and over) and the 25th, 50th, 75th and
  90th percentiles, for the project. Each annotator's row has a small
  copy of the same histogram, with the 10th to 90th percentile range beside it. The
  bins are the same for everyone, so an annotator whose bars sit at the left
  is faster than the others; a block of items under 5 s is worth a look.
- **By day** (UTC), from when each item was last touched, as a table and, once
  work has been saved on two or more days, as two charts: items saved per day
  and items per active hour. Each annotator's row has a line of their items
  per active hour by day. Saved items with no interaction events, such as
  imported answers or saves made through the API, are counted under
  *no events*, and the rates leave them out (a note says how many).
- With the [review workflow](../agent-evaluation/review_workflow.md) on, each
  annotator also gets **first-pass approval**, the share of their reviewed
  items that reached *done* without being sent back to an earlier review
  state, and **rework**, the share sent back at least once. An item's outcome
  counts for every annotator who saved an answer on it.
- Declared machine raters are left out.

### 7. Crowdsourcing Tab

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

A worker's platform is the one they arrived through, recorded when they first
log in. Workers who registered before that was recorded are classified by the
Prolific or MTurk IDs they carry. **Completed** counts workers who reached the
end of the study; **in progress** counts everyone between consent and the end.

This tab is particularly useful for:
- Monitoring crowdsourcing campaign progress
- Identifying low-quality workers
- Tracking multiple studies/HITs
- Ensuring workers receive completion codes

### 8. Configuration Tab

The Configuration tab changes assignment settings on a running server.

**Configurable Settings:**
- **Max Annotations per User**: Limit annotations per user. Tick **No limit** for none
- **Max Annotations per Item**: Limit annotations per item. Tick **No limit** for none

The API behind the form still uses `-1` for no limit.
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
`total_working_time` is a display string (`7m`, `1h 12m`);
`total_working_seconds` is the same value as a whole number of seconds.

### Agreement Summary
```
GET /admin/api/iaa_summary
Headers: X-API-Key: admin_api_key
```

One row per schema: `schema`, `annotation_type`, `metric` (the measure
chosen, or `null`), `value`, `display`, `band` (`strong`, `substantial`, `weak` or empty),
`n_items`, `n_annotators`, and `note` when no measure could be computed.
`n_overlap_items` counts the items with two or more annotators.

### Agreement Report
```
GET /admin/iaa
Headers: X-API-Key: admin_api_key
```

Returns JSON to API clients. A browser, which sends `Accept: text/html`,
gets the rendered page. `?format=json` or `?format=html` overrides the
`Accept` header. `/admin/judge-alignment`, `/admin/annotation-integrity` and
`/admin/triage-queue` follow the same rule.

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

Each row's `most_frequent_label` pools every schema. `label_summary_by_schema`
lists the modal label per schema as `{schema, label, count, total}`.

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
    "instances_with_interaction_log": 480,
    "total_changes": 2500,
    "total_ai_requests": 150
  },
  "ai_usage": {
    "total_requests": 150,
    "total_accepts": 105,
    "total_rejects": 45,
    "total_pending": 0,
    "accept_rate": 0.7,
    "avg_decision_time_ms": 3500
  },
  "quality_summary": {
    "high_suspicion_users": 2,
    "fast_annotation_rate": 0.055,
    "low_interaction_rate": 0.032,
    "no_change_rate": 0.081
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
      "instances_with_interaction_log": 50,
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

### Throughput
```
GET /admin/api/throughput
```

`annotators` holds one row per annotator: `items`, `qc_items` (attention and
gold items, left out of the rates), `items_timed`,
`active_seconds`, `items_per_active_hour`, `median_active_seconds`,
`time_distribution` and `by_day`, plus `reviewed_items`, `first_pass_approval` and `rework_rate` when
`review_enabled` is true. `project` holds the same totals and the by-day rows
for everyone. A rate is `null` when there is no timed work to divide by.
`time_distribution` is `null` with no timed items, otherwise `n`, `p10`,
`p25`, `p50`, `p75`, `p90`, `max` (seconds) and `bins`, a list of
`{from, to, count}` with `from` inclusive, `to` exclusive and `null` on the
last, open-ended bin.

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

`GET /admin/api/instances` computes a row for every instance before it filters,
sorts and paginates — it has to, because sorting by disagreement means knowing
the disagreement everywhere. What it does not do is ask each annotator for that
instance separately: one pass over annotators builds the per-instance
aggregates, so the cost tracks the number of annotations that exist rather than
instances × annotators. A page of 25 rows takes roughly 150 ms over 5,000
instances with 20 annotators, and 750 ms over 20,000.

The instance list is paginated rather than sent to the browser whole, and a
tab's data is fetched only when you open that tab.

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