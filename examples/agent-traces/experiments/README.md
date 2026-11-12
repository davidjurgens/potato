# Datasets & Experiments

Enables Potato's evaluation backbone — **versioned datasets** of evaluation
examples and **experiment runs** that score outputs with programmatic
[evaluators](../../../docs/agent-evaluation/evaluators.md).

## Run

```bash
python potato/flask_server.py start examples/agent-traces/experiments/config.yaml -p 8000
```

Open the admin dashboard, then click **Datasets & Experiments** in the header.

## What you can do

1. **Create a dataset** — a named, versioned collection of examples (inputs +
   optional reference outputs, splits, metadata).
2. **Add examples** — every add/update/delete creates a new immutable version.
   Tag a version (e.g. `prod`) to pin it for experiments.
3. **Run an experiment** — pick a dataset and one or more evaluators
   (trajectory match, tool-use, exact match, edit distance, LLM-judge, …).
4. **Compare experiments** — select two or more runs to see aggregate scores
   side by side, with deltas vs. the baseline so regressions stand out.

## API quick start

```bash
# Create a dataset
curl -X POST http://localhost:8000/datasets/api/datasets \
  -H "Content-Type: application/json" \
  -d '{"name": "agent-eval-v1", "description": "Tool-use correctness"}'

# Add examples (with reference trajectories)
curl -X POST http://localhost:8000/datasets/api/datasets/agent-eval-v1/examples \
  -H "Content-Type: application/json" \
  -d '{"examples": [
        {"id": "t1",
         "inputs": {"task": "weather in NYC"},
         "reference_outputs": {"conversation": [
            {"speaker": "Agent (Action)", "text": "get_weather({\"location\": \"NYC\"})"}]},
         "metadata": {"outputs": {"conversation": [
            {"speaker": "Agent (Action)", "text": "get_weather({\"location\": \"NYC\"})"}]}}}
      ]}'

# Run an experiment with the trajectory-match evaluator
curl -X POST http://localhost:8000/datasets/api/experiments/run \
  -H "Content-Type: application/json" \
  -d '{"dataset": "agent-eval-v1",
       "evaluators": [{"name": "trajectory_match", "params": {"mode": "unordered"}}]}'
```

## Storage

`datasets.storage` selects the backend:

- `file` (default) — git-diffable JSONL snapshots under
  `annotation_output/eval_store/datasets/`.
- `sqlite` — a single `annotation_output/eval_store/datasets.sqlite` for large
  dataset/experiment counts.

## Related

- [Evaluators](../../../docs/agent-evaluation/evaluators.md)
- [Datasets & Experiments guide](../../../docs/agent-evaluation/datasets_and_experiments.md)
