# Smoke tests — full-pipeline live LLM runs

Runnable scripts that exercise the solo-mode pipeline end-to-end against a
real LLM endpoint (vLLM, ollama). These are **not collected by pytest** —
`pytest.ini` has `--ignore=tests/smoke` because they depend on a live LLM
backend, take several minutes to run, and are not deterministic.

Use them manually to validate:
- refinement-cycle triggering and validation-gate behavior
- prompt-version evolution across cycles
- background LLM-labeling throughput
- hybrid-dual-track fallback (prompt_edit → ICL) when the revision model
  fails to beat baseline

## What's here

### Solo-mode refinement smokes

| File | Purpose |
|---|---|
| `sst2-hybrid-ollama-revision.yaml` | SST-2 config with labeler=vLLM Qwen3.5-4B, revision=ollama gpt-oss:20b, hybrid_dual_track strategy, port 8511. |
| `run_sst2_hybrid_sim.py` | Simulator runner for a vLLM-only SST-2 run on port 8510 (uses `tests/configs/sst2-hybrid-test.yaml`). |
| `run_sst2_ollama_sim.py` | Simulator runner for the ollama-revision config above on port 8511. Slower per cycle but produces higher-quality candidates. |

### Agent-aware simulator smokes

| File | What it covers | Typical runtime |
|---|---|---|
| `run_agent_trace_sim.py` | API-level smoke: `AgentSimulatorStrategy` (Gemma4 vision via Ollama) annotates `examples/agent-traces/agent-trace-evaluation/` end-to-end, batched per instance. Reports per-schema label distributions and gold-label accuracy on the `_gold` instances shipped with the example. | ~165s |
| `run_interactive_agent_sim.py` | Drives a live `interactive_chat` session against `examples/agent-testing/interactive-agent-test/` (echo agent_proxy), then has the agent strategy rate the trajectory. Persona model is `llama3.2:3b`; rater is `gemma4:e4b`. | ~25s |
| `run_playwright_ui_sim.py` | Slow-but-real UI smoke: drives the rendered annotation page through Chromium via Playwright. Reads instance data via the API (cookie-shared) but applies annotations with real DOM events and clicks the rendered `#next-btn`. Catches UI regressions the API smokes can't see. | ~32s |

### Coding-agent simulator smokes

| File | What it covers | Typical runtime |
|---|---|---|
| `run_swebench_sim.py` | Tier 1: agent strategy as-is against `examples/agent-traces/swebench-evaluation/` (issue + diff + test result). Confirms the existing pipeline handles SWE-bench-style data without code changes. | ~55s |
| `run_coding_agent_eval_sim.py` | Tier 2: exercises the new `structured_turns` rendering — `{role, content, tool_calls}` shape with file reads/edits/bash output rendered as text for the rater. | ~30s |
| `run_coding_agent_prm_sim.py` | Tier 3: exercises the new `process_reward` wire format — rater picks the first wrong step in each trace; strategy expands to `{steps:[...], mode:"first_error"}` JSON. | ~35s |
| `run_coding_agent_review_sim.py` | Tier 4: exercises the new `code_review` wire format — rater produces verdict + per-file comments + ratings; strategy serializes the structured judgement. | ~30s |
| `run_live_coding_agent_sim.py` | Tier 5a: full pipeline — persona LLM drives the new `subprocess_coding` agent_proxy that actually executes Python/shell in a per-session tempdir; rater grades the resulting conversation. Proves end-to-end live agent evaluation. | ~17s |
| `run_docker_coding_agent_sim.py` | Tier 5b: same as 5a but uses `docker_coding` agent_proxy (ephemeral container with `--network=none`, `--memory`, `--cpus`, `--read-only`). Skips with exit 77 if `docker` CLI is missing. | ~30s with cold image pull |

## Running

Both scripts assume `cwd` is the repo root.

### vLLM-only (fast, ~7–8 min)

```bash
# Terminal 1: start the server
python potato/flask_server.py start tests/configs/sst2-hybrid-test.yaml -p 8510

# Terminal 2: drive the simulator
python tests/smoke/run_sst2_hybrid_sim.py
```

### ollama-revision (slower, ~25–30 min)

Requires a local ollama with `gpt-oss:20b` pulled.

```bash
# Terminal 1
python potato/flask_server.py start tests/smoke/sst2-hybrid-ollama-revision.yaml -p 8511

# Terminal 2
python tests/smoke/run_sst2_ollama_sim.py
```

### Agent-trace smoke (~90s)

```bash
ollama pull gemma4:e4b      # one-time

# Terminal 1
python potato/flask_server.py start \
    examples/agent-traces/agent-trace-evaluation/config.yaml -p 8520

# Terminal 2
python tests/smoke/run_agent_trace_sim.py
```

Pass criteria: every user submits annotations, no LLM/HTTP errors, at
least one categorical schema receives ≥2 distinct label choices across
the run, and gold-label accuracy ≥ 50% on the `_gold` instances.

### Interactive-chat smoke (~45s)

```bash
ollama pull llama3.2:3b    # persona model
ollama pull gemma4:e4b      # rater (already pulled if you ran the above)

# Terminal 1
python potato/flask_server.py start \
    examples/agent-testing/interactive-agent-test/config.yaml -p 8521

# Terminal 2
python tests/smoke/run_interactive_agent_sim.py
```

The simulator plays the user, the server's `agent_proxy.type: echo`
plays the agent, and the agent strategy rates `task_success`,
`naturalness`, `helpfulness`, `comments` on each completed session.

### Playwright UI smoke (~35s)

```bash
pip install playwright          # one-time
playwright install chromium     # one-time

# Terminal 1
python potato/flask_server.py start \
    examples/agent-traces/agent-trace-evaluation/config.yaml -p 8522

# Terminal 2
python tests/smoke/run_playwright_ui_sim.py

# Run with a visible browser:
POTATO_PLAYWRIGHT_HEADLESS=0 python tests/smoke/run_playwright_ui_sim.py
```

Annotations come from the same `AgentSimulatorStrategy` as the API
smoke; the difference is that this runner clicks through the rendered
DOM (radios, checkboxes, textareas) and the `#next-btn` between
instances. Per-instance log lines like
`(DOM 7/9)` count how many target inputs were successfully matched in
the page — a sudden drop signals a UI / template regression.

### Coding-agent smokes (~3 min total without Docker)

```bash
ollama pull gemma4:e4b           # rater for all
ollama pull llama3.2:3b          # planner for the live runners

# Tier 1 — swebench
python potato/flask_server.py start \
    examples/agent-traces/swebench-evaluation/config.yaml -p 8523
python tests/smoke/run_swebench_sim.py

# Tier 2 — coding-agent-evaluation (structured_turns rendering)
python potato/flask_server.py start \
    examples/agent-traces/coding-agent-evaluation/config.yaml -p 8524
python tests/smoke/run_coding_agent_eval_sim.py

# Tier 3 — coding-agent-prm (process_reward wire format)
python potato/flask_server.py start \
    examples/agent-traces/coding-agent-prm/config.yaml -p 8525
python tests/smoke/run_coding_agent_prm_sim.py

# Tier 4 — coding-agent-review (code_review wire format)
python potato/flask_server.py start \
    examples/agent-traces/coding-agent-review/config.yaml -p 8526
python tests/smoke/run_coding_agent_review_sim.py

# Tier 5a — live coding agent (subprocess sandbox)
python potato/flask_server.py start \
    examples/agent-testing/coding-agent-live-test/config.yaml -p 8527
python tests/smoke/run_live_coding_agent_sim.py

# Tier 5b — live coding agent (Docker sandbox); requires docker
docker pull python:3.11-slim
python potato/flask_server.py start \
    examples/agent-testing/coding-agent-docker-test/config.yaml -p 8528
python tests/smoke/run_docker_coding_agent_sim.py
```

The Tier 5 runners exercise the new `subprocess_coding` and
`docker_coding` agent_proxy variants. Both honour the existing
`SafetySandbox` knobs (`max_steps`, `max_session_seconds`,
`rate_limit_per_minute`, `request_timeout_seconds`) plus their own
per-step timeout and output cap. `subprocess_coding` is fast but **not
a security boundary** — use `docker_coding` for less-trusted planner
output.

Each runner prints a per-cycle summary at the end (baseline vs best candidate,
APPLIED/REJECTED, strategy). For deeper inspection, query the server while it's
still running:

```bash
curl -s http://localhost:8511/solo/api/refinement/log | jq
curl -s http://localhost:8511/solo/api/status | jq
```

Or use the CLI viewer after the run:

```bash
python scripts/view_refinement_log.py tests/output/sst2-hybrid-ollama/solo_state
```

## Before running

1. Confirm the LLM endpoint is reachable (e.g. `curl http://burger.si.umich.edu:8001/v1/models` or `ollama list`).
2. Clear prior state if you want a clean run:
   `mv tests/output/sst2-hybrid-ollama tests/output/sst2-hybrid-ollama.prev-$(date +%s)`
3. Make sure nothing else is on the port (`lsof -ti:8511 | xargs -r kill -9`).

## What a successful run looks like

- Simulator progresses through 7 phases (setup → parallel-annotation → active-annotation → autonomous-labeling → final-validation).
- Refinement cycles fire at `trigger_interval` boundaries once enough disagreements accumulate (min_val + min_train = 15+ by default).
- Applied cycles create new prompt versions (`Created prompt version N by validated_refinement` or `validated_refinement_icl` in the server log).
- Background labeling log lines appear continuously: `Labeled N instances in background`.
- Final per-version agreement stays at or above the pre-refinement baseline — the validation gate's job.
