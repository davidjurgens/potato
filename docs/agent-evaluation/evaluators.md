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

## Rubric DAG (decision-tree judge)

A `rubric_dag` evaluator turns a rubric into a **decision tree the judge
traverses**. At each node the judge answers one discrete question; the chosen
branch leads either to another node or to a **leaf with a fixed, authored score**.
The scores are deterministic (you write them, the model doesn't invent a number),
the structure is auditable, and the **full traversed path is recorded** — so a
human-in-the-loop reviewer can correct a single branch decision instead of
re-grading the whole output.

```yaml
# Configure declaratively (used by experiments / automation / CI):
evaluators:
  - name: rubric_dag
    params:
      dag:
        key: answer_quality
        root: answers
        nodes:
          answers:
            question: "Does the response directly answer the question?"
            choices: [yes, partially, no]
            branches:
              yes: grounded                          # -> next node
              partially: {score: 0.5, label: partial}# -> leaf
              no: {score: 0.0, label: no answer}
          grounded:
            question: "Is the answer well-supported (no fabricated claims)?"
            choices: [yes, no]
            branches:
              yes: {score: 1.0, label: complete}
              no:  {score: 0.7, label: unsourced}
```

```python
from potato.evaluators import make_rubric_dag, RUBRIC_PRESETS

# Use the built-in rubric library, or pass your own `dag=`:
ev = make_rubric_dag(config, preset="answer_quality")
result = ev.evaluate(inputs="Capital of France?", outputs="Paris [gouvernement.fr].")
result.score                      # 1.0
result.metadata["path"]           # [{node, question, choice, reasoning}, ...]
```

`RUBRIC_PRESETS` is a small **reusable rubric library** (add your own by appending
to it). The evaluator reuses the judge endpoint config (`judge_alignment.ai_support`
or `ai_support`) and is robust to models that don't honor JSON output (it recovers
the chosen option from the raw text). Compare with the annotation-facing
[`rubric_eval`](../annotation-types) schema, which collects *human* multi-criteria
scores — the two pair naturally (judge proposes via the DAG, humans verify).

## RAG triad (reference-free)

The three most-adopted RAG metrics (TruLens/Ragas/Phoenix), reference-free (no gold
answer needed):

| Evaluator | Measures |
|-----------|----------|
| `context_relevance` | Is the retrieved context relevant to the question? |
| `groundedness` | Is the answer supported by the context (faithfulness)? |
| `answer_relevance` | Does the answer actually address the question? |

```python
from potato.evaluators import rag_triad

triad = rag_triad(config)          # {context_relevance, groundedness, answer_relevance}
g = triad["groundedness"].evaluate(
    inputs={"question": q, "context": retrieved_docs}, outputs=answer)
g.score                            # supported_claims / total_claims
g.metadata["claims"]               # [{claim, supported}, ...] — per-claim verdicts
```

The question comes from `inputs` (or `inputs["question"]`), the answer from
`outputs`, and the retrieved context from a `context=` kwarg (or `inputs["context"]`).

**Groundedness uses claim decomposition**: the answer is split into atomic claims and
each is checked against the context, so the score is `supported / total` and *every
claim verdict is recorded* in `metadata["claims"]` — a natural human-in-the-loop
adjudication target (annotators confirm or correct per-claim).

!!! note "max_tokens for claim decomposition"
    Groundedness asks the judge to enumerate claims, which can be long. If your judge
    endpoint's `max_tokens` is small (the default is 100), the claim list can be
    truncated and groundedness returns `None`. Set a higher `max_tokens` (e.g. 512)
    in the judge endpoint's `ai_config` for reliable claim decomposition.

## Agent-as-a-judge (per-requirement, with evidence)

A flat LLM judge gives one holistic score; an **agent-as-judge** inspects the
*intermediate steps* and judges the trajectory against **each acceptance
requirement** separately, citing evidence. This aligns far better with human
judgment on complex tasks (Zhuge et al. 2024 report ~90% per-requirement alignment
vs ~70% for a flat judge).

```python
from potato.evaluators import AgentAsJudgeEvaluator

ev = AgentAsJudgeEvaluator(config, requirements=[
    "The flight is under $400",
    "The flight is refundable",
    "The itinerary was emailed to the user",
])
r = ev.evaluate(inputs={"question": task}, outputs=trajectory)
r.score                       # fraction of requirements satisfied
r.metadata["verdicts"]        # [{requirement, satisfied, evidence}, ...]
```

Requirements come from the `requirements` param or `inputs["requirements"]`; the
trajectory from `outputs` (any shape `normalize_trajectory` accepts). Each verdict
is **evidence-backed and discrete** — the natural unit for a **human spot-check**:
an annotator confirms or overrides each one, and those corrections feed the
[judge↔human alignment](judge_alignment.md) corpus (track per-requirement κ, then
auto-calibrate). In practice the agent-judge catches gaps a holistic judge misses —
e.g. an agent that *plans* to email an itinerary but never does fails the "emailed"
requirement with the booking-confirmation step cited as evidence.

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
