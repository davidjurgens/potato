# Annotating Agent Traces with Potato

This guide covers how to use Potato for evaluating AI agent traces (trajectories). Potato provides all the infrastructure needed for rigorous agent evaluation: multi-annotator coordination, rich annotation schemas, inter-annotator agreement, quality control, and crowdsourcing support.

## Overview

An **agent trace** (or trajectory) is a record of an AI agent's step-by-step actions while completing a task. Each step typically includes:

- **Thought/Reasoning**: The agent's internal planning
- **Action**: A tool call or function invocation
- **Observation**: The result from the environment

Potato maps these traces onto its existing annotation infrastructure:

| Evaluation Level | What's Annotated | Potato Mechanism |
|-----------------|------------------|------------------|
| **Trajectory** | Overall success, efficiency, safety | `radio`, `likert`, `multiselect`, `slider` schemas |
| **Step** | Action correctness, tool choice quality | `per_turn_ratings` on dialogue display, `multirate` schema |
| **Span** | Hallucinations, factual errors in text | `span` schema with dialogue as `span_target` |
| **Comparison** | Which agent is better | Pairwise display + `pairwise` schema |

## Data Format

All agent traces should be formatted as JSONL with each line containing one trace:

```json
{
  "id": "trace_001",
  "task_description": "Book a flight from NYC to London",
  "agent_name": "GPT-4-ReAct",
  "metadata_table": [
    {"Property": "Steps", "Value": "7"},
    {"Property": "Tokens", "Value": "2340"},
    {"Property": "Cost", "Value": "$0.12"}
  ],
  "conversation": [
    {"speaker": "Agent (Thought)", "text": "I need to search for flights..."},
    {"speaker": "Agent (Action)", "text": "search_flights(origin='JFK', destination='LHR')"},
    {"speaker": "Environment", "text": "Found 3 flights: BA117 ($450)..."}
  ]
}
```

### Key Fields

- `id`: Unique trace identifier
- `task_description`: What the agent was asked to do
- `conversation`: List of `{speaker, text}` dicts representing the trace steps
- `metadata_table`: Optional list of `{Property, Value}` dicts for the spreadsheet display
- `agent_name`: Optional agent identifier

### Speaker Naming Conventions

Use consistent speaker names to enable per-turn ratings:

- `Agent (Thought)` - Agent reasoning/planning
- `Agent (Action)` - Tool calls and actions
- `Environment` - Tool/API results
- `User` - User messages (for interactive agents)
- `System` - System messages

## Display Configuration

### Basic: Dialogue Display

The simplest approach uses the `dialogue` display type, which works with zero code changes:

```yaml
instance_display:
  layout:
    direction: vertical
    gap: 16px

  fields:
    - key: task_description
      type: text
      label: "Task"

    - key: metadata_table
      type: spreadsheet
      label: "Trace Info"
      display_options:
        compact: true
        max_height: 120

    - key: conversation
      type: dialogue
      label: "Agent Trace"
      span_target: true
      display_options:
        show_turn_numbers: true
        alternating_shading: true
        per_turn_ratings:
          speakers: ["Agent (Action)"]
          schema_name: "action_correctness"
          scheme:
            type: likert
            size: 3
            labels: ["Wrong", "Right"]
```

### Rich: Agent Trace Display

The `agent_trace` display type provides purpose-built rendering with step cards:

```yaml
instance_display:
  fields:
    - key: conversation
      type: agent_trace
      label: "Agent Trace"
      span_target: true
      display_options:
        show_step_numbers: true
        show_summary: true
        collapse_observations: false
        step_type_colors:
          thought: "#e8f4fd"
          action: "#fff3e0"
          observation: "#e8f5e9"
```

The agent trace display automatically:
- Color-codes steps by type (thought/action/observation)
- Shows a summary header with step counts
- Supports collapsible observations for long traces
- Renders inline screenshot thumbnails if present

### Visual Agents: Image + Dialogue

For GUI/web agents with screenshots:

```yaml
instance_display:
  layout:
    direction: vertical
    gap: 16px

  fields:
    - key: screenshot_url
      type: image
      label: "Screenshot"
      display_options:
        max_height: 400

    - key: conversation
      type: dialogue
      label: "Agent Actions"
      display_options:
        show_turn_numbers: true
```

### Screenshot Sequences: Gallery Display

For step-by-step screenshot sequences:

```yaml
instance_display:
  fields:
    - key: screenshots
      type: gallery
      label: "Screenshots"
      display_options:
        layout: horizontal
        thumbnail_size: 300
        show_captions: true
        zoomable: true
```

## Annotation Schemas

### Trajectory-Level Assessment

```yaml
annotation_schemes:
  # Task success (3-way classification)
  - annotation_type: radio
    name: task_success
    description: "Did the agent complete the task?"
    labels:
      - name: success
        tooltip: "Fully completed correctly"
      - name: partial
        tooltip: "Partially completed or with errors"
      - name: failure
        tooltip: "Not completed"
    sequential_key_binding: true

  # Efficiency (5-point Likert)
  - annotation_type: likert
    name: efficiency
    description: "How efficient was the agent?"
    min_label: "Very inefficient"
    max_label: "Optimal"
    size: 5

  # Safety
  - annotation_type: radio
    name: safety
    labels:
      - name: safe
      - name: minor_concern
      - name: major_violation
```

### Error Taxonomy (MAST Framework)

The MAST taxonomy (NeurIPS 2025, kappa=0.88) defines 14 failure modes:

```yaml
  - annotation_type: multiselect
    name: mast_errors
    description: "Select all failure modes observed"
    labels:
      # System Design
      - name: disobey_task_spec
        tooltip: "Does not follow task specification"
      - name: step_repetition
        tooltip: "Repeats same action unnecessarily"
      - name: loss_of_history
        tooltip: "Forgets prior context"
      - name: unaware_of_termination
        tooltip: "Does not know when to stop"
      # Inter-Agent
      - name: fail_to_clarify
        tooltip: "Fails to ask for needed clarification"
      - name: task_derailment
        tooltip: "Goes off track from main task"
      - name: reasoning_action_mismatch
        tooltip: "Reasoning contradicts action taken"
      # Task Verification
      - name: premature_termination
        tooltip: "Stops before task is complete"
      - name: incomplete_verification
        tooltip: "Does not fully verify results"
      - name: no_errors
        tooltip: "No errors observed"
```

### Span-Level Hallucination Marking

```yaml
  - annotation_type: span
    name: hallucination_spans
    labels:
      - name: hallucination
        tooltip: "Claim not grounded in evidence"
      - name: incorrect_fact
        tooltip: "Factually incorrect statement"
```

### Per-Step Ratings (via per_turn_ratings)

Per-turn ratings add inline Likert widgets to specific speakers in the dialogue.

**Single dimension** (one rating per step):

```yaml
# In the dialogue display_options:
per_turn_ratings:
  speakers: ["Agent (Action)"]
  schema_name: "action_correctness"
  scheme:
    type: likert
    size: 3
    labels: ["Wrong", "Right"]
```

**Multi-dimension** (multiple ratings per step):

```yaml
# In the dialogue display_options:
per_turn_ratings:
  speakers: ["Agent (Action)"]
  schemes:
    - schema_name: action_correctness
      scheme:
        type: likert
        size: 3
        labels: ["Wrong", "Right"]
    - schema_name: reasoning_quality
      scheme:
        type: likert
        size: 5
        labels: ["Poor", "Excellent"]
```

Each scheme gets its own hidden input and annotation column. This is useful for evaluating multiple dimensions of step quality simultaneously (e.g., correctness and reasoning quality).

### Dynamic Multirate (options_from_data)

For traces with varying numbers of steps, use `options_from_data` to generate multirate rows dynamically from instance data:

```yaml
  - annotation_type: multirate
    name: step_ratings
    description: "Rate each step"
    options_from_data: step_summaries  # reads from instance["step_summaries"]
    labels: ["Incorrect", "Questionable", "Correct"]
```

Your data should include the `step_summaries` field:
```json
{
  "id": "trace_001",
  "step_summaries": ["Search for flights", "Compare prices", "Book cheapest"],
  ...
}
```

## Trace Converter CLI

Convert traces from common agent frameworks to Potato's format:

```bash
# Convert ReAct JSON traces
python -m potato.trace_converter --input traces.json --input-format react --output data.jsonl

# Convert LangChain/LangSmith exports
python -m potato.trace_converter --input langsmith_export.json --input-format langchain --output data.jsonl

# Convert Langfuse exports
python -m potato.trace_converter --input langfuse_traces.json --input-format langfuse --output data.jsonl

# Convert WebArena benchmark traces
python -m potato.trace_converter --input webarena_results.json --input-format webarena --output data.jsonl

# Convert ATIF (academic standard) traces
python -m potato.trace_converter --input atif_traces.json --input-format atif --output data.jsonl

# Auto-detect format
python -m potato.trace_converter --input traces.json --auto-detect --output data.jsonl

# List supported formats
python -m potato.trace_converter --list-formats
```

### Supported Input Formats

| Format | Source | Key Fields |
|--------|--------|-----------|
| `react` | Generic ReAct JSON | `steps[].thought/action/observation` |
| `langchain` | LangSmith export | `child_runs[].run_type/inputs/outputs` |
| `langfuse` | Langfuse export | `observations[].type/input/output` |
| `atif` | Academic standard | `steps[].thought/action/observation` + structured `task`/`agent` |
| `webarena` | GUI benchmarks | `actions[].action_type/element` + `screenshots[]` |
| `openai` | OpenAI Chat/Assistants API | `messages[].role/content/tool_calls` |
| `anthropic` | Anthropic Claude Messages API | `messages[].content[]` with typed blocks (`text`, `tool_use`, `tool_result`) |
| `swebench` | SWE-bench benchmark | `instance_id` + `problem_statement` + `patch`/`model_patch` |
| `otel` | OpenTelemetry/OTLP | `resourceSpans` (OTLP) or `trace_id`/`span_id` (flat) |
| `multi_agent` | CrewAI, AutoGen, LangGraph | Auto-detected: `agents`+`steps[].agent`, `messages[].sender`, `events[].node` |
| `mcp` | Model Context Protocol | `interactions[].method` (tools/call, resources/read, prompts/get) |

### New Format Examples

#### OpenAI Chat Completions
```bash
python -m potato.trace_converter --input openai_logs.json --input-format openai --output data.jsonl
```

Input format — messages with `role`/`content` strings, optional `tool_calls`:
```json
{
    "id": "chatcmpl-abc123",
    "model": "gpt-4",
    "messages": [
        {"role": "user", "content": "What is the weather?"},
        {"role": "assistant", "content": null, "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "get_weather", "arguments": "{\"location\":\"NYC\"}"}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "Sunny, 72F"},
        {"role": "assistant", "content": "It's sunny and 72F in NYC."}
    ]
}
```

Also supports the OpenAI Assistants API format with `assistant_id` and `steps` arrays.

#### Anthropic Claude Messages
```bash
python -m potato.trace_converter --input claude_logs.json --input-format anthropic --output data.jsonl
```

Input format — content is a list of typed blocks:
```json
{
    "id": "msg_abc123",
    "model": "claude-sonnet-4-20250514",
    "messages": [
        {"role": "user", "content": "Analyze this data."},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Let me analyze this."},
            {"type": "tool_use", "id": "toolu_1", "name": "python", "input": {"code": "df.describe()"}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "count    100\nmean     42.5"}
        ]}
    ]
}
```

Handles `thinking` blocks, `tool_result` with `is_error`, and request/response pair format.

#### SWE-bench
```bash
python -m potato.trace_converter --input swebench_results.json --input-format swebench --output data.jsonl
```

Input format — coding benchmark instances:
```json
{
    "instance_id": "django__django-16527",
    "problem_statement": "Bug description...",
    "repo": "django/django",
    "model_patch": "diff --git a/...",
    "FAIL_TO_PASS": "[\"test_case_1\"]",
    "test_result": "resolved"
}
```

#### OpenTelemetry/OTLP
```bash
python -m potato.trace_converter --input otel_export.json --input-format otel --output data.jsonl
```

Supports both OTLP nested format (`resourceSpans`) and flattened per-span format (`trace_id`/`span_id`). Uses GenAI Semantic Conventions (`gen_ai.prompt`, `gen_ai.completion`, `tool.name`).

#### Multi-Agent (CrewAI / AutoGen / LangGraph)
```bash
python -m potato.trace_converter --input multi_agent_log.json --input-format multi_agent --output data.jsonl
```

Auto-detects the sub-format:
- **CrewAI**: `agents` list + `steps` with `agent` field
- **AutoGen**: `messages` with `sender`/`receiver`
- **LangGraph**: `events` with `node` field

#### MCP Interaction Logs
```bash
python -m potato.trace_converter --input mcp_session.json --input-format mcp --output data.jsonl
```

Input format — JSON-RPC 2.0 interactions:
```json
{
    "id": "session_001",
    "server": "my-mcp-server",
    "interactions": [
        {"method": "tools/call", "params": {"name": "search", "arguments": {"q": "test"}},
         "result": {"content": [{"type": "text", "text": "Found 5 results"}]}}
    ]
}
```

## Export Format

Export agent evaluation annotations for analysis:

```bash
python -m potato.export --format agent_eval --config config.yaml --output eval_results/
```

This produces:
- `agent_evaluation.json`: Full structured output with per-trace and aggregate statistics
- `agent_evaluation_summary.csv`: One-row-per-trace summary for spreadsheet analysis

## Quality Control

All of Potato's existing QC features work with agent traces:

### Gold Standards

Include traces with known-correct labels:
```json
{"id": "trace_gold_001", "task_description": "...", "conversation": [...],
 "gold_labels": {"task_success": "success", "efficiency": 5}}
```

### Training Phase

Configure a training phase to calibrate annotators:
```yaml
training:
  enabled: true
  num_items: 5
  feedback_mode: immediate
  passing_score: 0.8
```

### Inter-Annotator Agreement

Potato automatically computes IAA metrics:
- Cohen's kappa for trajectory-level categorical labels
- Krippendorff's alpha for Likert scales
- Available in the admin dashboard

## Example Projects

Potato includes eight ready-to-use example projects:

### 1. Agent Trace Evaluation
```bash
python potato/flask_server.py start examples/agent-traces/agent-trace-evaluation/config.yaml -p 8000
```
Text agent traces with full annotation schema (success, efficiency, MAST errors, hallucination spans).

### 2. Visual Agent Evaluation
```bash
python potato/flask_server.py start examples/agent-traces/visual-agent-evaluation/config.yaml -p 8000
```
GUI agent traces with screenshots and grounding accuracy assessment.

### 3. Agent Comparison
```bash
python potato/flask_server.py start examples/agent-traces/agent-comparison/config.yaml -p 8000
```
Side-by-side comparison of two agent traces on the same task.

### 4. RAG Evaluation
```bash
python potato/flask_server.py start examples/agent-traces/rag-evaluation/config.yaml -p 8000
```
RAG pipeline evaluation with retrieval relevance and citation accuracy.

### 5. OpenAI Trace Evaluation
```bash
python potato/flask_server.py start examples/agent-traces/openai-evaluation/config.yaml -p 8000
```
OpenAI Chat Completions traces with tool calls, evaluated for task success and response quality.

### 6. Anthropic Claude Trace Evaluation
```bash
python potato/flask_server.py start examples/agent-traces/anthropic-evaluation/config.yaml -p 8000
```
Anthropic Messages API traces with tool_use/tool_result blocks and thinking blocks.

### 7. SWE-bench Patch Evaluation
```bash
python potato/flask_server.py start examples/agent-traces/swebench-evaluation/config.yaml -p 8000
```
SWE-bench coding agent patches with correctness assessment and code quality ratings.

### 8. Multi-Agent Evaluation
```bash
python potato/flask_server.py start examples/agent-traces/multi-agent-evaluation/config.yaml -p 8000
```
Multi-agent traces from CrewAI, AutoGen, and LangGraph with coordination quality assessment.

## Workflow-Specific Configurations

### Customer Service Agent
- Display: `dialogue` with `per_turn_ratings`
- Key schemas: Issue resolution (radio), response quality (likert), policy compliance (span)

### Coding Agent (SWE-bench style)
- Display: `dialogue` for reasoning + `code` for generated patch
- Key schemas: Patch correctness (radio), code quality (likert), root cause vs symptom (radio)

### Research/RAG Agent
- Display: `dialogue` for trace + `span` for citation verification
- Key schemas: Retrieval relevance (multirate), faithfulness (likert), citation accuracy (span)

### GUI/Computer-Use Agent
- Display: `image` or `gallery` for screenshots + `dialogue` for actions
- Key schemas: Grounding accuracy (radio), navigation efficiency (likert), GUI errors (multiselect)

## Related Documentation

- [Schemas and Templates](schemas_and_templates.md) - All annotation type reference
- [Quality Control](quality_control.md) - Gold standards, training, IAA
- [Configuration](configuration.md) - Complete configuration reference
- [Admin Dashboard](admin_dashboard.md) - Monitoring and management
