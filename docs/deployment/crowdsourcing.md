# Crowdsourcing Integration

Potato can be seamlessly deployed online to collect annotations from common crowdsourcing platforms like Prolific and Amazon Mechanical Turk.

## Setup Potato on a Server

To run Potato in a crowdsourcing setup, you need to deploy Potato on a server with open ports (ports accessible via the open internet). When you start the Potato server, simply change the default port to an openly accessible port:

```bash
potato start your-project -p 8080
```

You should then be able to access the annotation page via `your_ip_address:the_port`.

---

## Prolific Integration

[Prolific](https://www.prolific.co/) is a platform where you can easily recruit task participants. Potato provides seamless integration with Prolific through:

1. **URL-Direct Login**: Automatic login using Prolific's URL parameters
2. **Completion Codes**: Built-in support for completion code display and redirect
3. **Prolific API Integration**: Optional automatic study management via Prolific's API

### Quick Start: Minimal Prolific Setup

For a basic Prolific integration, you only need to add two configuration options to your YAML file:

```yaml
# Enable URL-direct login (extracts PROLIFIC_PID from URL)
login:
  type: url_direct
  url_argument: PROLIFIC_PID  # Optional, this is the default

# Your Prolific completion code
completion_code: "YOUR-PROLIFIC-CODE"
```

With this configuration:
- Workers arriving from Prolific are automatically logged in using their `PROLIFIC_PID`
- No password is required (automatically disabled for URL-direct login)
- When workers complete all tasks, they see a completion page with:
  - The completion code displayed prominently (click to copy)
  - A "Return to Prolific" button that redirects them to submit their completion

### URL-Direct Login

When workers click your study link on Prolific, they arrive at a URL like:
```
https://your-server:8080/?PROLIFIC_PID=abc123&SESSION_ID=xyz789&STUDY_ID=study456
```

Potato automatically:
1. Extracts the worker ID from the URL parameter
2. Creates a session for the worker (no login form needed)
3. Initializes their annotation state
4. Routes them to the first phase (consent, instructions, or annotation)

#### Configuration Options

```yaml
login:
  type: url_direct           # or "prolific" for full API integration
  url_argument: PROLIFIC_PID # URL parameter name to extract username from
                             # Can be customized for MTurk (workerId) etc.
```

#### Supported Login Types

| Type | Description |
|------|-------------|
| `standard` | Default login form (username/password) |
| `url_direct` | Extract username from URL parameter |
| `prolific` | URL-direct login + Prolific API integration |

### Completion Code Setup

Potato provides a built-in completion page that displays your Prolific completion code:

```yaml
# Simple completion code (shown on done page)
completion_code: "YOUR-PROLIFIC-CODE"

# Optional: Auto-redirect to Prolific after completion
auto_redirect_on_completion: true
auto_redirect_delay: 5000  # milliseconds (default: 5000)
```

The completion page features:
- Large, prominent display of the completion code
- Click-to-copy functionality
- "Return to Prolific" button that redirects to `https://app.prolific.co/submissions/complete?cc=YOUR-CODE`
- Optional auto-redirect after a configurable delay

### Full Configuration Example

Here's a complete configuration for a Prolific study:

```yaml
# Task identification
annotation_task_name: "My Prolific Study"

# Prolific login settings
login:
  type: url_direct
  url_argument: PROLIFIC_PID

# Completion settings
completion_code: "ABC123XYZ"
auto_redirect_on_completion: false  # Set to true for auto-redirect

# Hide navigation to prevent workers from skipping
hide_navbar: true
jumping_to_id_disabled: true

# Phase configuration
phases:
  order:
    - consent
    - instructions
    - annotation
  consent:
    file: data/consent.html
  instructions:
    file: data/instructions.html
  annotation:
    type: annotation

# Automatic task assignment for crowdsourcing
assignment_strategy: random
max_annotations_per_user: 10
max_annotations_per_item: 3

# Data files
data_files:
  - data/items.json

# Output
output_annotation_dir: annotation_output/
```

---

## Advanced: Prolific API Integration

For larger studies, Potato can integrate with Prolific's API to automatically manage your study:

- Release slots from returned/timed-out/rejected workers
- Pause the study when server load is high
- Resume when load decreases
- Automatically pause when the study is complete

### Setup Prolific API

1. **Get your Prolific API token** from your [Prolific account settings](https://app.prolific.co/account/general)

2. **Create a Prolific config file** (`configs/prolific_config.yaml`):

```yaml
token: "your-prolific-api-token"
study_id: "your-study-id"
max_concurrent_sessions: 30      # Maximum concurrent workers
workload_checker_period: 300     # Seconds between load checks
```

3. **Reference it in your main config**:

```yaml
login:
  type: prolific  # Enables both URL-direct login and API integration

prolific:
  config_file_path: configs/prolific_config.yaml

completion_code: "YOUR-PROLIFIC-CODE"
```

### Server Workload Management

When many workers access your study concurrently, your server might become overloaded. Potato automatically manages this:

1. Checks active worker count against `max_concurrent_sessions`
2. Pauses the Prolific study if threshold is exceeded
3. Monitors worker count every `workload_checker_period` seconds
4. Resumes when active workers drop to 20% of the maximum

```yaml
# In prolific_config.yaml
max_concurrent_sessions: 30   # Pause study above this threshold
workload_checker_period: 300  # Check every 5 minutes
```

> **Note**: The Prolific API may have performance issues with studies over 200 participants. For very large studies, consider running multiple smaller batches.

---

## Alternative: Using Surveyflow for Completion

If you need more control over the completion page, you can use surveyflow instead of the built-in completion page:

1. **Create an end page** (`surveyflow/end.jsonl`):

```json
{"id":"1","text":"Thanks for your participation! Click the link below to complete the study.","schema": "pure_display", "choices": ["<a href=\"https://app.prolific.co/submissions/complete?cc=YOUR-CODE\" target=\"_blank\">Complete Study on Prolific</a>"]}
```

2. **Configure surveyflow** in your YAML:

```yaml
surveyflow:
  on: true
  order:
    - pre_annotation
    - post_annotation
  pre_annotation:
    - surveyflow/consent.jsonl
  post_annotation:
    - surveyflow/end.jsonl
```

---

## Amazon Mechanical Turk Integration

[Amazon Mechanical Turk (MTurk)](https://www.mturk.com/) is a popular crowdsourcing marketplace for human intelligence tasks. Potato provides full integration with MTurk through:

1. **URL-Direct Login**: Automatic login using MTurk's URL parameters
2. **Preview Mode**: Proper handling of HIT preview state
3. **Form Submission**: Built-in completion flow with form submission to MTurk
4. **MTurk API Integration**: Optional automatic assignment management via AWS API

### Quick Start: Minimal MTurk Setup

For a basic MTurk integration, add these configuration options to your YAML file:

```yaml
# Enable URL-direct login (extracts workerId from URL)
login:
  type: url_direct
  url_argument: workerId

# Optional: completion code to record
completion_code: "COMPLETED"

# Hide navigation for crowdsourcing
hide_navbar: true
jumping_to_id_disabled: true
```

With this configuration:
- Workers arriving from MTurk are automatically logged in using their `workerId`
- Workers previewing the HIT see a preview page prompting them to accept
- When workers complete all tasks, they see a completion page with a "Submit HIT to MTurk" button

### URL Parameters

When workers click your HIT on MTurk, they arrive at a URL like:
```
https://your-server:8080/?workerId=A1B2C3D4E5&assignmentId=xyz123&hitId=abc456&turkSubmitTo=https://www.mturk.com/mturk/externalSubmit
```

Potato automatically captures these MTurk parameters:

| Parameter | Description |
|-----------|-------------|
| `workerId` | Worker's unique MTurk ID (used as username) |
| `assignmentId` | Unique ID for this worker-HIT assignment |
| `hitId` | The HIT identifier |
| `turkSubmitTo` | URL where the form should be submitted on completion |

### HIT Preview Mode

When `assignmentId` equals `ASSIGNMENT_ID_NOT_AVAILABLE`, the worker is previewing the HIT (hasn't accepted it yet). Potato displays a preview page explaining that they need to accept the HIT to begin working.

### Completion Flow

When workers complete the task, they see a completion page with:
- A "Submit HIT to MTurk" button that POSTs to the `turkSubmitTo` URL
- The completion code (if configured) displayed for reference
- The `assignmentId` is automatically included in the form submission

### Setting Up Your External Question HIT

To use Potato with MTurk, you need to create an External Question HIT. Use this XML format:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">
  <ExternalURL>https://your-server:8080/?workerId=${workerId}&amp;assignmentId=${assignmentId}&amp;hitId=${hitId}&amp;turkSubmitTo=${turkSubmitTo}</ExternalURL>
  <FrameHeight>800</FrameHeight>
</ExternalQuestion>
```

MTurk automatically substitutes the placeholder variables (`${workerId}`, etc.) with actual values.

### Full MTurk Configuration Example

Here's a complete configuration for an MTurk study:

```yaml
# Task identification
annotation_task_name: "Text Classification Task"
task_description: "Classify the sentiment of short texts."

# MTurk login settings
login:
  type: url_direct
  url_argument: workerId

# Optional completion code
completion_code: "TASK_COMPLETE"

# Hide navigation to prevent workers from skipping
hide_navbar: true
jumping_to_id_disabled: true

# Automatic task assignment for crowdsourcing
assignment_strategy: random
max_annotations_per_user: 10
max_annotations_per_item: 3

# Data files
data_files:
  - data/items.json

# Output
output_annotation_dir: annotation_output/
```

### Sandbox vs Production

MTurk provides a sandbox environment for testing. The endpoints are:

| Environment | Worker Site | Submit URL |
|-------------|-------------|------------|
| Sandbox | workersandbox.mturk.com | https://workersandbox.mturk.com/mturk/externalSubmit |
| Production | www.mturk.com | https://www.mturk.com/mturk/externalSubmit |

For testing:
1. Create HITs on the sandbox requester site
2. Access as a worker on the sandbox worker site
3. The `turkSubmitTo` parameter will automatically point to the sandbox

### Advanced: MTurk API Integration

For larger studies, Potato can integrate with the MTurk API via boto3 to automatically manage your HIT:

- List and monitor assignments
- Auto-approve completed assignments
- Track worker status

#### Setup MTurk API

1. **Install boto3**:
```bash
pip install boto3
```

2. **Get AWS credentials** with MTurk permissions from your AWS account

3. **Create an MTurk config file** (`configs/mturk_config.yaml`):

```yaml
aws_access_key_id: "YOUR_AWS_ACCESS_KEY"
aws_secret_access_key: "YOUR_AWS_SECRET_KEY"
sandbox: true  # Set to false for production
hit_id: "YOUR_HIT_ID"  # Optional: for tracking/auto-approval
```

4. **Reference it in your main config**:

```yaml
login:
  type: url_direct
  url_argument: workerId

mturk:
  enabled: true
  config_file_path: configs/mturk_config.yaml
```

> **Security Note**: Never commit AWS credentials to version control. Use environment variables or AWS credential files in production.

---

## Step-by-Step MTurk Setup Guide

### 1. Create Your HIT on MTurk

Go to [MTurk Requester](https://requester.mturk.com/) (or [Sandbox](https://requestersandbox.mturk.com/) for testing).

Create an External Question HIT with:
- Your Potato server URL as the ExternalURL
- Appropriate reward and time settings
- Required qualifications for quality control

### 2. Configure Your Potato Project

Add the MTurk settings to your configuration:

```yaml
login:
  type: url_direct
  url_argument: workerId

completion_code: "COMPLETED"
hide_navbar: true
jumping_to_id_disabled: true
```

### 3. Test in Sandbox

1. Create a HIT in the MTurk sandbox
2. Run your Potato server
3. Access the HIT as a sandbox worker
4. Verify the full workflow:
   - Preview page shows when HIT not accepted
   - Login works when HIT is accepted
   - Completion page has working submit button

### 4. Deploy to Production

Once tested:
1. Deploy your Potato server to a production environment
2. Create production HITs pointing to your server
3. Monitor completions via the admin dashboard

---

## Step-by-Step Prolific Setup Guide

### 1. Create Your Study on Prolific

Go to [Prolific](https://app.prolific.co/) and create a new study. Note your study ID from the URL.

### 2. Configure Your Potato Project

Add the Prolific settings to your configuration:

```yaml
login:
  type: url_direct
  url_argument: PROLIFIC_PID

completion_code: "YOUR-CODE-FROM-PROLIFIC"
hide_navbar: true
jumping_to_id_disabled: true
```

### 3. Set Up Task Assignment

Configure automatic assignment for crowdsourcing:

```yaml
assignment_strategy: random  # or "ordered"
max_annotations_per_user: 10
max_annotations_per_item: 3
```

### 4. Test Locally

Run your project locally and test with a simulated Prolific URL:

```bash
potato start your-project -p 8000
```

Then visit: `http://localhost:8000/?PROLIFIC_PID=test_user`

### 5. Deploy to Server

Upload your project to a server with open ports:

```bash
# On your server
git clone your-repo
cd your-project
potato start . -p 8080
```

### 6. Configure Prolific Study URL

In Prolific, set your study URL to:
```
https://your-server-ip:8080/?PROLIFIC_PID={{%PROLIFIC_PID%}}&SESSION_ID={{%SESSION_ID%}}&STUDY_ID={{%STUDY_ID%}}
```

Prolific will automatically replace the placeholders with actual values.

### 7. Preview and Launch

Use Prolific's preview feature to test the full worker experience, then launch your study!

---

## Troubleshooting

### Workers see "Missing required URL parameter" error

- Ensure your Prolific study URL includes the `PROLIFIC_PID` parameter
- Check that `login.type` is set to `url_direct` or `prolific`

### Workers can't log in

- Verify `require_password` is not set to `true` (it's auto-disabled for URL-direct login)
- Check server logs for authentication errors

### Completion code not showing

- Ensure `completion_code` is set in your config
- Verify workers are reaching the DONE phase

### Prolific API not working

- Verify your API token is correct
- Check that `study_id` matches your actual Prolific study
- Look for error messages in the server logs

### MTurk workers stuck on preview page

- Workers see the preview page when they haven't accepted the HIT yet
- The page auto-refreshes every 3 seconds to check if HIT was accepted
- Ensure your External Question URL includes all required parameters

### MTurk submit button not working

- Verify `turkSubmitTo` parameter is present in the original URL
- Check that the form action URL is correct (sandbox vs production)
- Look for CORS or mixed-content errors in browser console

### MTurk API not connecting

- Verify AWS credentials are correct
- Check that `sandbox` setting matches your environment
- Ensure boto3 is installed: `pip install boto3`
- Verify your AWS account has MTurk requester permissions

---

## Example Projects

Check out these example projects in the [potato-showcase](https://github.com/davidjurgens/potato-showcase) repository:

- **prolific_api_example**: Full Prolific API integration example
- **match_finding**: Simple URL-direct login setup
- **summarization_evaluation**: Crowdsourcing with automatic assignment

Each example includes configuration files you can adapt for your own studies.
