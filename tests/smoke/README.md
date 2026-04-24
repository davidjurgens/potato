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

| File | Purpose |
|---|---|
| `sst2-hybrid-ollama-revision.yaml` | SST-2 config with labeler=vLLM Qwen3.5-4B, revision=ollama gpt-oss:20b, hybrid_dual_track strategy, port 8511. |
| `run_sst2_hybrid_sim.py` | Simulator runner for a vLLM-only SST-2 run on port 8510 (uses `tests/configs/sst2-hybrid-test.yaml`). |
| `run_sst2_ollama_sim.py` | Simulator runner for the ollama-revision config above on port 8511. Slower per cycle but produces higher-quality candidates. |

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
