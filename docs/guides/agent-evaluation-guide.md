# Agent Evaluation Guide

This guide covers evaluating AI agent systems with Potato, including coding agents, web agents, RAG pipelines, and multi-agent systems.

## Overview

Potato supports evaluating AI agents at multiple levels:

| Level | What You Annotate | Example |
|-------|------------------|---------|
| **Trajectory** | Overall task success | "Did the agent complete the task?" |
| **Step** | Individual action correctness | Per-turn Likert ratings on each agent step |
| **Span** | Specific text segments | Highlight hallucinated claims, factual errors |
| **Comparison** | Side-by-side evaluation | "Which agent performed better?" |

## Trace Conversion

Import traces from any major agent framework:

```bash
python -m potato.trace_converter --input traces.json --input-format openai --output data.jsonl
```

Supported formats: OpenAI, Anthropic/Claude, ReAct, LangChain, LangFuse, WebArena, SWE-bench, OpenTelemetry, CrewAI/AutoGen/LangGraph, MCP, Aider, Claude Code, ATIF, SWE-Agent, and Web Agent.

For full details, see **[Agent Traces](../agent-evaluation/agent_traces.md)**.

## Coding Agent Evaluation

Evaluate agentic coding systems (Claude Code, SWE-Agent, Aider) with:

- Diff rendering for code changes
- Process Reward Model (PRM) annotation
- Code review workflows

See **[Coding Agent Annotation](../agent-evaluation/coding_agent_annotation.md)**.

## Web Agent Evaluation

Review GUI agent traces with an interactive screenshot viewer:

- Step-by-step navigation through screenshots
- SVG overlays showing clicks, bounding boxes, mouse paths, and scroll actions
- Inline annotation controls per step
- Live browsing mode with automatic trace recording

See **[Web Agent Annotation](../agent-evaluation/web_agent_annotation.md)**.

## Trajectory Evaluation

Per-step error marking with typed error taxonomies:

- Mark individual steps as correct, incorrect, or partially correct
- Assign error types (hallucination, reasoning error, tool misuse, etc.)
- Span-level annotation within agent output

See **[Trajectory Evaluation](../agent-evaluation/trajectory_eval.md)**.

## Live Agent Interaction

Observe and interact with a live AI agent in real time, recording traces as you go:

See **[Live Agent Interaction](../agent-evaluation/live_agent.md)**.

## Continuous Evaluation Loop

Beyond annotating individual traces, Potato closes the loop from production traffic
to graded, regression-gated evaluation:

- **Capture** — instrument your agent with the [`@traceable` tracing SDK](../integrations/tracing_sdk.md)
  (`potato_trace`), or POST traces to the ingestion webhook / Langfuse poller.
- **Automate** — [automation rules](../agent-evaluation/automation_rules.md) run
  `filter → sampling rate → actions` over every incoming trace, routing it to the
  annotation queue, an eval dataset, an evaluator, an outbound webhook, or a notification.
- **Curate** — build versioned [datasets & experiments](../agent-evaluation/datasets_and_experiments.md)
  (file or SQLite, tagged versions, splits), and use the [semantic Catalog](../agent-evaluation/semantic_curation.md)
  (embedding search + dynamic slices) to find the traces worth reviewing.
- **Evaluate** — score outputs with [programmatic evaluators](../agent-evaluation/evaluators.md)
  (deterministic trajectory match, tool-use correctness, reference-free LLM-judge,
  heuristics), or compare models head-to-head in the [model arena](../agent-evaluation/model_arena.md).
- **Gate CI** — run evals inside pytest and fail the build on score-threshold
  regressions with the [CI evaluation plugin](../agent-evaluation/ci_evaluation.md).
- **Calibrate judges** — measure and tune an LLM judge against human gold with
  [judge alignment](../agent-evaluation/judge_alignment.md) (Cohen's κ, auto-calibration
  from human corrections) and blind multi-LLM [judge calibration](../ai-intelligence/judge_calibration.md);
  judges work on categorical, span, and free-text outputs.

Inspect and control all of this from the admin dashboard (Datasets & Experiments,
Automation, Catalog, Arena links) and the `/admin/eval/*` API.

## Using AI Assistance for Evaluation

Speed up agent evaluation with AI-powered features:

- **[AI Support](../ai-intelligence/ai_support.md)** - LLM label suggestions for agent evaluation tasks
- **[Chat Support](../ai-intelligence/chat_support.md)** - Ask an LLM questions about complex agent traces

## Example Configurations

Ready-to-use examples in `examples/agent-traces/`:

| Example | What It Evaluates |
|---------|-------------------|
| `agent-trace-evaluation/` | Text agent traces with MAST error taxonomy |
| `visual-agent-evaluation/` | GUI agents with screenshot grounding |
| `agent-comparison/` | Side-by-side A/B agent comparison |
| `rag-evaluation/` | RAG retrieval relevance and citation accuracy |
| `openai-evaluation/` | OpenAI Chat API traces with tool calls |
| `anthropic-evaluation/` | Claude messages with tool_use blocks |
| `swebench-evaluation/` | Coding agents with patch correctness ratings |
| `multi-agent-evaluation/` | Multi-agent coordination (CrewAI, AutoGen, LangGraph) |
| `web-agent-review/` | Pre-recorded web traces with overlay viewer |
| `web-agent-creation/` | Live web browsing with trace recording |

Run any example:

```bash
python potato/flask_server.py start examples/agent-traces/agent-trace-evaluation/config.yaml -p 8000
```
