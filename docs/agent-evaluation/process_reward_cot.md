# Chain-of-Thought Process Reward Annotation with LLM Pre-Labeling

**Annotate process rewards for long chain-of-thought (CoT) reasoning, with an
external LLM pre-labeling every step and a human verifying each one.** This guide
covers how to segment a long reasoning trace into steps, display it for efficient
review, have an LLM suggest a reward for each step, and let annotators confirm or
override those suggestions — producing high-quality **Process Reward Model (PRM)**
training data faster than labeling from scratch.

> **In one sentence:** Potato turns a long chain-of-thought into a vertical list of
> reviewable steps, asks an LLM to score each step correct / neutral / incorrect,
> and has a human verify the scores — the standard *"LLM labels, human verifies"*
> workflow for building step-level reward data.

Related: [Process Supervision (PRM Labeling)](process_supervision.md) ·
[Trajectory Evaluation](trajectory_eval.md) ·
[LLM-as-Judge Alignment](judge_alignment.md) ·
[Judge Calibration](../ai-assisted/judge_calibration.md)

---

## What is a process reward?

A **process reward** is a per-step correctness signal used to train a **Process
Reward Model (PRM)** — a model that scores *each step* of a reasoning chain rather
than only the final answer (an *outcome* reward). Process supervision, popularized
by **PRM800K** (Lightman et al. 2023, *"Let's Verify Step by Step"*), improves
reliability on multi-step reasoning because it rewards *how* a model reasons, not
just *whether* it lands on the right answer.

Each step gets one of three labels:

| Reward | Meaning |
|--------|---------|
| **+1** | Correct — the step is valid and moves the solution forward |
| **0** | Neutral — neither helps nor hurts (enable with `allow_neutral: true`) |
| **−1** | Incorrect — introduces an error, invalid logic, or a wrong fact |

## Why LLM pre-labeling + human verification?

Labeling every step of a long CoT by hand is slow. Having an **external LLM
pre-label each step** and then having a human **verify** (confirm or override) is
far faster and is the workflow most teams use to scale PRM data collection. The
human stays in control — the LLM only proposes; nothing is saved as a final label
until a person accepts or changes it.

This mode combines three pieces:

1. **CoT segmentation** — split one long reasoning string into discrete steps.
2. **A long-CoT display** (`cot_trace`) — a tall, scrollable, step-by-step view.
3. **LLM pre-labeling + verification** — the `process_reward` schema with
   `ai_prelabel: true`.

---

## Quick start

Run the ready-made example from the repository root:

```bash
python potato/flask_server.py start examples/agent-traces/cot-process-reward/config.yaml -p 8000
```

Open `http://localhost:8000`, click **✨ AI pre-label steps**, then confirm or
override each suggested reward.

## Configuration

```yaml
# 1. Segment the long CoT string into a step list.
cot_segmentation:
  source_key: reasoning      # item field holding the long CoT string
  strategy: auto             # blank_line | numbered | markers | sentence | llm | auto
  target_key: cot_steps      # step list is written here
  min_step_chars: 30         # merge steps shorter than this into the previous

# 2. Display the steps as a tall, reviewable column.
instance_display:
  fields:
    - key: cot_steps
      type: cot_trace
      display_options:
        show_rail: true          # sticky step-navigation rail
        collapse_long_steps: true
        clamp_lines: 10

# 3. Label + verify per-step rewards.
annotation_schemes:
  - annotation_type: process_reward
    name: step_rewards
    steps_key: cot_steps
    mode: per_step
    allow_neutral: true          # PRM800K-style +1 / 0 / -1
    inline_with_trace: true      # controls attach to each step in the display
    ai_prelabel: true            # show the "AI pre-label steps" button
    require_verification: true   # every AI suggestion must be verified

# 4. Point at any LLM endpoint for pre-labeling.
ai_support:
  enabled: true
  endpoint_type: openai          # openai | ollama | anthropic | vllm | gemini ...
  ai_config:
    model: gpt-4o-mini
    max_tokens: 768              # long CoT + per-step verdicts need headroom
    temperature: 0.1
```

### `cot_segmentation` options

| Key | Default | Description |
|-----|---------|-------------|
| `source_key` | *(required)* | Item field containing the long CoT string |
| `strategy` | `auto` | Segmentation strategy (see below) |
| `target_key` | `cot_steps` | Field the step list is written to |
| `min_step_chars` | `0` | Merge steps shorter than this into the previous step |
| `max_steps` | `200` | Hard cap on number of steps |
| `markers` | *(see below)* | Literal split markers for the `markers` strategy |
| `sentences_per_step` | `1` | Group N sentences per step (`sentence` strategy) |

### `process_reward` options for this workflow

| Key | Default | Description |
|-----|---------|-------------|
| `steps_key` | `steps` | Item field holding the step list (set to your `target_key`) |
| `mode` | `first_error` | `per_step` for true process supervision |
| `allow_neutral` | `false` | Enable the three-way +1 / 0 / −1 label |
| `inline_with_trace` | `false` | Attach ✓/○/✗ controls to each rendered step |
| `ai_prelabel` | `false` | Show the ✨ **AI pre-label steps** button |
| `require_verification` | `false` | Require every AI suggestion to be verified |
| `reward_labels` | — | Override button wording, e.g. `{correct: Valid, incorrect: Flawed}` |

---

## How CoT segmentation works

Set `strategy` to control how a long reasoning string becomes steps:

| Strategy | Splits on |
|----------|-----------|
| `blank_line` | Blank lines between paragraphs |
| `numbered` | Numbered / "Step N:" list markers |
| `markers` | Literal markers (`<step>`, `<think>`, `---`, or your own) |
| `sentence` | Sentence boundaries (group with `sentences_per_step`) |
| `llm` | An LLM proposes the step boundaries (needs an endpoint) |
| `auto` | Tries markers → numbered → blank lines → sentences, first that yields ≥2 steps |

Segmentation runs once when data is loaded and is cached on the item, so the
display and the labeling schema always see the same steps. If your data is
**already segmented** into a step list, skip `cot_segmentation` and point
`steps_key` / the `cot_trace` field straight at that list.

## The verification workflow

1. The annotator opens an instance and sees the reasoning as a vertical list of
   step cards with a sticky **step rail** and a **Jump to next unverified** button.
2. Clicking **✨ AI pre-label steps** calls the LLM (via `/api/prm/prelabel`). Each
   step gets a dashed **"✨ AI: correct/incorrect"** badge whose tooltip shows the
   model's reasoning and confidence.
3. For each step the annotator either **confirms** (clicks the suggested label) or
   **overrides** (clicks a different label). **Accept all AI labels** confirms
   everything at once.
4. Confirmed / overridden steps lose the dashed treatment; the rail and progress
   counter track how many steps remain to verify.

Each stored step records `reward`, `source` (`ai` or `human`), `verified`, and the
original `ai_reward` / `ai_reasoning` / `confidence`, so exports can keep only
human-verified rows.

---

## Frequently asked questions

### How do I segment a chain-of-thought into steps?

Add a `cot_segmentation` block naming the field that holds the reasoning
(`source_key`) and a `strategy`. Use `auto` to let Potato pick, or force
`numbered`, `blank_line`, `markers`, `sentence`, or `llm`. The result is written to
`target_key` (default `cot_steps`), which your display and labeling schema read.

### Can an LLM pre-label the steps for me?

Yes. Set `ai_prelabel: true` on the `process_reward` schema and configure an
`ai_support` endpoint. An **AI pre-label steps** button appears; the LLM suggests a
reward for every step and the annotator verifies each one. Suggestions are never
saved as final labels until a human confirms or overrides them.

### Which LLMs are supported for pre-labeling?

Any endpoint Potato supports: OpenAI-compatible APIs (including local vLLM /
llama.cpp via `base_url`), Ollama, Anthropic, Gemini, and more. The judge
automatically raises `max_tokens` for long chains so per-step verdicts aren't
truncated.

### Is this the same as outcome reward labeling?

No. An outcome reward scores only the final answer; a **process reward** scores
every step. Use `mode: per_step` for true process supervision, or `first_error` for
fast outcome-style supervision where the first mistake is assumed unrecoverable.

### How is the labeled data exported for PRM training?

The [coding-eval exporter](coding_agent_annotation.md) writes
`prm_training_data.jsonl` with one record per instance:
`{instance_id, annotator, steps: [{index, reward, source, verified}], mode}`. The
`source` / `verified` fields let you filter to human-confirmed labels.

### Does per-step data feed inter-annotator agreement?

Yes. The stored `{steps: [{index, reward}]}` blob maps to a `{step_index: reward}`
shape that feeds step-level Krippendorff α / Cohen κ (see step agreement).

---

## Related documentation

- [Process Supervision (PRM Labeling)](process_supervision.md) — the base
  `process_reward` schema and modes
- [Trajectory Evaluation](trajectory_eval.md) — richer per-step error taxonomies
- [LLM-as-Judge Alignment](judge_alignment.md) — measuring human↔judge agreement
- [Coding Agent Annotation](coding_agent_annotation.md) — PRM/DPO/SWE-bench export
- [AI Support](../ai_support.md) — configuring LLM endpoints
