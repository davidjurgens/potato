# Coding Agent Trace Annotation

Potato supports annotation of agentic coding system traces -- sessions from tools like Claude Code, OpenCode, Cursor, Aider, SWE-Agent, and other AI coding assistants. This guide covers how to set up coding agent evaluation projects.

## Overview

Coding agent traces consist of sequences of tool calls (file reads, edits, terminal commands, searches) interleaved with agent reasoning. Potato renders these with purpose-built formatting:

- **Code diffs** (Edit/Write): Red/green unified diff view
- **Terminal blocks** (Bash): Dark monospace terminal styling
- **Code blocks** (Read/Grep): Line-numbered code display
- **File tree sidebar**: Shows all files touched, grouped by operation
- **Collapsible outputs**: Long outputs auto-collapse with expand controls

## Quick Start

```bash
# Run the example from the repository root
python potato/flask_server.py start examples/agent-traces/coding-agent-evaluation/config.yaml -p 8000
```

## Data Format

### Structured Turns Format (Recommended)

The `structured_turns` format preserves full tool call structure for rich rendering:

```json
{
  "id": "session_001",
  "task_description": "Fix the authentication bypass in login.py",
  "model": "claude-sonnet-4-20250514",
  "structured_turns": [
    {
      "role": "user",
      "content": "Fix the authentication bypass in login.py",
      "tool_calls": []
    },
    {
      "role": "assistant",
      "content": "I'll investigate the auth issue.",
      "tool_calls": [
        {
          "tool": "Read",
          "input": {"file_path": "src/auth/login.py"},
          "output": "def login(user, password):\n    if user.role == 'admin':\n        return True\n    ...",
          "output_type": "code",
          "language": "python"
        },
        {
          "tool": "Edit",
          "input": {
            "file_path": "src/auth/login.py",
            "old_string": "if user.role == 'admin':\n        return True",
            "new_string": "if verify_password(password, user.password_hash):"
          },
          "output": "Edit applied successfully.",
          "output_type": "diff"
        },
        {
          "tool": "Bash",
          "input": {"command": "pytest tests/test_auth.py -v"},
          "output": "4 passed",
          "output_type": "terminal"
        }
      ]
    }
  ]
}
```

### Tool Call Fields

Each tool call in `tool_calls` has:

| Field | Required | Description |
|-------|----------|-------------|
| `tool` | Yes | Tool name (Read, Edit, Bash, Grep, Glob, Write, etc.) |
| `input` | Yes | Tool input parameters (dict) |
| `output` | No | Tool output (string) |
| `output_type` | No | Rendering hint: `code`, `diff`, `terminal`, `generic` (auto-detected if omitted) |
| `language` | No | Programming language for syntax hints (auto-detected from file extension) |

### Converting From Other Formats

Use the trace converter to convert from Anthropic Messages API, SWE-Agent, or other formats:

```bash
# Convert Claude Code / Anthropic Messages API traces
python -m potato.trace_converter -i traces.json -f claude_code -o data/converted.jsonl

# Auto-detect format
python -m potato.trace_converter -i traces.json --auto-detect -o data/converted.jsonl
```

The `claude_code` converter handles:
- Anthropic Messages API format (content blocks with `tool_use`/`tool_result`)
- Pre-structured `structured_turns` format
- Generic `turns` or `steps` format with tool calls

## Configuration

### Display Configuration

Use the `coding_trace` display type in your `instance_display` config:

```yaml
instance_display:
  layout:
    direction: vertical
    gap: 16px
  fields:
    - key: task_description
      type: text
      label: "Task"
    - key: structured_turns
      type: coding_trace
      label: "Agent Session"
      display_options:
        show_file_tree: true        # Show file tree sidebar
        diff_view: unified          # Diff rendering style
        collapse_long_outputs: true # Auto-collapse long outputs
        max_output_lines: 50       # Lines before collapsing
        terminal_theme: dark       # Terminal block theme
        show_step_numbers: true    # Show step numbers
        show_reasoning: true       # Show agent reasoning text
```

### Display Options

| Option | Default | Description |
|--------|---------|-------------|
| `show_file_tree` | `true` | Show sidebar with all files touched |
| `diff_view` | `unified` | Diff rendering style |
| `collapse_long_outputs` | `true` | Auto-collapse outputs longer than `max_output_lines` |
| `max_output_lines` | `50` | Number of lines before collapsing |
| `terminal_theme` | `dark` | Terminal block color theme |
| `show_step_numbers` | `true` | Show step numbers for assistant turns |
| `show_tool_badges` | `true` | Show tool name badges on tool calls |
| `show_reasoning` | `true` | Show agent reasoning text |
| `compact` | `false` | Use compact layout |

### Annotation Schemas

The coding trace display works with all standard Potato annotation schemas. Common combinations:

```yaml
annotation_schemes:
  # Task-level success rating
  - annotation_type: radio
    name: task_success
    description: "Did the agent complete the task?"
    labels:
      - name: success
      - name: partial
      - name: failure

  # Code quality rating
  - annotation_type: likert
    name: code_quality
    description: "Rate the quality of the code changes"
    size: 5

  # Issue identification
  - annotation_type: multiselect
    name: issues
    description: "Select any issues observed"
    labels:
      - name: unnecessary_reads
      - name: wrong_tool
      - name: incomplete_fix
      - name: regression
      - name: missing_tests
      - name: scope_creep

  # Free-form notes
  - annotation_type: text
    name: notes
    description: "Additional observations"
```

## Supported Tool Types

The display renders each tool type with appropriate formatting:

| Tool Names | Rendering | Style |
|------------|-----------|-------|
| `Read`, `read` | Code block with line numbers | Blue badge |
| `Edit`, `edit`, `Replace` | Unified diff (red/green lines) | Orange badge |
| `Write`, `write`, `Create` | "New file" code block (all green) | Green badge |
| `Bash`, `Terminal`, `Shell` | Dark terminal block with `$` prompt | Dark badge |
| `Grep`, `Glob`, `Search`, `Find` | Code block (search results) | Purple badge |
| Other tools | JSON-formatted input/output | Grey badge |

## Examples

See `examples/agent-traces/` for complete example projects:

- **`coding-agent-evaluation/`** -- Basic coding agent trace evaluation with task success, code quality, and issue identification
- **`swebench-evaluation/`** -- SWE-bench coding agent evaluation
- **`agent-trace-evaluation/`** -- Comprehensive agent evaluation with trajectory_eval schema

## Related Documentation

- [Schemas and Templates](schemas_and_templates.md) -- All annotation schema types
- [Configuration Reference](configuration.md) -- Complete configuration options
