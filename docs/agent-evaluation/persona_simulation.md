# Simulated-User Personas & Multi-Turn Evaluation

Evaluate an agent the way real users exercise it — over a **multi-turn
conversation**, driven by a goal-directed simulated **user persona** (the
τ-bench / τ²-bench setup), not a single prompt. A persona LLM plays the user; your
agent replies; after the dialogue a judge decides whether the **expected outcome**
was achieved. Because stochastic agents aren't reliable on one run, **pass^k**
reports the fraction of independent trials that succeed.

> Potato's other simulator models an *annotator* (competence profiles). This models
> a goal-driven *end user* conversing with a target **agent**.

## Personas

`PERSONA_LIBRARY` ships deliberately diverse personas — default simulated users are
too cooperative, which over-states agent quality:

| Persona | Behavior |
|---------|----------|
| `cooperative` | Friendly, answers directly (easy baseline) |
| `terse` | One-line replies, gives only what's asked |
| `impatient` | Pushes the agent to hurry, shows mild frustration |
| `info_withholding` | Volunteers nothing; answers only the exact question asked |

Define your own with `Persona(name, goal, style)`.

## Running a conversation

```python
from potato.simulator.persona_simulator import (
    simulate_conversation, pass_hat_k, ConversationGolden,
)

golden = ConversationGolden(
    scenario="I want to book a flight from Detroit to San Francisco next Tuesday.",
    expected_outcome="The assistant gathers the details and explicitly confirms a booking.",
    persona="info_withholding",   # stress the agent with a reluctant user
    max_turns=6,
)

def agent_fn(history):            # your target agent: (history) -> reply
    return my_agent.respond(history)

result = simulate_conversation(golden.persona, agent_fn, golden, config=config)
result.success       # judged True/False
result.transcript()  # the full dialogue
```

`config` supplies the user/judge LLM (`ai_support` or `judge_alignment.ai_support`).
The same `agent_fn` contract works for any agent — a local function, an HTTP call,
or another Potato endpoint.

## pass^k reliability

```python
report = pass_hat_k(golden.persona, agent_fn, golden, k=5, config=config)
report["pass_hat_k"]   # e.g. 0.6  -> succeeded in 3 of 5 independent trials
```

A single success can be luck; `pass^k` surfaces how *reliably* the agent handles
the scenario — the metric τ-bench introduced and commercial eval tools rarely
report.

## Related documentation

- [Agent-as-a-judge](evaluators.md#agent-as-a-judge-per-requirement-with-evidence) —
  score the resulting trajectory per requirement
- [Trajectory Evaluation](trajectory_eval.md) — human per-step review of the dialogue
- [Model Arena](model_arena.md) — compare agents/models head-to-head
