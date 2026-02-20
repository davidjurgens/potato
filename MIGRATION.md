# Migration Guide: v1.x to v2.0.0

This guide helps you migrate existing Potato annotation projects from v1.x to v2.0.0.

## Overview

**Who needs to migrate?** Anyone with existing Potato annotation projects using v1.x configuration files.

**Estimated time:** 15-30 minutes per project, depending on complexity.

**What's changing?**
- Configuration format (JSON → YAML)
- Directory structure requirements
- Annotation type naming (`highlight` → `span`)
- Path resolution behavior

## Quick Checklist

Use this checklist to track your migration progress:

- [ ] Convert JSON configuration to YAML format
- [ ] Add the required `task_dir` field
- [ ] Update `output_annotation_dir` to use subdirectory structure
- [ ] Rename `highlight` to `span` in annotation schemes
- [ ] Move configuration file into the task directory
- [ ] Update any custom paths to be relative to `task_dir`
- [ ] Test the migrated configuration

---

## Step-by-Step Migration Guide

### Step 1: Convert JSON to YAML

v2.0.0 requires YAML format for all configuration files. JSON is no longer supported.

**Before (v1.x JSON):**
```json
{
    "port": 9001,
    "server_name": "potato annotator",
    "annotation_task_name": "Sentiment Analysis",
    "data_files": ["data/examples.json"],
    "item_properties": {
        "id_key": "id",
        "text_key": "text"
    },
    "annotation_schemes": [
        {
            "annotation_type": "radio",
            "name": "sentiment",
            "labels": ["positive", "negative", "neutral"]
        }
    ]
}
```

**After (v2.0.0 YAML):**
```yaml
port: 9001
server_name: potato annotator
annotation_task_name: Sentiment Analysis
data_files:
  - data/examples.json
item_properties:
  id_key: id
  text_key: text
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    labels:
      - positive
      - negative
      - neutral
```

**Conversion tips:**
- Remove curly braces `{}` and square brackets `[]` for objects and simple arrays
- Use indentation (2 spaces) instead of braces for nesting
- Remove quotes around keys
- Use `-` prefix for list items
- Remove commas at the end of lines

### Step 2: Add the `task_dir` Field

v2.0.0 requires a `task_dir` field that specifies the root directory for your annotation task.

**Add this field near the top of your config:**
```yaml
task_dir: annotation_output/my-project/
```

This directory will contain:
- Your annotation output files
- User state files
- Any task-specific data

### Step 3: Update Directory Structure

We recommend organizing your project with the config file inside the task directory:

**Recommended structure:**
```
my_annotation_project/
├── config.yaml                 # Configuration file
├── data/
│   └── examples.json           # Input data
└── annotations/                # Output directory
    └── (generated files)
```

**Update your config to match:**
```yaml
task_dir: my_annotation_project/
output_annotation_dir: my_annotation_project/annotations/
data_files:
  - data/examples.json
```

### Step 4: Rename `highlight` to `span`

If you use span/highlight annotations, update the annotation type:

**Before:**
```yaml
annotation_schemes:
  - annotation_type: highlight
    name: entities
    labels:
      - Person
      - Organization
      - Location
```

**After:**
```yaml
annotation_schemes:
  - annotation_type: span
    name: entities
    labels:
      - Person
      - Organization
      - Location
```

**Quick find-and-replace:**
- Search: `annotation_type: highlight`
- Replace: `annotation_type: span`

Or search: `"annotation_type": "highlight"`
Replace: `annotation_type: span`

### Step 5: Move Config Files (Security Requirement)

For security, config files must now be located within the `task_dir` directory or its parent.

**If your config was at:** `/home/user/configs/my_task.yaml`
**And task_dir was:** `/home/user/projects/my_task/`

**Move the config to:** `/home/user/projects/my_task/config.yaml`

Then run: `python potato/flask_server.py start /home/user/projects/my_task/config.yaml`

### Step 6: Update Path References

All relative paths are now resolved relative to `task_dir`, not the current working directory.

**Before (paths relative to where you run the command):**
```yaml
data_files:
  - ../shared_data/examples.json
output_annotation_dir: ./output/
```

**After (paths relative to task_dir):**
```yaml
task_dir: my_project/
data_files:
  - data/examples.json           # Relative to task_dir
output_annotation_dir: annotations/  # Relative to task_dir
```

**Security note:** Paths cannot escape more than 2 parent directories (`../../`). Attempting to access files outside the project directory will result in a security error.

### Step 7: Validate Your Configuration

Test your migrated config before deploying:

```bash
# Start the server with your migrated config
python potato/flask_server.py start path/to/your/config.yaml -p 8000

# Or if installed via pip
potato start path/to/your/config.yaml -p 8000
```

Check for:
- Server starts without errors
- Login page loads at http://localhost:8000
- Annotation interface displays correctly
- Annotations can be submitted and saved

---

## Complete Before/After Example

### Before: v1.x Configuration (JSON)

**File:** `sentiment_task.json`
```json
{
    "port": 9001,
    "server_name": "potato annotator",
    "annotation_task_name": "Sentiment Analysis Task",
    "output_annotation_dir": "annotation_output/sentiment/",
    "output_annotation_format": "jsonl",
    "data_files": ["data/tweets.json"],
    "item_properties": {
        "id_key": "id",
        "text_key": "text",
        "context_key": "context"
    },
    "user_config": {
        "allow_all_users": true,
        "users": []
    },
    "alert_time_each_instance": 10000000,
    "annotation_schemes": [
        {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "What is the sentiment of this text?",
            "labels": [
                {"name": "positive", "tooltip": "Expresses positive emotion"},
                {"name": "negative", "tooltip": "Expresses negative emotion"},
                {"name": "neutral", "tooltip": "No clear sentiment"}
            ],
            "sequential_key_binding": true
        },
        {
            "annotation_type": "highlight",
            "name": "sentiment_words",
            "description": "Highlight words that indicate sentiment",
            "labels": ["positive_word", "negative_word"]
        }
    ],
    "site_dir": "default"
}
```

### After: v2.0.0 Configuration (YAML)

**File:** `sentiment_project/config.yaml`
```yaml
port: 9001
server_name: potato annotator
annotation_task_name: Sentiment Analysis Task

# New required field
task_dir: sentiment_project/

# Updated path structure
output_annotation_dir: sentiment_project/annotations/
output_annotation_format: jsonl

data_files:
  - data/tweets.json

item_properties:
  id_key: id
  text_key: text
  context_key: context

user_config:
  allow_all_users: true
  users: []

alert_time_each_instance: 10000000

annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: What is the sentiment of this text?
    labels:
      - name: positive
        tooltip: Expresses positive emotion
      - name: negative
        tooltip: Expresses negative emotion
      - name: neutral
        tooltip: No clear sentiment
    sequential_key_binding: true

  # Note: "highlight" renamed to "span"
  - annotation_type: span
    name: sentiment_words
    description: Highlight words that indicate sentiment
    labels:
      - positive_word
      - negative_word

site_dir: default
```

### Directory Structure Change

**Before:**
```
project_root/
├── sentiment_task.json         # Config anywhere
├── data/
│   └── tweets.json
└── annotation_output/
    └── sentiment/
```

**After:**
```
project_root/
└── sentiment_project/          # task_dir
    ├── config.yaml             # Config inside task_dir
    ├── data/
    │   └── tweets.json
    └── annotations/            # output_annotation_dir
```

---

## Troubleshooting

### Error: "Config file must be within task directory"

**Cause:** Your config file is outside the `task_dir`.

**Solution:** Move the config file into the `task_dir` or a parent directory of `task_dir`.

### Error: "Path traversal detected" or "Path escapes project directory"

**Cause:** A path in your config attempts to access files outside the allowed directory.

**Solution:** Ensure all paths stay within the project. Move data files into your project directory instead of using `../../` paths.

### Error: "Unknown annotation type: highlight"

**Cause:** The `highlight` annotation type was renamed to `span`.

**Solution:** Replace `annotation_type: highlight` with `annotation_type: span`.

### Error: "Missing required field: task_dir"

**Cause:** v2.0.0 requires the `task_dir` field.

**Solution:** Add `task_dir: your_project_directory/` to your config.

### Error: "Invalid YAML syntax"

**Cause:** Syntax error during JSON to YAML conversion.

**Common issues:**
- Missing colons after keys
- Incorrect indentation (use 2 spaces, not tabs)
- Leftover JSON syntax (commas, brackets)

**Solution:** Use a YAML validator to check your syntax. Online tools like [YAML Lint](http://www.yamllint.com/) can help.

### Annotations not saving

**Cause:** The `output_annotation_dir` path may be incorrect.

**Solution:**
1. Ensure `output_annotation_dir` is a valid path relative to `task_dir`
2. Check that the directory exists or can be created
3. Verify write permissions

### Data files not loading

**Cause:** Path resolution changed from current directory to `task_dir`.

**Solution:** Update `data_files` paths to be relative to `task_dir`, or use absolute paths.

---

## Getting Help

If you encounter issues not covered here:

1. Check the [CHANGELOG.md](CHANGELOG.md) for a complete list of changes
2. Review example configs in `examples/`
3. Open an issue at https://github.com/davidjurgens/potato/issues

## New Features

After migrating, explore the new v2.0.0 features documented in [docs/new_features_v2.md](docs/new_features_v2.md):
- AI-powered hints
- Active learning
- Training phase
- Database backend
- Enhanced admin dashboard
