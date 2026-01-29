# Config File Structure and Validation

This document explains the requirements for Potato configuration files, including where they should be placed, how paths are resolved, and what validation is performed.

## Overview

Potato uses YAML configuration files to define annotation tasks. These files must follow specific structural requirements to ensure security and proper functionality.

## Config File Location Requirements

### Core Requirement

**Your YAML configuration file must be located within the `task_dir` specified in the configuration.**

This is a security requirement that ensures all project files are properly contained within the specified task directory.

### Valid Config File Structures

#### Structure 1: Config File in Task Directory (Recommended)

```
my_annotation_project/
├── config.yaml                    # ✅ Config file in task_dir
├── data/
│   └── my_data.json
├── output/
│   └── annotations/
└── templates/
    └── custom_layout.html
```

With this structure, your `config.yaml` would contain:
```yaml
task_dir: my_annotation_project/
data_files:
  - data/my_data.json
output_annotation_dir: output/annotations/
# ... other configuration
```

#### Structure 2: Config File with task_dir='.' (Recommended for Portability)

Using `task_dir: .` makes your configuration portable because paths are resolved relative to the config file's location.

```
my_annotation_project/
├── config.yaml                    # ✅ Config file with task_dir: .
├── data/
│   └── my_data.json
├── output/
│   └── annotations/
└── templates/
    └── custom_layout.html
```

With this structure, your `config.yaml` would contain:
```yaml
task_dir: .                        # Resolves to my_annotation_project/
data_files:
  - data/my_data.json
output_annotation_dir: output/annotations/
# ... other configuration
```

This approach is portable - you can move the entire `my_annotation_project/` folder anywhere and it will still work.

#### Structure 3: Config Files in Configs Subdirectory

```
my_annotation_project/
├── configs/
│   ├── experiment1.yaml           # ✅ Config files in configs/
│   └── experiment2.yaml
├── data/
│   └── my_data.json
└── output/
    └── annotations/
```

With this structure, your config files would contain:
```yaml
task_dir: ..                       # Resolves to my_annotation_project/ (parent of configs/)
data_files:
  - data/my_data.json
output_annotation_dir: output/annotations/
# ... other configuration
```

**Note**: `task_dir: ..` is resolved relative to the config file's directory (`configs/`), so it becomes `my_annotation_project/`.

### Invalid Config File Structures

#### ❌ Config File Outside Task Directory

```
my_annotation_project/
├── config.yaml                    # ❌ Config file outside task_dir
└── task_data/
    ├── data/
    │   └── my_data.json
    └── output/
        └── annotations/
```

If `config.yaml` contains `task_dir: task_data/`, this will fail validation because the config file is not within the specified task directory.

## Starting the Server

### Option 1: Direct Config File (Recommended)

```bash
# Start with a specific config file
python potato/flask_server.py start my_annotation_project/config.yaml -p 8000
```

### Option 2: Project Directory (Multiple Configs)

```bash
# Start with a project directory (will prompt to choose config if multiple exist)
python potato/flask_server.py start my_annotation_project/ -p 8000
```

## Path Resolution Rules

### Task Directory Resolution

**Important**: The `task_dir` setting itself is resolved relative to the config file's directory, not the current working directory. This makes configurations portable.

| `task_dir` Value | Config File Location | Resolved `task_dir` |
|------------------|---------------------|---------------------|
| `.` | `/project/configs/config.yaml` | `/project/configs/` |
| `..` | `/project/configs/config.yaml` | `/project/` |
| `../output` | `/project/configs/config.yaml` | `/project/output/` |
| `/absolute/path` | (anywhere) | `/absolute/path` (unchanged) |

### Other Path Resolution

Once `task_dir` is resolved, all other relative paths in your configuration are resolved relative to the `task_dir`:

| Config Field | Example Path | Resolved To |
|--------------|--------------|-------------|
| `data_files` | `data/my_data.json` | `{task_dir}/data/my_data.json` |
| `output_annotation_dir` | `output/annotations/` | `{task_dir}/output/annotations/` |
| `site_dir` | `templates/` | `{task_dir}/templates/` |
| `custom_ds` | `custom_data/` | `{task_dir}/custom_data/` |

### Example Path Resolution

If your `task_dir` is `/home/user/my_project/` and your config contains:

```yaml
task_dir: /home/user/my_project/
data_files:
  - data/sentiment_data.json
  - data/quality_data.csv
output_annotation_dir: output/annotations/
site_dir: templates/
```

The paths will be resolved to:

- `data/sentiment_data.json` → `/home/user/my_project/data/sentiment_data.json`
- `data/quality_data.csv` → `/home/user/my_project/data/quality_data.csv`
- `output/annotations/` → `/home/user/my_project/output/annotations/`
- `templates/` → `/home/user/my_project/templates/`

## Special Path Values

Some configuration fields accept special values instead of file paths:

| Value | Meaning |
|-------|---------|
| `"null"` | Disable the feature |
| `"default"` | Use the default implementation |
| `null` (YAML null) | Disable the feature |

### Example

```yaml
site_dir: default          # Use default templates
customjs: null            # No custom JavaScript
custom_ds: "default"      # Use default dataset handling
```

## Validation Requirements

Potato performs comprehensive validation of your configuration to ensure:

### 1. Config File Location
- ✅ Config file is within the specified `task_dir`
- ❌ Config file is outside the `task_dir`

### 2. Required Fields
- ✅ All mandatory configuration fields are present
- ❌ Missing required fields like `task_dir`, `data_files`, etc.

### 3. File Existence
- ✅ All referenced data files exist and are accessible
- ❌ Data files don't exist at the specified paths

### 4. Path Security
- ✅ All paths are secure and don't escape the project directory
- ❌ Paths would escape the project directory (security violation)

### 5. Schema Validation
- ✅ Annotation schemes have valid configurations
- ❌ Invalid annotation types or missing required fields

## Common Validation Errors

### "Configuration file must be in the task_dir"

**Problem**: Your config file is outside the `task_dir` specified in the YAML.

**Example**:
```
config.yaml (contains: task_dir: my_task/)
my_task/
├── data/
└── output/
```

**Solution**: Move the config file into the `task_dir` or update the `task_dir` path.

### "Data file not found"

**Problem**: A referenced data file doesn't exist at the specified path.

**Example**:
```yaml
data_files:
  - data/my_data.json  # File doesn't exist
```

**Solution**: Check that the file path is correct relative to the `task_dir`.

### "Missing required configuration fields"

**Problem**: Required fields are missing from your config.

**Solution**: Ensure all required fields are present:
- `task_dir`
- `data_files`
- `item_properties`
- `annotation_schemes`
- `annotation_task_name`
- `alert_time_each_instance`

### "Path resolves outside project directory"

**Problem**: A file path would escape the project directory (security violation).

**Example**:
```yaml
data_files:
  - ../../../sensitive_data.json  # ❌ Security violation
```

**Solution**: Use only relative paths within the project directory.

## Best Practices

1. **Keep config files in the task directory**: This ensures proper organization and security
2. **Use relative paths**: All paths should be relative to the `task_dir`
3. **Test your configuration**: Always test with a small dataset first
4. **Use descriptive names**: Choose clear, descriptive names for your task directories
5. **Version control**: Keep your configuration files in version control
6. **Document your choices**: Add comments to explain non-obvious configuration choices

## Example Complete Configuration

```yaml
# Basic Configuration
port: 8000
server_name: Sentiment Analysis Task
annotation_task_name: Twitter Sentiment Analysis
task_dir: sentiment_analysis_project/

# Data Configuration
data_files:
  - data/tweets.json
item_properties:
  id_key: tweet_id
  text_key: tweet_text

# Output Configuration
output_annotation_dir: output/annotations/
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
    description: What is the sentiment of this tweet?
    labels:
      - positive
      - negative
      - neutral
    sequential_key_binding: true

  - annotation_type: text
    name: reasoning
    description: Please explain your reasoning:
    multiline: true
    rows: 3
    cols: 50

# Server Configuration
server:
  port: 8000
  host: 0.0.0.0
  require_password: true
  persist_sessions: false

# Optional Settings
site_dir: default
customjs: null
customjs_hostname: null
alert_time_each_instance: 10000000
```

This configuration follows all the requirements and best practices outlined in this document.