# Configuration Guide

This document provides a comprehensive guide to configuring Potato annotation tasks using YAML configuration files. Potato uses YAML files to define all aspects of an annotation task, from server settings to annotation schemes and user management.

## Table of Contents

1. [Basic Configuration](#basic-configuration)
2. [Server Configuration](#server-configuration)
3. [Data Configuration](#data-configuration)
4. [Annotation Schemes](#annotation-schemes)
5. [User Management](#user-management)
6. [Assignment Strategies](#assignment-strategies)
7. [UI and Layout Configuration](#ui-and-layout-configuration)
8. [Advanced Features](#advanced-features)
9. [Complete Example](#complete-example)

## Basic Configuration

### Core Settings

```yaml
# Server identification
server_name: My Annotation Task
annotation_task_name: Sentiment Analysis Task

# Root directory for your task's design and output
task_dir: my_task/

# Port for the server to run on
port: 8000
```

**Key Options:**
- **`server_name`**: Display name for the server (shown in browser title)
- **`annotation_task_name`**: Name of the annotation task (shown to annotators)
- **`port`**: Port number for the server (default: 8000)
- **`task_dir`**: The root directory for the task and all of the custom layout, data, and annotations will be placed in this directory.

## Server Configuration

### Basic Server Settings

```yaml
server:
  port: 8000
  host: "0.0.0.0"  # Listen on all interfaces
  require_password: true
  persist_sessions: false
```

### Advanced Server Settings

```yaml
customjs: null  # Path to custom JavaScript file
customjs_hostname: null  # Hostname for custom JS
site_dir: default  # or path to custom template directory
alert_time_each_instance: 10  # Seconds before alert (very high = disabled)
```

## Data Configuration

### Input Data

```yaml
data_files:
  - data/my_data.json
  - data/another_dataset.csv

item_properties:
  id_key: id           # Field name for item ID
  text_key: text       # Field name for item text
  context_key: context # Optional: field name for context
  kwargs:              # Optional: additional fields to pass to templates
    - metadata
    - source
```

### Output Configuration

```yaml
output_annotation_dir: your_task_dir/annotations/
output_annotation_format: json  # Options: json, jsonl, csv, tsv
annotation_codebook_url: https://docs.google.com/document/d/...
```

## Annotation Schemes

Potato supports multiple annotation types. Each scheme defines one annotation question or task.

### Radio Button (Single Choice)

```yaml
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: What is the sentiment of this text?
    labels:
      - positive
      - negative
      - neutral
    sequential_key_binding: true  # Enable keyboard shortcuts (1, 2, 3)
    horizontal: false             # Display horizontally
    has_free_response:
      instruction: Please specify other sentiment:
```

### Multiselect (Multiple Choice)

```yaml
annotation_schemes:
  - annotation_type: multiselect
    name: topics
    description: What topics are mentioned? (Select all that apply)
    labels:
      - politics
      - technology
      - sports
      - entertainment
    sequential_key_binding: true
    has_free_response:
      instruction: Other topics:
```

### Likert Scale

```yaml
annotation_schemes:
  - annotation_type: likert
    name: quality
    description: How would you rate the quality of this text?
    min_label: Very Poor
    max_label: Excellent
    size: 5  # Number of scale points
    sequential_key_binding: true
```

### Text Input

```yaml
annotation_schemes:
  - annotation_type: text
    name: summary
    description: Please provide a brief summary:
    multiline: true
    rows: 4
    cols: 60
    allow_paste: true  # Allow pasting (default: true)
```

### Slider

```yaml
annotation_schemes:
  - annotation_type: slider
    name: confidence
    description: How confident are you in your assessment?
    min: 0
    max: 10
    step: 1
    min_label: Not Confident
    max_label: Very Confident
```

### Number Input

```yaml
annotation_schemes:
  - annotation_type: number
    name: word_count
    description: How many words are in this text?
    min: 0
    max: 1000
    step: 1
```

### Select Dropdown

```yaml
annotation_schemes:
  - annotation_type: select
    name: category
    description: Select the most appropriate category:
    labels:
      - News
      - Opinion
      - Review
      - Tutorial
      - Story
```

### Span Annotation (Text Highlighting)

```yaml
annotation_schemes:
  - annotation_type: span
    name: sentiment_spans
    description: Highlight text spans with different sentiments
    labels:
      - positive
      - negative
      - neutral
    colors:  # Optional: custom colors for each label
      positive: "#4CAF50"
      negative: "#f44336"
      neutral: "#9E9E9E"
    bad_text_label:  # Optional: checkbox for invalid text
      label_content: No answer
```

### Multirate (Matrix Rating)

```yaml
annotation_schemes:
  - annotation_type: multirate
    name: quality_ratings
    description: Rate the following aspects:
    display_config:
      num_columns: 1
    options:
      - Clarity
      - Accuracy
      - Relevance
    labels:
      - Strongly Disagree
      - Disagree
      - Neutral
      - Agree
      - Strongly Agree
    label_requirement:
      required: true
    option_randomization: false
    sequential_key_binding: true
```

### Video/GIF Labels

```yaml
annotation_schemes:
  - annotation_type: multiselect
    name: gif_reply
    video_as_label: true
    description: Select appropriate GIF replies
    labels:
      - name: "{{instance_obj.gifs[0]}}"
        videopath: /files/{{instance_obj.gifs_path[0]}}
      - name: "{{instance_obj.gifs[1]}}"
        videopath: /files/{{instance_obj.gifs_path[1]}}
```

## User Management

### Basic User Configuration

```yaml
user_config:
  allow_all_users: true  # Allow any user to register
  users: []             # Pre-defined users (empty = none)
```

### Advanced User Settings

```yaml
max_annotations_per_user: 10  # Maximum annotations per user

login:
  type: url_direct           # Login type
  url_argument: PROLIFIC_PID # URL parameter for user ID

jumping_to_id_disabled: true   # Disable go-to instance feature
hide_navbar: true              # Hide navigation bar
```

## Database Configuration

### MySQL Database Setup

Potato supports MySQL database backend for improved performance and scalability. To use MySQL:

```yaml
database:
  type: mysql
  host: localhost
  port: 3306
  database: potato_annotations
  username: potato_user
  password: ${POTATO_DB_PASSWORD}  # Use environment variable for security
  charset: utf8mb4
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600
```

### Database Configuration Options

- **`type`**: Database type (`mysql` or `file` for file-based storage)
- **`host`**: Database server hostname
- **`port`**: Database server port (default: 3306)
- **`database`**: Database name
- **`username`**: Database username
- **`password`**: Database password (use environment variables for security)
- **`charset`**: Character encoding (default: utf8mb4)
- **`pool_size`**: Connection pool size (default: 10)
- **`max_overflow`**: Maximum overflow connections (default: 20)
- **`pool_timeout`**: Connection timeout in seconds (default: 30)
- **`pool_recycle`**: Connection recycle time in seconds (default: 3600)

### Environment Variables

For security, use environment variables for database credentials:

```bash
export POTATO_DB_PASSWORD="your_secure_password"
```

Then reference it in your config:

```yaml
database:
  password: ${POTATO_DB_PASSWORD}
```

### Database Setup

1. **Create Database**:
   ```sql
   CREATE DATABASE potato_annotations CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

2. **Create User**:
   ```sql
   CREATE USER 'potato_user'@'localhost' IDENTIFIED BY 'your_password';
   GRANT ALL PRIVILEGES ON potato_annotations.* TO 'potato_user'@'localhost';
   FLUSH PRIVILEGES;
   ```

3. **Tables**: Potato will automatically create the required tables on first startup.

### Migration from File-Based Storage

To migrate existing annotations from file-based to database storage:

1. Backup your existing annotation data
2. Configure the database connection
3. Start Potato with the new configuration
4. Existing data will be loaded from files and stored in the database

### Performance Considerations

- **Connection Pooling**: Adjust `pool_size` based on expected concurrent users
- **Indexing**: Database tables include appropriate indexes for common queries
- **Backup**: Regular database backups are recommended for production use

## Assignment Strategies

Potato supports multiple strategies for assigning items to annotators.

### Strategy Configuration

```yaml
assignment_strategy: random  # Options: random, fixed_order, least_annotated, max_diversity

# Alternative: nested configuration
assignment:
  strategy: random
  max_annotations_per_item: 3
  random_seed: 1234
```

### Available Strategies

- `random`: Assigns items randomly to annotators
- `fixed_order`: Assigns items in the order they appear in the dataset
- `least_annotated`: Prioritizes items with the fewest annotations
- `max_diversity`: Prioritizes items with highest disagreement in existing annotations
- `active_learning`: Uses ML to prioritize uncertain items (placeholder)
- `llm_confidence`: Uses LLM confidence scores (placeholder)

### Legacy Assignment Configuration

```yaml
automatic_assignment:
  on: true
  output_filename: task_assignment.json
  sampling_strategy: random  # random or ordered
  labels_per_instance: 3
  instance_per_annotator: 5
  test_question_per_annotator: 0
```

## UI and Layout Configuration

### Template Selection

```yaml
html_layout: default  # Options: default, fixed_keybinding, kwargs, or custom path
surveyflow_html_layout: default

task_layout: templates/my_layout.html
use_dedicated_layout: true  # Generate annotation_layout.html file
```

### UI Customization

```yaml
ui:
  show_progress: true
  show_instructions: true
  allow_navigation: true
  allow_editing: true
```

### Keyboard Shortcuts

```yaml
horizontal_key_bindings: true
sequential_key_binding: true
```

## Advanced Features

### SurveyFlow Configuration

```yaml
surveyflow:
  on: true
  order:
    - pre_annotation
    - post_annotation
  pre_annotation:
    - surveyflow/intro.jsonl
    - surveyflow/instruction.jsonl
    - surveyflow/consent.jsonl
  post_annotation:
    - surveyflow/experience.jsonl
    - surveyflow/demographic_questions.jsonl
    - surveyflow/end.jsonl
  testing:
    - surveyflow/testing.jsonl
```

### Prestudy Configuration

```yaml
prestudy:
  on: true
  minimum_score: 0.8
  groundtruth_key: whether_match
  question_key: Whether the presented sentences are discussing the same scientific finding
  answer_mapping:
    Yes: true
    No: false
  pass_page: surveyflow/prestudy_pass.jsonl
  fail_page: surveyflow/prestudy_fail.jsonl
```

### Active Learning

```yaml
active_learning_config:
  enable_active_learning: true
  classifier_name: sklearn.linear_model.LogisticRegression
  classifier_kwargs: {}
  vectorizer_name: sklearn.feature_extraction.text.CountVectorizer
  vectorizer_kwargs: {}
  resolution_strategy: random
  random_sample_percent: 50
  active_learning_schema:
    - sentiment
  update_rate: 5
  max_inferred_predictions: 20
```

### List as Text Configuration

```yaml
list_as_text:
  text_list_prefix_type: alphabet  # Options: alphabet, number, none
  horizontal: true
```

### Keyword Highlights

```yaml
keyword_highlights_file: frame_keywords.tsv
```

## Complete Example

Here's a complete configuration file that demonstrates most features:

```yaml
# Basic Configuration
port: 8000
server_name: Comprehensive Annotation Task
annotation_task_name: Multi-Modal Text Analysis

data_files:
  - data/my_dataset.json
item_properties:
  id_key: id
  text_key: text
  context_key: context

task_dir: output/comprehensive_task/
output_annotation_format: json
annotation_codebook_url: https://docs.google.com/document/d/...

user_config:
  allow_all_users: true
  users: []
max_annotations_per_user: 20

assignment_strategy: least_annotated
max_annotations_per_item: 3

annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: What is the overall sentiment of this text?
    labels:
      - positive
      - negative
      - neutral
    sequential_key_binding: true

  - annotation_type: multiselect
    name: topics
    description: What topics are mentioned? (Select all that apply)
    labels:
      - politics
      - technology
      - sports
      - entertainment
      - science
    has_free_response:
      instruction: Other topics:
    sequential_key_binding: true

  - annotation_type: likert
    name: quality
    description: How would you rate the quality of this text?
    min_label: Very Poor
    max_label: Excellent
    size: 5
    sequential_key_binding: true

  - annotation_type: text
    name: summary
    description: Please provide a brief summary of this text:
    multiline: true
    rows: 4
    cols: 60

  - annotation_type: slider
    name: confidence
    description: How confident are you in your assessment?
    min: 0
    max: 10
    step: 1
    min_label: Not Confident
    max_label: Very Confident

  - annotation_type: select
    name: category
    description: Select the most appropriate category:
    labels:
      - News
      - Opinion
      - Review
      - Tutorial
      - Story

  - annotation_type: number
    name: word_count
    description: How many words are in this text?
    min: 0
    max: 10
    step: 1

ui:
  show_progress: true
  show_instructions: true
  allow_navigation: true
  allow_editing: true

server:
  port: 8000
  host: 0.0.0.0
  require_password: true
  persist_sessions: false

assignment:
  strategy: least_annotated
  max_annotations_per_item: 3
  random_seed: 1234

site_dir: default
use_dedicated_layout: true
customjs: null
customjs_hostname: null

alert_time_each_instance: 10000000
```

## Configuration Validation

When you start Potato with a configuration file, it will validate the configuration and report any errors. Common issues include:

- Missing required fields
- Invalid annotation types
- File paths that dont exist
- Invalid assignment strategies
- Malformed YAML syntax

## Best Practices
1. **Start Simple**: Begin with basic configuration and add complexity gradually
2. **Test Thoroughly**: Always test your configuration with a small dataset first
3. **Use Descriptive Names**: Choose clear, descriptive names for annotation schemes
4. **Document Your Choices**: Add comments to explain non-obvious configuration choices
5. **Version Control**: Keep your configuration files in version control
6. **Environment Variables**: Use environment variables for sensitive information
7. **Backup Data**: Always backup your data and configuration before making changes

## Troubleshooting

### Common Issues
1. **Port Already in Use**: Change the port number in your configuration
2. **File Not Found**: Check that all file paths are correct and files exist
3. **Invalid YAML**: Use a YAML validator to check syntax
4. **Permission Errors**: Ensure Potato has read/write access to directories
5. **Template Errors**: Check that template files exist and are valid HTML
