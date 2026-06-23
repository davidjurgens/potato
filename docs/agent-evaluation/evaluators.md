# Programmatic Evaluators

Potato ships a Flask-free **evaluators library** (`potato.evaluators`) for scoring
agent trajectories and text outputs automatically — the deterministic and
LLM-as-judge checks that complement human annotation. These evaluators are the
building block used by the experiment runner, the automation engine, and the
pytest CI plugin, and they are also usable on their own.

## Overview

Every evaluator implements one contract:

```python
result = evaluator.evaluate(outputs=..., reference_outputs=..., inputs=...)
result.score   # normalized float, conventionally 0.0–1.0 (higher = better), or None
result.value   # raw/categorical value (bool, label, count)
result.comment # human-readable explanation
result.metadata
```

Trajectories may be passed in any shape Potato understands — OpenAI-style message
lists, Potato's canonical `conversation` turns (what every
[trace converter](../agent-evaluation/agent_traces.md) produces), or a
`CanonicalTrace` object. Normalization is automatic.

## Trajectory match (deterministic)

Compares the agent's tool-call sequence to a reference.

```python
from potato.evaluators import TrajectoryMatchEvaluator

ev = TrajectoryMatchEvaluator(
    mode="unordered",                 # strict | unordered | subset | superset
    tool_args_match_mode="subset",    # exact | ignore | subset | superset
    tool_args_match_overrides={"search": "ignore"},
)
result = ev.evaluate(outputs=agent_trace, reference_outputs=gold_trace)
```

| `mode` | Passes when… |
|--------|--------------|
| `strict` | identical tool calls, same order |
| `unordered` | same multiset of tool calls, any order |
| `subset` | agent called only tools that appear in the reference |
| `superset` | agent called at least the reference tools (extras allowed) |

| `tool_args_match_mode` | Arg comparison |
|------------------------|----------------|
| `exact` | argument dicts must be equal |
| `ignore` | only the tool name matters |
| `subset` | agent args ⊆ reference args |
| `superset` | reference args ⊆ agent args |

`tool_args_match_overrides` lets one tool match loosely while others stay strict.

## Tool-use correctness

```python
from potato.evaluators import ToolUseEvaluator, ToolCallAccuracyEvaluator

# Did the agent call a specific tool (optionally with expected args)?
ToolUseEvaluator(expected_tool="submit", expected_args={"id": 1}).evaluate(outputs=trace)

# What fraction of reference tool calls did the agent reproduce? (partial credit)
ToolCallAccuracyEvaluator(args_match_mode="exact").evaluate(
    outputs=trace, reference_outputs=gold)
```

## LLM-as-judge (reference-free)

Scores trajectory *quality* without a gold reference — useful because many valid
agent paths exist. Reuses the same `ai_support` endpoint config as the rest of
Potato (OpenAI/Anthropic/Ollama/vLLM/…).

```python
from potato.evaluators import LLMTrajectoryJudge

judge = LLMTrajectoryJudge(config=task_config, continuous=True)  # 0.0–1.0 score
result = judge.evaluate(outputs=agent_trace, inputs=task_prompt)
```

Set `continuous=False` (the default) for a pass/fail verdict.

## Heuristic / code evaluators

```python
from potato.evaluators import (
    ExactMatch, Contains, RegexMatch, EditDistance,
    JSONValid, JSONSchemaMatch, EmbeddingDistance,
)

ExactMatch(case_sensitive=False).evaluate(outputs="HI", reference_outputs="hi")
Contains(substring="error").evaluate(outputs=text)
EditDistance().evaluate(outputs=a, reference_outputs=b)       # 1 - dist/maxlen
JSONSchemaMatch(schema).evaluate(outputs=model_json)          # needs `jsonschema`
EmbeddingDistance().evaluate(outputs=a, reference_outputs=b)  # lazy ML import
```

`EmbeddingDistance` imports `sentence_transformers` lazily on first use, or accepts
an injected `embed_fn` (e.g. an embedding API). Importing the library never pulls
the ML stack.

## Graph-trajectory eval (LangGraph, via agentevals)

For LangGraph node/transition evaluation, Potato reuses the MIT-licensed
[`agentevals`](https://github.com/langchain-ai/agentevals) package through a lazy
adapter — install it only if you need it:

```python
from potato.evaluators import agentevals_adapter

if agentevals_adapter.is_available():
    ev = agentevals_adapter.graph_trajectory_strict_match()
```

## Configuring evaluators declaratively

The registry maps names → evaluators so they can be configured in YAML (used by
the experiment runner and automation engine):

```python
from potato.evaluators import build_evaluator, list_evaluators

list_evaluators()  # [{"name": "trajectory_match", "description": ...}, ...]
ev = build_evaluator("trajectory_match", {"mode": "unordered"})
```

## Related

- [Agent trace annotation](agent_traces.md)
- [Datasets & experiments](datasets_and_experiments.md) *(uses these evaluators)*
- [Trajectory evaluation schema](trajectory_eval.md) *(human counterpart)*
