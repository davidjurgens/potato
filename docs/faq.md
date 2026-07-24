# Frequently Asked Questions

Short, direct answers to common questions about Potato, annotation, and agent
(agentic) evaluation. See the linked guides for detail.

## What is Potato?

Potato is a **free, open-source, self-hosted annotation and agent-evaluation
platform** for NLP, agentic, and GenAI research. You configure tasks entirely in
YAML — no coding — to annotate text, audio, video, images, documents, and AI
agent traces. See [Quick Start](quick-start.md).

## What is agentic annotation?

Agentic annotation is the practice of **evaluating AI agent runs** — their
reasoning steps, tool calls, and final outputs — rather than just labeling static
text. Potato renders agent *trajectories* and lets humans (and LLM judges) rate
correctness step by step, mark error spans, edit trajectories, and compare agents.
See the [Agent Evaluation Guide](guides/agent-evaluation-guide.md).

## Is Potato a free alternative to LangSmith, LabelBox, or Braintrust?

Yes. Potato is free and self-hosted, and covers the agent-evaluation loop those
tools provide — programmatic evaluators, versioned datasets and experiments,
automation rules, CI gating, LLM-as-judge calibration, and a multi-model arena —
without per-seat or per-trace fees and without sending your data to a SaaS. See
the [comparison](comparison.md).

## How do I evaluate AI agent trajectories?

Import a trace (OpenAI, Anthropic, LangChain, LangGraph, CrewAI, OpenTelemetry,
and more), display it with the `agent_trace` or three-pane `eval_trace` view, and
score it with human schemes or [programmatic evaluators](agent-evaluation/evaluators.md)
(deterministic trajectory match, tool-use correctness, LLM-judge). See
[Agent Traces](agent-evaluation/agent_traces.md) and
[Trajectory Evaluation](agent-evaluation/trajectory_eval.md).

## How do I annotate agent traces and tool calls?

Convert traces with `python -m potato.trace_converter`, then annotate tool calls,
reasoning, and observations per step. Tool calls render natively in the
`coding_trace` and `eval_trace` displays. See [Agent Traces](agent-evaluation/agent_traces.md).

## How do I do LLM-as-judge evaluation and calibration?

Configure an LLM judge, run it over human-labeled items, and measure agreement
(Cohen's κ, ECE/Brier). Potato can **auto-calibrate** the judge by turning human
corrections into few-shot examples, and judges categorical, span, and free-text
outputs. See [Judge Alignment](agent-evaluation/judge_alignment.md) and
[Judge Calibration](ai-intelligence/judge_calibration.md).

## How do I collect RLHF / DPO / preference data?

Use pairwise or ranking schemes (or the [model arena](agent-evaluation/model_arena.md)
for side-by-side model comparison), then export to SFT/DPO via the
[trajectory-correction](agent-evaluation/trajectory_correction.md) and
[dataset](agent-evaluation/datasets_and_experiments.md) exporters.

## Can I gate CI on evaluation quality?

Yes. The [pytest plugin](agent-evaluation/ci_evaluation.md) runs your evaluations
in CI and fails the build when a metric drops below a threshold
(`--potato-threshold correct=0.8`), so prompt/model regressions are caught on every PR.

## How do I capture agent runs from my own code?

Instrument your agent with the [`potato_trace` SDK](integrations/tracing_sdk.md):
decorate functions with `@traceable` and runs are captured and sent to Potato. An
OpenTelemetry exporter is also available.

## Does Potato support crowdsourcing (MTurk, Prolific)?

Yes — native [MTurk and Prolific integration](deployment/crowdsourcing.md) with
platform-specific authentication, plus quality control, training phases, and
inter-annotator agreement.

## What annotation types does Potato support?

20+ schemes: radio/checkbox/Likert, span/NER, spans linking, coreference, ranking,
best-worst scaling, pairwise/conjoint comparison, sliders, soft labels, rubric
grids, and agent-specific schemes (trajectory eval, process-reward, code review).
See the [Schema Gallery](annotation-types/schemas_and_templates.md).

## How large a dataset can Potato handle?

Potato holds items in an ID-keyed in-memory index, so **lookups are O(1)**, not
file scans — the "un-indexed files" concern does not apply. Memory scales with
the number of items (the ML stack is *not* loaded unless you enable a feature
that needs it): the reference 50k-item boot runs in ~5.7 s at ~365 MB RSS, and a
benchmark (`tests/performance/test_large_dataset_boot.py`) guards against
regressions. For very large projects, shard work across
[cohorts](advanced/task_assignment.md) and cap workload with `per_annotator_quota`
so annotators only ever load their own queue. See
[Scaling & Large Datasets](deployment/scaling.md) for details, including bulk
export behavior.

## Can different annotators see different questions or have different permissions?

Yes to both. Assign different annotation schemes to different cohorts with
[Per-Cohort Schemas](advanced/per_cohort_schemas.md), and control who can do what
with [role-based access control](auth-users/roles_and_permissions.md) (admin,
adjudicator, annotator, or custom roles — assigned by user or SSO claim). Dynamic
assignment of *items* to unknown annotators is also built in via
[batch assignment](advanced/task_assignment.md) (cohorts, auto-assignment,
restart-persistent pins).

## Is my data private?

Yes. Potato is self-hosted — your data stays on your infrastructure. There is no
required external service.

## How do I install and run Potato?

```bash
pip install potato-annotation
python potato/flask_server.py start <config.yaml> -p 8000
```

See [Quick Start](quick-start.md) and [Usage](deployment/usage.md).

## Related

- [Glossary](glossary.md) — definitions of annotation & agent-evaluation terms
- [Agent Evaluation Guide](guides/agent-evaluation-guide.md)
- [Comparison with other tools](comparison.md)
