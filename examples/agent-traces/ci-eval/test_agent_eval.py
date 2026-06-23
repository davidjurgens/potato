"""
Example: evaluate an agent in pytest and gate CI on score thresholds.

Run (from repo root; ``-p`` loads the plugin without installing Potato):

    pytest examples/agent-traces/ci-eval/test_agent_eval.py \
        -p potato.testing.pytest_plugin \
        --potato-threshold correct=0.8 --potato-experiment demo-suite

If you `pip install -e .`, the plugin auto-loads and ``-p`` isn't needed.
"""

import pytest

from potato.testing import expect


# A toy "agent" under evaluation — replace with your real one.
def my_agent(question: str) -> str:
    answers = {"2+2": "4", "capital of France": "Paris", "color of sky": "blue"}
    return answers.get(question, "I don't know")


CASES = [
    {"q": "2+2", "expected": "4"},
    {"q": "capital of France", "expected": "Paris"},
    {"q": "color of sky", "expected": "blue"},
]


@pytest.mark.potato_eval
@pytest.mark.parametrize("case", CASES, ids=[c["q"] for c in CASES])
def test_agent_answers(case, potato_eval):
    out = my_agent(case["q"])
    potato_eval.log_inputs({"question": case["q"]})
    potato_eval.log_outputs(out)
    potato_eval.log_reference_outputs(case["expected"])

    correct = 1.0 if out == case["expected"] else 0.0
    potato_eval.log_feedback("correct", correct)
    # Fuzzy similarity to the reference as a second metric.
    potato_eval.log_feedback(
        "similarity", 1.0 - expect.edit_distance(out, case["expected"]).value)

    # Per-case hard assertion (fails this case if the answer is empty).
    expect(out).to_contain("") if out else pytest.fail("empty answer")
