# Glossary

Definitions of annotation and agent-evaluation terms used in Potato. Each term
links to the relevant feature.

## Annotation

**Annotation** — adding structured labels (categories, spans, ratings, rankings)
to data so it can train or evaluate models. In Potato, tasks are defined in YAML.

**Span annotation** — highlighting and labeling a contiguous segment of text
(e.g. an entity, an error, a hallucinated claim). See [span linking](annotation-types/text/span_linking.md).

**Inter-annotator agreement (IAA)** — how consistently multiple annotators label
the same items; measured with Cohen's κ, Fleiss' κ, or Krippendorff's α. See
[Quality Control](workflow/quality_control.md).

**Adjudication** — resolving disagreements between annotators to produce gold
labels. See [Adjudication](administration/adjudication.md).

**Gold label** — the agreed-upon correct annotation for an item, used as a
reference for scoring judges or models.

## Agentic evaluation

**Agentic annotation / agent evaluation** — evaluating an AI agent's *run*
(reasoning, tool calls, outputs), not just static text. See the
[Agent Evaluation Guide](guides/agent-evaluation-guide.md).

**Trace** — a record of an agent's execution: the sequence of messages, tool
calls, and observations for one task. Potato imports traces from OpenAI,
Anthropic, LangChain, LangGraph, CrewAI, OpenTelemetry, and more.

**Trajectory** — the ordered sequence of an agent's steps (thoughts → tool calls
→ observations → answer). [Trajectory evaluation](agent-evaluation/trajectory_eval.md)
scores each step.

**Tool call (function call)** — an agent's invocation of an external tool/function
with arguments; a primary unit of agent evaluation.

**Trajectory match** — a deterministic evaluator that compares an agent's
tool-call sequence to a reference (strict / unordered / subset / superset). See
[Evaluators](agent-evaluation/evaluators.md).

**LLM-as-judge** — using an LLM to score model/agent outputs against a rubric.
Potato measures and [calibrates](agent-evaluation/judge_alignment.md) the judge
against human gold (Cohen's κ, ECE).

**Process Reward Model (PRM)** — a model that scores the correctness of each
*step* in a trajectory (not just the final answer); Potato's `process_reward`
scheme collects this training data.

**RLHF / DPO / SFT data** — preference and demonstration data for training:
SFT (`prompt → completion`), DPO (`prompt → chosen / rejected`). Potato exports
these from pairwise, ranking, and [trajectory-correction](agent-evaluation/trajectory_correction.md) tasks.

**Experiment** — one run of evaluators over a versioned
[dataset](agent-evaluation/datasets_and_experiments.md), producing comparable
aggregate scores over time.

**Dynamic slice** — a saved semantic + metadata filter that auto-includes new
matching traces, used to find what to review. See [Semantic Curation](agent-evaluation/semantic_curation.md).

**Model arena** — sending one prompt to several models side by side and recording
which is best (a win-rate leaderboard). See [Model Arena](agent-evaluation/model_arena.md).

## Related

- [FAQ](faq.md)
- [Agent Evaluation Guide](guides/agent-evaluation-guide.md)
