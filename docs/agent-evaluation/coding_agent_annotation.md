# Coding Agent Trace Annotation

Potato annotates agentic coding sessions -- traces from Claude Code, OpenCode, Cursor, Aider, SWE-Agent, and other AI coding assistants.

## Overview

Coding agent traces consist of sequences of tool calls (file reads, edits, terminal commands, searches) interleaved with agent reasoning. Potato renders them as:

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
- Claude Code's own session transcripts (`~/.claude/projects/<project>/<session>.jsonl`)
- Anthropic Messages API format (content blocks with `tool_use`/`tool_result`)
- Pre-structured `structured_turns` format
- Generic `turns` or `steps` format with tool calls

### Annotating your own Claude Code sessions

Claude Code writes one JSONL file per session under
`~/.claude/projects/<slugified-working-directory>/<session-id>.jsonl`. Point the
converter straight at one:

```bash
python -m potato.trace_converter \
  -i ~/.claude/projects/-home-me-myrepo/3c853f0f-....jsonl \
  --auto-detect -o data/session.jsonl
```

One session becomes one trace, not one per line. What you get:

| In the transcript | In the trace |
|---|---|
| `user` / `assistant` messages | conversation turns |
| `tool_use` + matching `tool_result` | a tool call with its output, typed for the display |
| `parentUuid` chain | only the surviving path — rewound attempts are dropped and counted |
| `isSidechain` messages | `sidechain_runs`, kept out of the main turns |
| `cwd`, `gitBranch`, `version`, `usage` | the metadata table |
| slash commands (`/clear` and friends) | dropped; they are the CLI talking to itself |

Two things to know before planning a study around this:

- **Thinking text is not on disk.** Transcripts keep the `thinking` block and its
  signature and drop the content — measured at 6393 blocks across 40 local
  sessions, none with text. The trace reports the count so the gap is visible.
  If you need reasoning to annotate, capture it live with
  `claude -p --output-format stream-json` or the Agent SDK instead.
- **The on-disk shape belongs to the CLI, not to a published API.** Every row
  carries a `version`. Treat the reader as best-effort across upgrades: it
  ignores record types it does not know, and raises rather than handing back an
  empty trace if a file stops parsing into messages.

Transcripts also carry absolute paths, branch names, environment details and
whatever source the session read. Redact before sharing a dataset, and get
consent from whoever's sessions they are.

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

### Process Reward Schema (PRM)

For collecting binary per-step correctness signals for training Process Reward Models:

```yaml
  - annotation_type: process_reward
    name: step_rewards
    description: "Mark the first incorrect step"
    steps_key: structured_turns
    mode: first_error  # or "per_step"
```

| Option | Default | Description |
|--------|---------|-------------|
| `steps_key` | `steps` | Key in instance data containing the steps array |
| `step_text_key` | `action` | Key within each step for display text |
| `mode` | `first_error` | `first_error`: click first wrong step, rest auto-marked. `per_step`: annotate each independently |

### Code Review Schema

For GitHub PR review-style annotation with inline comments:

```yaml
  - annotation_type: code_review
    name: review
    description: "Review the agent's code changes"
    comment_categories: [bug, style, suggestion, security]
    verdict_options: [approve, request_changes, comment_only]
    file_rating_dimensions: [correctness, quality]
```

| Option | Default | Description |
|--------|---------|-------------|
| `comment_categories` | `[bug, style, suggestion, security, question]` | Categories for inline comments |
| `verdict_options` | `[approve, request_changes, comment_only]` | Overall review verdict options |
| `file_rating_dimensions` | `[correctness, quality]` | Per-file rating dimensions (1-5 scale) |

Click on diff lines in the `coding_trace` display to add inline comments with file path and line number auto-filled.

## Trace Converters

Convert traces from various coding agent formats:

```bash
# Claude Code / Anthropic Messages API
python -m potato.trace_converter -i traces.json -f claude_code -o data/converted.jsonl

# Aider chat history
python -m potato.trace_converter -i chat.md -f aider -o data/converted.jsonl

# SWE-Agent trajectories
python -m potato.trace_converter -i trajectory.json -f swe_agent_trajectory -o data/converted.jsonl

# Auto-detect format
python -m potato.trace_converter -i traces.json --auto-detect -o data/converted.jsonl
```

## Export Formats

Export annotations for ML training pipelines:

```bash
python -m potato.export -f coding_eval -o exports/ --types prm,preference,swebench,code_review
```

| Format | Output | Use Case |
|--------|--------|----------|
| `prm` | `prm_training_data.jsonl` | Process Reward Model training |
| `preference` | `preference_pairs.jsonl` | DPO/RLHF from pairwise annotations |
| `swebench` | `swebench_results.jsonl` | SWE-bench compatible evaluation |
| `code_review` | `code_reviews.jsonl` | Structured review data |

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

## Live Coding Agent Mode

Watch a coding agent work in real-time, intervene, rollback, replay with different instructions, and edit agent actions.

### Quick Start

```bash
# With Ollama (fully local, no API key needed)
python potato/flask_server.py start examples/agent-traces/live-coding-agent/config.yaml -p 8000
```

### Configuration

```yaml
live_coding_agent:
  backend_type: ollama_tool_use   # or anthropic_tool_use, claude_sdk
  ai_config:
    model: qwen2.5-coder:7b       # Any Ollama model with tool support
    base_url: http://localhost:11434
  working_dir: ./workspace
  max_turns: 20
  sandbox_mode: container         # container (default), bubblewrap, trusted
  container_cli: docker           # or podman
```

### Agent Backends

| Backend | Config Key | Requirements |
|---------|-----------|-------------|
| Ollama (local) | `ollama_tool_use` | Ollama running locally, no API key |
| Anthropic API | `anthropic_tool_use` | `ANTHROPIC_API_KEY` env var |
| Claude Agent SDK | `claude_sdk` | `claude-agent-sdk` package installed |

### Sandbox modes

Annotators can edit a tool call and re-execute it. That includes `Bash`, so the
sandbox is what stops an edited command reaching the host. Pick the strongest
one your machine supports.

| Mode | Boundary | Needs |
|------|----------|-------|
| `container` (default) | Namespaces, cgroups, seccomp. No network, read-only root, runs as `nobody`, all capabilities dropped | `docker` or `podman` |
| `bubblewrap` | Namespaces, no daemon, no root | `bwrap`, Linux |
| `trusted` | None | An explicit acknowledgement |

Set `container_cli: podman` for rootless containers, which need no root daemon.

#### Give the agent an image that can do the task

The default image is `python:3.12-slim` and the default network is `none`.
Both are right on their own. Together they mean an agent asked to run the tests
cannot: there is no test runner in the image and no way to install one, so its
first tool call is `pytest` and the answer is exit 127.

Name an image that already carries what the task needs:

```yaml
live_coding_agent:
  sandbox_mode: container
  sandbox_image: my-org/eval-python:3.12   # pytest, ruff, whatever the task uses
```

Loosening `sandbox_network` is the other way out, and a worse one — an agent
that can reach the network can send out whatever it reads. Potato logs a
warning when you do. The boot banner points this out when the defaults are
left as they are.

#### Session lifecycle

A session holds a container for as long as it is alive. It is released when
the annotator clicks **Stop**, when the session has been finished for longer
than the manager's TTL (one hour), and when the Potato process exits. A
session that finishes on its own keeps its container until one of those
happens, because the instruction box stays live and the annotator may still
have something to ask.

Both SIGINT (Ctrl-C) and SIGTERM (`systemctl stop`, `docker stop`,
supervisord, `kill`) release. Python runs its exit handlers for a signal it
has a handler for, and SIGTERM has none by default, so Potato installs one —
chained, so a process manager's own handler still runs.

A crash escapes all of it, so Potato sweeps leftover sandbox containers at
startup and logs how many it removed.

To go further, install a drop-in container runtime and name it:

```yaml
live_coding_agent:
  sandbox_mode: container
  container_runtime: runsc     # gVisor: intercepts syscalls in userspace
  # container_runtime: kata    # Kata: a hardware VM per container
```

Potato passes the value straight through as `--runtime`, so nothing else
changes.

#### Running without a container runtime

On a shared cluster or a machine where Docker is not an option, `bubblewrap` is
usually available and needs neither a daemon nor root:

```yaml
live_coding_agent:
  sandbox_mode: bubblewrap
```

It is a weaker boundary than a container, with no cgroup limits, and it needs
unprivileged user namespaces, which some hardened kernels turn off. Potato
checks for both at startup and refuses to run if either is missing.

#### Trusted mode

If you control the host and trust your annotators, run without a sandbox:

```yaml
live_coding_agent:
  sandbox_mode: trusted
  acknowledge_untrusted_code_execution: true
```

Both keys are required. Without the second, the server refuses to start. Tool
calls then run as the Potato user with no isolation, and Potato logs a banner
saying so on every boot. Deployment preflight rejects this mode for a public
host.

`worktree`, `docker` and `direct` still parse, and map onto the ladder above.
`worktree` and `direct` become `trusted` and need the acknowledgement key:
a git worktree is on the same host, as the same user, with the same network, so
`cd /` leaves it. It keeps the agent's edits off your main checkout, which is
worth having, but it is not a security boundary. `docker` becomes `container`,
which fails loudly when Docker is missing instead of silently running tools on
the host the way `docker` used to.

#### Workspace copies and Docker-in-Docker

The agent works on a **copy** of `working_dir`, made per session, so its edits
never touch the original. Copies live in `.potato-sandboxes` beside
`working_dir`; set `sandbox_root` to move them.

If Potato itself runs inside a container, do not mount the host Docker socket to
get container mode. That is equivalent to giving the sandbox host root. Use
rootless Podman, `bubblewrap`, or `trusted` inside an already-isolated
container.

### Controls

During a live session, annotators can:
- **Pause/Resume**: Stop the agent between tool calls
- **Send Instructions**: Guide the agent ("try a different approach")
- **Stop**: End the session and save the trace

### Checkpoints and Rollback

After each file-modifying tool call, a git checkpoint is created. Annotators can:
- View all checkpoints in a timeline
- **Rollback** to any previous step (restores files and conversation)
- See diffs between checkpoints

### Branching and Replay

From any checkpoint, create alternative trajectories:
- **Replay from step**: Branch with new instructions
- **Edit action**: Modify a tool call's input and re-execute
- **Compare branches**: View different approaches side by side
- All branches are saved in the trace export

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/live_coding_agent/start` | POST | Start a session |
| `/api/live_coding_agent/stream/<id>` | GET | SSE event stream |
| `/api/live_coding_agent/pause/<id>` | POST | Pause agent |
| `/api/live_coding_agent/resume/<id>` | POST | Resume agent |
| `/api/live_coding_agent/instruct/<id>` | POST | Send instruction |
| `/api/live_coding_agent/stop/<id>` | POST | Stop and save |
| `/api/live_coding_agent/checkpoints/<id>` | GET | List checkpoints |
| `/api/live_coding_agent/rollback/<id>` | POST | Rollback to step |
| `/api/live_coding_agent/replay/<id>` | POST | Create branch and replay |
| `/api/live_coding_agent/branches/<id>` | GET | List branches |
| `/api/live_coding_agent/switch_branch/<id>` | POST | Switch branch |

## Examples

See `examples/agent-traces/` for complete example projects:

- **`live-coding-agent/`** -- Live coding agent with real-time streaming and controls
- **`coding-agent-evaluation/`** -- Static coding agent trace evaluation
- **`coding-agent-prm/`** -- Fast PRM data collection with first_error mode
- **`coding-agent-review/`** -- GitHub PR-style code review with inline comments
- **`coding-agent-comparison/`** -- Multi-dimensional agent quality comparison
- **`swebench-evaluation/`** -- SWE-bench coding agent evaluation

## Related Documentation

- [Schemas and Templates](../annotation-types/schemas_and_templates.md) -- All annotation schema types
- [Configuration Reference](../configuration/configuration.md) -- Complete configuration options
