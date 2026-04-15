# Configuration Migration Tool

Potato includes a migration tool to help upgrade configuration files from older formats to the current v2 format. This tool automatically detects and applies necessary changes while preserving your existing settings.

## Usage

```bash
# Basic migration (prints migrated config to stdout)
potato migrate config.yaml --to-v2

# Save to a new file
potato migrate config.yaml --to-v2 --output new_config.yaml

# Modify the original file in place
potato migrate config.yaml --to-v2 --in-place

# Preview changes without applying them
potato migrate config.yaml --to-v2 --dry-run
```

## Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--to-v2` | | **Required.** Migrate to v2 format |
| `--output FILE` | `-o` | Write migrated config to specified file |
| `--in-place` | `-i` | Modify the original config file directly |
| `--dry-run` | | Show what changes would be made without applying them |
| `--quiet` | `-q` | Suppress informational output |

**Note:** `--in-place` and `--output` cannot be used together.

## Migration Rules

The migration tool applies the following transformations:

### 1. Textarea to Multiline

Converts the old textarea format to the new multiline format for text schemas.

**Before:**
```yaml
annotation_schemes:
  - annotation_type: "text"
    name: "feedback"
    textarea:
      on: true
      rows: 4
      cols: 50
```

**After:**
```yaml
annotation_schemes:
  - annotation_type: "text"
    name: "feedback"
    multiline: true
    rows: 4
    cols: 50
```

### 2. Legacy User Config

Detects old `user_config` format and suggests adding explicit `login` configuration.

**Before:**
```yaml
user_config:
  allow_all_users: true
```

**After:**
```yaml
user_config:
  allow_all_users: true
login:
  type: open
```

### 3. Label Requirement Format

Converts boolean `label_requirement` to the dictionary format.

**Before:**
```yaml
annotation_schemes:
  - annotation_type: "multirate"
    name: "ratings"
    label_requirement: true
```

**After:**
```yaml
annotation_schemes:
  - annotation_type: "multirate"
    name: "ratings"
    label_requirement:
      required: true
```

### 4. Output Format Suggestions

Provides recommendations when using older output formats:

- If `output_annotation_format` is set to `csv` or `tsv`, suggests using `json` for richer annotation data support (spans, metadata)

### 5. Site Configuration Notes

Confirms that `site_dir: default` is the recommended approach for v2, using auto-generated templates.

## Examples

### Preview Changes (Dry Run)

```bash
$ potato migrate old_config.yaml --to-v2 --dry-run

Migration changes:

[textarea_to_multiline] Convert textarea.on to multiline format in textbox schemas:
  - Converted textarea.on to multiline in schema 'feedback'

[legacy_user_config] Migrate legacy user_config to login format:
  - Added login.type: open (from allow_all_users: true)
  - Note: user_config is still valid, login section added for clarity

Dry run - no changes written.

Migrated configuration would be:
annotation_task_name: My Task
...
```

### Migrate and Save to New File

```bash
$ potato migrate old_config.yaml --to-v2 --output migrated_config.yaml

Migration changes:
...

Wrote migrated config to migrated_config.yaml
```

### Quiet Mode

```bash
# Just output the migrated YAML, no status messages
$ potato migrate old_config.yaml --to-v2 --quiet > new_config.yaml
```

## When to Use Migration

Consider using the migration tool when:

- Upgrading from an older version of Potato
- You see deprecation warnings when starting the server
- Configuration options don't work as expected
- You want to ensure your config follows current best practices

## Troubleshooting

### "Configuration file is empty"

The YAML file couldn't be parsed or is empty. Check that:
- The file exists and is readable
- The YAML syntax is valid
- The file contains configuration content

### "Invalid YAML in configuration file"

There's a syntax error in your YAML. Common issues:
- Incorrect indentation
- Missing colons after keys
- Unquoted special characters

### No migrations needed

If you see "No migrations needed - config is already up to date", your configuration already uses the current v2 format.
