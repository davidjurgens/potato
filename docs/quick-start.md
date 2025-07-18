# Quick Start Guide

This guide will help you get started with Potato annotation tasks using YAML configuration files.

## Installation

### Option 1: Install from PyPI (Recommended)

```bash
pip install potato-annotation
```

### Option 2: Install from GitHub

```bash
git clone https://github.com/davidjurgens/potato.git
cd potato
pip install -r requirements.txt
```

## Creating Your First Annotation Task

### 1. Create a Task Directory

Start by creating a directory for your annotation task:

```bash
mkdir my_annotation_task
cd my_annotation_task
```

### 2. Create Your Data File

Create a data file with your items to annotate. For example, create `data/my_data.json`:

```json
[
  {
    "id": "item_1",
    "text": "This is the first text to annotate."
  },
  {
    "id": "item_2",
    "text": "This is the second text to annotate."
  }
]
```

### 3. Create Your Configuration File

Create a YAML configuration file `config.yaml`:

```yaml
# Basic Configuration
port: 8000
server_name: My First Annotation Task
annotation_task_name: Sentiment Analysis
task_dir: output/my_task/

# Data Configuration
data_files:
  - data/my_data.json
item_properties:
  id_key: id
  text_key: text

# Output Configuration
output_annotation_format: json
annotation_codebook_url: ""

# User Configuration
user_config:
  allow_all_users: true
  users: []
max_annotations_per_user: 10

# Assignment Strategy
assignment_strategy: random
max_annotations_per_item: 3

# Annotation Schemes
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: What is the sentiment of this text?
    labels:
      - positive
      - negative
      - neutral
    sequential_key_binding: true

  - annotation_type: text
    name: comments
    description: Any additional comments about this text?
    multiline: true
    rows: 3
    cols: 50

# Server Configuration
server:
  port: 8000
  host: "0.0.0.0"
  require_password: false
  persist_sessions: false

# Template Configuration
site_dir: default
use_dedicated_layout: true
customjs: null
customjs_hostname: null

# Alert Configuration
alert_time_each_instance: 10000000
```

### 4. Launch the Server

Start your annotation server:

```bash
python -m potato.flask_server start config.yaml
```

The server will be available at `http://localhost:8000`.

## Task Directory Structure

When you run Potato, it creates the following directory structure:

```
my_annotation_task/
├── config.yaml              # Your configuration file
├── data/
│   └── my_data.json         # Your data file
├── output/
│   └── my_task/             # Task directory (created by Potato)
│       ├── layouts/         # Generated layout files
│       │   └── task_layout.html
│       ├── annotations/     # Annotation output files
│       │   ├── all_annotations.json
│       │   └── user_annotations/
│       └── state/          # Server state files
└── README.md               # Optional: task documentation
```

## Available Annotation Types

Potato supports multiple annotation types. Here are some common examples:

### Radio Buttons (Single Choice)
```yaml
annotation_schemes:
  - annotation_type: radio
    name: category
    description: Select the category that best describes this text
    labels:
      - news
      - opinion
      - review
    sequential_key_binding: true
```

### Checkboxes (Multiple Choice)
```yaml
annotation_schemes:
  - annotation_type: multiselect
    name: topics
    description: What topics are mentioned? (Select all that apply)
    labels:
      - politics
      - technology
      - sports
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
    size: 5
```

### Text Input
```yaml
annotation_schemes:
  - annotation_type: text
    name: summary
    description: Please provide a brief summary
    multiline: true
    rows: 4
    cols: 60
```

## Assignment Strategies

Potato supports different strategies for assigning items to annotators:

- **`random`**: Assigns items randomly
- **`fixed_order`**: Assigns items in the order they appear in the dataset
- **`least_annotated`**: Prioritizes items with the fewest annotations
- **`max_diversity`**: Prioritizes items with highest disagreement

Example:
```yaml
assignment_strategy: least_annotated
max_annotations_per_item: 3
```

## Advanced Configuration

For more complex tasks, you can:

- Add multiple annotation schemes
- Configure SurveyFlow for pre/post annotation surveys
- Set up active learning
- Customize the UI layout
- Add keyboard shortcuts

See the [Configuration Guide](configuration.md) for complete documentation.

## Example Projects

If you want to see working examples, check out the project templates:

```bash
# List available templates
potato list all

# Get a specific template
potato get sentiment_analysis

# Start a template project
potato start sentiment_analysis
```

## Next Steps

1. **Customize your configuration**: Modify the YAML file to match your annotation needs
2. **Add more data**: Expand your data file with more items
3. **Test thoroughly**: Try annotating a few items to ensure everything works
4. **Deploy**: Set up the server for your annotators to access

For detailed configuration options, see the [Configuration Guide](configuration.md).
