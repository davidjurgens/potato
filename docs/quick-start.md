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

**Important**: Your configuration file must be located within the `task_dir` that you specify in the configuration. This is a security requirement.

Create a YAML configuration file `config.yaml` in your task directory:

```yaml
# Basic Configuration
port: 8000
server_name: My First Annotation Task
annotation_task_name: Sentiment Analysis
task_dir: .  # Resolves to the directory containing this config file

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
  host: 0.0.0.0
  require_password: true
  persist_sessions: false

# Optional: Custom UI settings
site_dir: default
customjs: null
customjs_hostname: null
alert_time_each_instance: 10000000
```

### 4. Start the Server

Start the annotation server with your configuration:

```bash
# From the parent directory of your task
python potato/flask_server.py start my_annotation_task/config.yaml -p 8000
```

## Project Structure

Your final project structure should look like this:

```
my_annotation_task/
├── config.yaml              # ✅ Config file in task_dir
├── data/
│   └── my_data.json         # Your annotation data
├── output/                  # Will be created automatically
│   └── annotations/         # Annotation results
└── templates/               # Optional: custom templates
    └── custom_layout.html
```

## Alternative: Multiple Config Files

If you want to have multiple configuration files for different experiments, you can use a `configs/` subdirectory:

```
my_annotation_task/
├── configs/
│   ├── experiment1.yaml     # ✅ Config files in configs/
│   └── experiment2.yaml
├── data/
│   └── my_data.json
└── output/
    └── annotations/
```

In this case, your config files should use `task_dir: ..` to point to the parent directory:

```yaml
task_dir: ..  # Resolves to my_annotation_task/ (parent of configs/)
data_files:
  - data/my_data.json
```

Then start the server with:

```bash
# Start with project directory (will prompt to choose config)
python potato/flask_server.py start my_annotation_task/ -p 8000

# Or start with a specific config file
python potato/flask_server.py start my_annotation_task/configs/experiment1.yaml -p 8000
```

## Path Resolution

### Task Directory

The `task_dir` setting is resolved relative to the config file's directory. This makes configurations portable:

| `task_dir` Value | Config File Location | Resolved `task_dir` |
|------------------|---------------------|---------------------|
| `.` | `my_task/config.yaml` | `my_task/` |
| `..` | `my_task/configs/config.yaml` | `my_task/` |

### Other Paths

All other relative paths in your configuration are resolved relative to the `task_dir`:

- `data/my_data.json` → `{task_dir}/data/my_data.json`
- `output/annotations/` → `{task_dir}/output/annotations/`
- `templates/` → `{task_dir}/templates/`

## Common Issues and Solutions

### "Configuration file must be in the task_dir"
- **Problem**: Your config file is outside the `task_dir` specified in the YAML
- **Solution**: Move the config file into the `task_dir` or update the `task_dir` path

### "Data file not found"
- **Problem**: A referenced data file doesn't exist
- **Solution**: Check that the file path is correct relative to the `task_dir`

### "Missing required configuration fields"
- **Problem**: Required fields are missing from your config
- **Solution**: Ensure all required fields are present (see configuration guide for details)
