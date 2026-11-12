"""
Potato testing helpers — run evaluations inside pytest and gate CI on thresholds.

    from potato.testing import expect

    @pytest.mark.potato_eval
    def test_x(potato_eval):
        potato_eval.log_feedback("correct", 1.0)
        expect(out).to_contain("answer")

The pytest plugin (markers, the ``potato_eval`` fixture, ``--potato-threshold`` /
``--potato-experiment`` options, summary + gating) is registered via the
``pytest11`` entry point in setup.py. See ``docs/agent-evaluation/ci_evaluation.md``.
"""

from potato.testing.expectations import expect, Matcher, normalized_edit_distance

__all__ = ["expect", "Matcher", "normalized_edit_distance"]
