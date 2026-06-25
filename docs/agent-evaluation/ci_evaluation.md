# CI Evaluation (pytest plugin)

Run Potato evaluations inside your own **pytest** suite and **gate CI** on
aggregate score thresholds — so a prompt/model change that regresses quality
fails the build, the same way a unit test does. This is the "operationalize
eval" layer on top of the [evaluators](evaluators.md) and
[datasets/experiments](datasets_and_experiments.md).

## Install

The plugin ships with Potato and auto-loads once installed:

```bash
pip install -e .          # registers the `potato_eval` pytest plugin
```

Without installing, load it explicitly: `pytest -p potato.testing.pytest_plugin`.

## Write eval tests

Mark a test `@pytest.mark.potato_eval` and request the `potato_eval` fixture:

```python
import pytest
from potato.testing import expect

@pytest.mark.potato_eval
@pytest.mark.parametrize("case", CASES, ids=[c["q"] for c in CASES])
def test_agent(case, potato_eval):
    out = my_agent(case["q"])
    potato_eval.log_inputs({"question": case["q"]})
    potato_eval.log_outputs(out)
    potato_eval.log_reference_outputs(case["expected"])

    potato_eval.log_feedback("correct", 1.0 if out == case["expected"] else 0.0)
    potato_eval.log_feedback("similarity", 1.0 - expect.edit_distance(out, case["expected"]).value)

    expect(out).to_contain(case["expected"])   # per-case hard assertion
```

- **`potato_eval`** fixture: `log_inputs`, `log_outputs`, `log_reference_outputs`,
  `log_feedback(key, score)`.
- **`expect(...)`** fluent assertions: `.to_equal`, `.to_contain`,
  `.to_be_less_than`, `.to_be_greater_than`, `.to_be_between`, `.to_be_close_to`,
  plus `expect.edit_distance(a, b)` and `expect.embedding_distance(a, b)`.

`log_feedback` scores are aggregated across all eval tests (mean per key); a
failed `expect` fails that individual test as usual.

## Gate the build

```bash
pytest tests/eval/ \
  --potato-threshold correct=0.8 \
  --potato-threshold similarity=0.7 \
  --potato-experiment agent-regression
```

| Option | Effect |
|--------|--------|
| `--potato-threshold KEY=MIN` | Fail the run if `mean(KEY) < MIN`. Repeatable. |
| `--potato-experiment DATASET` | Record the run as an [Experiment](datasets_and_experiments.md) (so it shows in the comparison view). |
| `--potato-no-sync` | Skip experiment recording. |

A summary prints at the end:

```
============================== Potato evaluation ===============================
cases: 3
  correct: 1.000  (threshold 0.8)
  similarity: 1.000  (threshold 0.7)
recorded experiment: ci-0001
```

If a threshold is violated the run exits non-zero (failing the CI job) and prints
`THRESHOLD FAILED: <key> = <actual> < <min>`.

## Environment

| Var | Meaning |
|-----|---------|
| `POTATO_EVAL_STORE` | Directory for recorded experiments (default `./eval_store`). |
| `POTATO_EVAL_STORAGE` | `file` (default) or `sqlite`. |
| `POTATO_EVAL_SUITE` | Experiment name label. |
| `POTATO_EVAL_EXPERIMENT` | Default dataset for `--potato-experiment`. |

Recorded experiments are plain files — upload them as a CI artifact to track
scores across runs, or point them at the same store your Potato server reads.

## GitHub Actions

A ready-to-copy workflow is in
`examples/agent-traces/ci-eval/ci_workflow_example.yml` — it runs the suite on
every PR, gates on thresholds, and uploads the experiment records as an artifact.

## Example

```bash
pytest examples/agent-traces/ci-eval/test_agent_eval.py \
  -p potato.testing.pytest_plugin \
  --potato-threshold correct=0.8 --potato-experiment demo-suite
```

## Related

- [Programmatic Evaluators](evaluators.md)
- [Datasets & Experiments](datasets_and_experiments.md)
- [Automation Rules](automation_rules.md)
