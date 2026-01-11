# Loading Data from a Directory

This guide explains how to load annotation instances from all files in a directory, with optional live watching for new or modified files.

## Overview

Instead of specifying individual data files with `data_files`, you can point Potato to a directory containing your data files. All supported files (JSON, JSONL, CSV, TSV) in that directory will be loaded automatically.

This is useful when:
- You have many data files and don't want to list them individually
- You want to dynamically add new files while the server is running
- You're receiving data from an external process that writes to a shared directory

## Configuration

### Basic Usage (Static Loading)

To load all files from a directory at startup:

```yaml
# Load all supported files from this directory
data_directory: "./data/incoming"

# data_files can be empty when using data_directory
data_files: []

# Required: item_properties must still be configured
item_properties:
  id_key: "id"
  text_key: "text"
```

### Live Directory Watching

To automatically detect and load new or modified files while the server is running:

```yaml
data_directory: "./data/incoming"
data_files: []

# Enable live watching (default: false)
watch_data_directory: true

# Optional: how often to check for changes in seconds (default: 5.0)
watch_poll_interval: 10.0

item_properties:
  id_key: "id"
  text_key: "text"
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `data_directory` | string | - | Path to the directory containing data files |
| `watch_data_directory` | boolean | `false` | Whether to watch for new/modified files |
| `watch_poll_interval` | number | `5.0` | Seconds between directory scans (min: 1.0, max: 3600) |

## Supported File Formats

The directory watcher supports the same formats as `data_files`:

- **JSON** (`.json`) - One JSON object per line, or a JSON array
- **JSONL** (`.jsonl`) - JSON Lines format, one object per line
- **CSV** (`.csv`) - Comma-separated values with header row
- **TSV** (`.tsv`) - Tab-separated values with header row

Each file can contain multiple instances. The `id_key` and `text_key` from `item_properties` determine which fields contain the instance ID and text content.

## How It Works

### At Startup

1. All files with supported extensions in `data_directory` are scanned
2. Each file is parsed according to its extension
3. Instances are added to the annotation queue
4. If `watch_data_directory` is enabled, a background thread starts watching

### During Runtime (when watching is enabled)

1. Every `watch_poll_interval` seconds, the directory is scanned
2. New files are parsed and their instances are added
3. Modified files are re-parsed:
   - New instances are added
   - Existing instances are updated (annotations are preserved)
4. Removed files: instances remain in the system (to preserve any annotations)

## Example Directory Structure

```
my_project/
├── configs/
│   └── config.yaml
└── data/
    └── incoming/
        ├── batch_001.jsonl
        ├── batch_002.jsonl
        └── new_data.json    # Added while server is running
```

## Example Data Files

### JSONL Format (`batch_001.jsonl`)
```json
{"id": "item_001", "text": "First document to annotate."}
{"id": "item_002", "text": "Second document to annotate."}
{"id": "item_003", "text": "Third document to annotate."}
```

### JSON Format (`batch_002.json`)
```json
[
  {"id": "item_004", "text": "Fourth document."},
  {"id": "item_005", "text": "Fifth document."}
]
```

### CSV Format (`batch_003.csv`)
```csv
id,text,category
item_006,Sixth document to annotate.,news
item_007,Seventh document to annotate.,blog
```

## Combining with data_files

You can use both `data_directory` and `data_files` together. The `data_files` are loaded first, then files from `data_directory`:

```yaml
# Load specific files first
data_files:
  - "data/important_batch.jsonl"

# Then load everything from the directory
data_directory: "./data/incoming"
watch_data_directory: true
```

## Instance Updates

When a file is modified while watching is enabled:

- **New instances** (new IDs) are added to the annotation queue
- **Existing instances** (same IDs) are updated with new data, but annotations are preserved
- **Removed instances** (IDs no longer in file) remain in the system to preserve annotations

This means annotators won't lose their work if you update a data file.

## Error Handling

- Files that fail to parse are logged and skipped (other files still load)
- Missing `id_key` in an instance: that instance is skipped with a warning
- Missing `text_key` in an instance: instance loads with a warning
- Directory permissions errors are logged

## Performance Considerations

- **Poll interval**: Higher values reduce CPU usage but delay detection of new files
- **Large directories**: All files are scanned each interval; consider organizing files into subdirectories if you have thousands of files
- **Large files**: Files are fully re-parsed when modified; consider using smaller batch files

## Logging

The directory watcher logs its activity at INFO level:

```
INFO: Loaded 150 instances from data_directory: ./data/incoming
INFO: Directory watching enabled (poll interval: 5.0s)
INFO: Directory scan: 25 instances added, 0 updated
INFO: Directory watcher stopped
```

Enable DEBUG logging to see individual file processing details.
