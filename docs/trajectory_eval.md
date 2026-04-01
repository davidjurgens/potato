# Trajectory Evaluation

Per-step error annotation for agent traces. Based on research from TRAIL (Trace Reasoning and Agentic Issue Localization), AgentRewardBench, and Anthropic's "Demystifying Evals for AI Agents."

## Overview

The `trajectory_eval` schema displays each step of an agent's trajectory as a card. For each step, the annotator can:

1. **Mark correctness**: correct, incorrect, or partially correct
2. **Classify the error type** from a configurable taxonomy (with optional subtypes)
3. **Assign severity** with configurable weights
4. **Write a rationale** explaining the error
5. View an auto-computed **quality score** based on severity penalties

## Configuration

```yaml
annotation_schemes:
  - annotation_type: trajectory_eval
    name: step_evaluation
    description: "Evaluate each agent step"
    steps_key: steps           # field in instance data containing step list
    step_text_key: action      # which field in each step to display
    correctness_options:       # customize correctness labels
      - correct
      - incorrect
      - partially_correct
    error_types:               # error taxonomy
      - name: reasoning
        subtypes:
          - logical_error
          - factual_error
          - planning_error
      - name: execution
        subtypes:
          - wrong_tool
          - wrong_args
          - api_error
      - name: safety
        subtypes:
          - harmful_action
          - data_leak
          - scope_violation
    severities:                # severity levels with penalty weights
      - name: minor
        weight: -1
      - name: major
        weight: -5
      - name: critical
        weight: -10
    show_score: true           # show computed quality score
    max_score: 100             # maximum quality score
```

## Data Format

Each instance should contain a list of steps under the configured `steps_key`:

```json
{
  "id": "trace_001",
  "task_description": "Find the weather in San Francisco",
  "steps": [
    {"action": "search_web('SF weather')", "thought": "Need to find weather info."},
    {"action": "click_result(0)", "thought": "Opening first result."},
    {"action": "extract_text('.weather')", "thought": "Getting the data."}
  ]
}
```

## Output Format

Annotations are stored as JSON in a hidden input:

```json
{
  "steps": [
    {"step_index": 0, "correctness": "correct"},
    {
      "step_index": 1,
      "correctness": "incorrect",
      "error_type": "execution",
      "error_subtype": "wrong_tool",
      "severity": "major",
      "rationale": "Should have used a more specific selector"
    }
  ],
  "score": 95
}
```

## Why Not `per_turn_ratings`?

The existing `per_turn_ratings` in `dialogue_display.py` only supports inline Likert scales (numeric ratings). Trajectory evaluation needs:

- **Structured error classification** (type dropdown + severity + rationale)
- **Correctness toggles** that show/hide the error form
- **Score rollup** across all steps
- The ability to **mark steps as correct** without expanding the error form

## Example

```bash
python potato/flask_server.py start examples/agent-traces/trajectory-evaluation/config.yaml -p 8000
```

## Related Documentation

- [Error Span](error_span.md) — similar MQM-style error annotation for text
- [Rubric Evaluation](rubric_eval.md) — multi-criteria evaluation grid
- [Schemas and Templates](schemas_and_templates.md) — gallery of all annotation types
