# Amazon Mechanical Turk Integration Guide

This guide provides comprehensive instructions for deploying Potato annotation tasks on Amazon Mechanical Turk (MTurk).

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Configuration Reference](#configuration-reference)
5. [Creating HITs on MTurk](#creating-hits-on-mturk)
6. [Testing in Sandbox](#testing-in-sandbox)
7. [Production Deployment](#production-deployment)
8. [MTurk API Integration](#mturk-api-integration)
9. [Best Practices](#best-practices)
10. [Troubleshooting](#troubleshooting)
11. [FAQ](#faq)

---

## Overview

Potato integrates with Amazon Mechanical Turk through the External Question HIT type. This allows you to:

- Host your annotation interface on your own server
- Automatically authenticate workers using their MTurk worker ID
- Handle HIT preview mode gracefully
- Submit completed work back to MTurk seamlessly

### How It Works

1. You create an External Question HIT on MTurk pointing to your Potato server
2. Workers click on your HIT and are redirected to your Potato server with URL parameters
3. Potato extracts the worker ID and other parameters from the URL
4. Workers complete the annotation task
5. Upon completion, workers click "Submit HIT to MTurk" which POSTs to MTurk's servers

### URL Parameters

MTurk passes four parameters to your External Question URL:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `workerId` | Worker's unique MTurk identifier | `A1B2C3D4E5F6G7` |
| `assignmentId` | Unique ID for this worker-HIT pair | `3XJOUITW8UFLC7...` |
| `hitId` | The HIT identifier | `3ZZRZH8GRFW4N...` |
| `turkSubmitTo` | URL where completion form should POST | `https://www.mturk.com/mturk/externalSubmit` |

---

## Prerequisites

### Server Requirements

1. **Publicly accessible server** with:
   - Open port (typically 8080 or 443)
   - HTTPS recommended (required for some browsers)
   - Stable internet connection

2. **Python environment** with Potato installed:
   ```bash
   pip install potato-annotation
   # or from source
   pip install -e .
   ```

### MTurk Requirements

1. **MTurk Requester Account**: Sign up at [requester.mturk.com](https://requester.mturk.com)
2. **Funded Account**: Add funds for production (sandbox is free)
3. **AWS Account** (optional): For API integration features

---

## Quick Start

### Step 1: Create Your Potato Configuration

Create a YAML configuration file for your annotation task:

```yaml
# mturk_task.yaml

annotation_task_name: "Sentiment Classification"
task_description: "Classify the sentiment of short text snippets."

# MTurk login configuration
login:
  type: url_direct
  url_argument: workerId

# Optional completion code
completion_code: "TASK_COMPLETE"

# Crowdsourcing settings
hide_navbar: true
jumping_to_id_disabled: true
assignment_strategy: random
max_annotations_per_user: 10
max_annotations_per_item: 3

# Task directories
task_dir: .
output_annotation_dir: annotation_output/

# Data files
data_files:
  - data/items.json

# Annotation scheme
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "What is the sentiment of this text?"
    labels:
      - positive
      - neutral
      - negative
```

### Step 2: Start Your Potato Server

```bash
# Start the server
potato start mturk_task.yaml -p 8080

# Or with HTTPS (recommended)
potato start mturk_task.yaml -p 443 --ssl-cert cert.pem --ssl-key key.pem
```

### Step 3: Test Locally

Test the MTurk URL parameters locally:

```bash
# Test normal workflow
curl "http://localhost:8080/?workerId=TEST_WORKER&assignmentId=TEST_ASSIGNMENT&hitId=TEST_HIT&turkSubmitTo=https://workersandbox.mturk.com/mturk/externalSubmit"

# Test preview mode
curl "http://localhost:8080/?workerId=TEST_WORKER&assignmentId=ASSIGNMENT_ID_NOT_AVAILABLE&hitId=TEST_HIT"
```

### Step 4: Create Your HIT on MTurk

Create an External Question HIT (see [Creating HITs on MTurk](#creating-hits-on-mturk) section).

---

## Configuration Reference

### Required Settings

```yaml
# Login configuration for MTurk
login:
  type: url_direct      # Required: enables URL-based authentication
  url_argument: workerId  # Required: MTurk uses 'workerId' parameter
```

### Recommended Settings

```yaml
# Hide navigation to prevent workers from skipping
hide_navbar: true
jumping_to_id_disabled: true

# Crowdsourcing assignment
assignment_strategy: random  # or "ordered"
max_annotations_per_user: 10  # Limit per worker
max_annotations_per_item: 3   # Redundancy for quality

# Task description (shown in preview)
task_description: "Brief description of your task for the preview page."

# Optional completion code
completion_code: "YOUR_CODE"
```

### Optional: MTurk API Integration

```yaml
# Enable MTurk API features (requires boto3)
mturk:
  enabled: true
  config_file_path: configs/mturk_config.yaml
```

MTurk config file (`configs/mturk_config.yaml`):

```yaml
aws_access_key_id: "YOUR_ACCESS_KEY"
aws_secret_access_key: "YOUR_SECRET_KEY"
sandbox: true  # false for production
hit_id: "YOUR_HIT_ID"  # Optional: for tracking
```

---

## Creating HITs on MTurk

### Using the MTurk Requester Website

1. Go to [MTurk Requester](https://requester.mturk.com) (or [Sandbox](https://requestersandbox.mturk.com))
2. Click "Create" → "New Project"
3. Select "Other" as the project template
4. Fill in project details:
   - **Project Name**: Your task name
   - **Title**: What workers see in search
   - **Description**: Detailed task description
   - **Keywords**: Help workers find your HIT
   - **Reward**: Payment per assignment
   - **Time Allotted**: How long workers have
   - **Auto-approve**: When to auto-approve (e.g., 7 days)

5. In the "Design Layout" step, select "Source" and paste your External Question XML:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">
  <ExternalURL>https://your-server.com:8080/?workerId=${workerId}&amp;assignmentId=${assignmentId}&amp;hitId=${hitId}&amp;turkSubmitTo=${turkSubmitTo}</ExternalURL>
  <FrameHeight>800</FrameHeight>
</ExternalQuestion>
```

**Important**:
- Use `&amp;` instead of `&` in XML
- Adjust `FrameHeight` based on your interface (600-900 typical)
- Use HTTPS if possible

### Using boto3 (Programmatic)

```python
import boto3

# Create MTurk client
mturk = boto3.client(
    'mturk',
    region_name='us-east-1',
    endpoint_url='https://mturk-requester-sandbox.us-east-1.amazonaws.com'  # Remove for production
)

# External Question XML
question_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">
  <ExternalURL>https://your-server.com:8080/?workerId=${workerId}&amp;assignmentId=${assignmentId}&amp;hitId=${hitId}&amp;turkSubmitTo=${turkSubmitTo}</ExternalURL>
  <FrameHeight>800</FrameHeight>
</ExternalQuestion>'''

# Create HIT
response = mturk.create_hit(
    Title='Sentiment Classification Task',
    Description='Classify the sentiment of short text snippets.',
    Keywords='sentiment, classification, text, NLP',
    Reward='0.50',
    MaxAssignments=100,
    LifetimeInSeconds=86400,  # 24 hours
    AssignmentDurationInSeconds=3600,  # 1 hour
    AutoApprovalDelayInSeconds=604800,  # 7 days
    Question=question_xml
)

print(f"Created HIT: {response['HIT']['HITId']}")
```

---

## Testing in Sandbox

Always test in the MTurk Sandbox before going to production.

### Sandbox URLs

| Service | URL |
|---------|-----|
| Requester | https://requestersandbox.mturk.com |
| Worker | https://workersandbox.mturk.com |
| API Endpoint | https://mturk-requester-sandbox.us-east-1.amazonaws.com |

### Testing Workflow

1. **Create a Sandbox Requester Account**
   - Use your regular MTurk requester credentials
   - Sandbox is separate from production

2. **Create a Sandbox Worker Account**
   - Create a separate Amazon account for testing
   - Register as a worker at workersandbox.mturk.com

3. **Create Test HIT**
   - Create your HIT on the sandbox requester site
   - Use the sandbox submit URL in your XML

4. **Test as Worker**
   - Log in to sandbox worker site
   - Find and accept your HIT
   - Verify:
     - Preview page shows when HIT not accepted
     - Login works after accepting HIT
     - Annotations are saved correctly
     - Submit button works and HIT completes

5. **Verify Submission**
   - Check the requester dashboard for submitted assignments
   - Verify worker answers are recorded

### Local Testing Without MTurk

You can test the full workflow locally:

```bash
# Start your server
potato start mturk_task.yaml -p 8000

# In browser, visit:
# Preview mode:
http://localhost:8000/?workerId=test123&assignmentId=ASSIGNMENT_ID_NOT_AVAILABLE&hitId=hit123

# Normal mode (simulates accepted HIT):
http://localhost:8000/?workerId=test123&assignmentId=assign123&hitId=hit123&turkSubmitTo=https://workersandbox.mturk.com/mturk/externalSubmit
```

---

## Production Deployment

### Checklist Before Going Live

- [ ] Tested thoroughly in sandbox
- [ ] Server has HTTPS certificate
- [ ] Server can handle expected load
- [ ] Backup system for annotations
- [ ] Monitoring/alerting in place
- [ ] Clear instructions for workers
- [ ] Quality control measures defined
- [ ] Budget calculated and funded

### Server Recommendations

1. **Use HTTPS**: Many browsers require HTTPS for forms
2. **Handle Concurrent Users**: Use gunicorn or similar:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:8080 "potato.flask_server:create_app('config.yaml')"
   ```
3. **Set Up Logging**: Monitor for errors
4. **Database Backups**: Regular backups of annotation data

### Production External Question URL

```xml
<ExternalURL>https://your-domain.com/?workerId=${workerId}&amp;assignmentId=${assignmentId}&amp;hitId=${hitId}&amp;turkSubmitTo=${turkSubmitTo}</ExternalURL>
```

Note: Production uses `https://www.mturk.com/mturk/externalSubmit` as the submit URL (MTurk provides this automatically).

---

## MTurk API Integration

Potato includes optional MTurk API integration for advanced features.

### Installation

```bash
pip install boto3
```

### Configuration

Create `configs/mturk_config.yaml`:

```yaml
# AWS credentials (or use environment variables/credentials file)
aws_access_key_id: "AKIAIOSFODNN7EXAMPLE"
aws_secret_access_key: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

# Environment
sandbox: true  # Set to false for production

# Optional: HIT to track
hit_id: "3XJOUITW8UFLC..."
```

Enable in your main config:

```yaml
mturk:
  enabled: true
  config_file_path: configs/mturk_config.yaml
```

### Available API Features

```python
from potato.server_utils.mturk_apis import get_mturk_hit

# Get the MTurk manager
mturk = get_mturk_hit()

if mturk:
    # Get account balance
    balance = mturk.get_account_balance()

    # List pending assignments
    pending = mturk.get_pending_assignments()

    # Auto-approve all pending
    count = mturk.auto_approve_all("Thank you!")

    # Get HIT info
    info = mturk.get_basic_hit_info()
```

### Security Best Practices

1. **Never commit credentials** to version control
2. Use environment variables or AWS credentials file:
   ```bash
   export AWS_ACCESS_KEY_ID="your_key"
   export AWS_SECRET_ACCESS_KEY="your_secret"
   ```
3. Use IAM roles with minimal permissions
4. Rotate credentials regularly

---

## Best Practices

### Task Design

1. **Clear Instructions**: Provide detailed examples
2. **Reasonable Time**: Don't rush workers
3. **Fair Pay**: At least minimum wage equivalent
4. **Manageable Length**: 5-15 minutes per HIT is ideal

### Quality Control

1. **Qualification Tests**: Screen workers upfront
2. **Attention Checks**: Include verification questions
3. **Redundancy**: Multiple workers per item (3+ recommended)
4. **Review Samples**: Manually check a subset

### Worker Communication

1. **Contact Info**: Provide a way to ask questions
2. **Clear Rejection Policy**: Explain criteria upfront
3. **Prompt Payment**: Approve quickly when possible

### Technical

1. **Handle Edge Cases**: Workers may reload, go back, etc.
2. **Save Progress**: Autosave if possible
3. **Graceful Errors**: Show helpful error messages
4. **Mobile Friendly**: Some workers use mobile devices

---

## Troubleshooting

### Workers See Preview Page After Accepting

**Symptom**: Workers stuck on "Accept the HIT to begin" page

**Solutions**:
- Verify the `assignmentId` parameter is being passed correctly
- Check for URL encoding issues
- Ensure the HIT URL includes all parameters
- The preview page auto-refreshes; ask workers to wait

### Submit Button Doesn't Work

**Symptom**: Clicking "Submit HIT to MTurk" does nothing

**Solutions**:
- Check browser console for errors
- Verify `turkSubmitTo` parameter is present
- Ensure form action URL is correct
- Check for CORS or mixed-content (HTTP/HTTPS) issues
- Try a different browser

### Workers Can't Log In

**Symptom**: Error about missing URL parameter

**Solutions**:
- Verify `login.url_argument` is set to `workerId`
- Check the External Question URL includes `workerId=${workerId}`
- Ensure `login.type` is `url_direct`

### Assignments Not Appearing

**Symptom**: Workers complete task but assignment not submitted

**Solutions**:
- Verify the form POSTs to `turkSubmitTo` URL
- Check that `assignmentId` is included in form
- Look for JavaScript errors in browser console
- Test the full flow in sandbox first

### API Connection Failed

**Symptom**: MTurk API features not working

**Solutions**:
- Verify boto3 is installed: `pip install boto3`
- Check AWS credentials are correct
- Verify `sandbox` setting matches environment
- Ensure AWS account has MTurk permissions
- Check endpoint URL (sandbox vs production)

### Server Errors

**Symptom**: 500 errors or server crashes

**Solutions**:
- Check server logs for stack traces
- Verify all config files exist
- Ensure data files are accessible
- Check disk space and memory

---

## FAQ

### How much should I pay workers?

Aim for at least $12-15/hour equivalent. Calculate based on:
- Average completion time
- Task complexity
- Market rates for similar tasks

### Can I reject work?

Yes, but:
- Have clear rejection criteria upfront
- Only reject for obvious issues (spam, random clicking)
- Your rejection rate affects worker willingness

### How do I handle worker questions?

Options:
- Include contact email in instructions
- Use MTurk's messaging system
- Create a FAQ document

### Can I use Potato without a server?

No, Potato requires a server. Options:
- Cloud hosting (AWS, GCP, Azure)
- University servers
- Services like Heroku or Render

### How do I ensure data quality?

1. Use qualification tests
2. Include attention checks
3. Require multiple annotations per item
4. Review and approve/reject manually
5. Use agreement metrics to identify issues

### What if my server goes down during a HIT?

- Workers won't be able to submit
- You may need to extend the HIT or create makeup HITs
- Consider auto-save functionality
- Have monitoring/alerts in place

### Can workers do the task multiple times?

By default, MTurk only allows one assignment per worker per HIT. To allow multiple:
- Create multiple HITs
- Use different HIT Groups
- Configure `max_annotations_per_user` in Potato

### How do I handle international workers?

- Consider language requirements
- Be aware of timezone differences
- Payment is in USD
- Some countries have limited MTurk access

---

## Additional Resources

- [MTurk Requester Documentation](https://docs.aws.amazon.com/mturk/)
- [boto3 MTurk Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/mturk.html)
- [Potato Documentation](https://potato-annotation.readthedocs.io/)
- [MTurk Best Practices](https://blog.mturk.com/tutorial-best-practices-for-using-mturk-requester-website-9c4c4c4d5e32)
