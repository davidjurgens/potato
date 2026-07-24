"""Tests for the Potato pytest plugin: expectations, collector, gating, and an
end-to-end pytester run."""

import pytest

from potato.testing import expect, normalized_edit_distance
from potato.testing.pytest_plugin import (
    EvalCollector,
    _parse_thresholds,
    compute_violations,
)

# Enable the pytester fixture for the end-to-end test below.
pytest_plugins = ["pytester"]


# ---- expectations ----

def test_expect_pass_and_fail():
    expect("the answer is 4").to_contain("4")
    expect(0.9).to_be_greater_than(0.8)
    expect(0.2).to_be_less_than(0.5)
    expect(0.5).to_be_between(0.0, 1.0)
    with pytest.raises(AssertionError):
        expect("foo").to_contain("bar")
    with pytest.raises(AssertionError):
        expect(0.3).to_be_greater_than(0.8)


def test_edit_distance_metric():
    assert normalized_edit_distance("kitten", "kitten") == 0.0
    expect.edit_distance("kitten", "kitten").to_be_less_than(0.01)
    assert normalized_edit_distance("kitten", "sitting") > 0.0
    with pytest.raises(AssertionError):
        expect.edit_distance("abc", "xyz").to_be_less_than(0.1)


def test_embedding_distance_injected():
    vocab = {"cat": [1.0, 0.0], "feline": [0.9, 0.1], "dog": [0.0, 1.0]}
    embed = lambda s: vocab.get(s.strip(), [0.0, 0.0])
    near = expect.embedding_distance("cat", "feline", embed_fn=embed).value
    far = expect.embedding_distance("cat", "dog", embed_fn=embed).value
    assert near < far


# ---- collector + gating ----

def test_collector_aggregates_means():
    c = EvalCollector()
    c.case("t1").log_feedback("correct", 1.0)
    c.case("t2").log_feedback("correct", 0.0)
    c.case("t3").log_feedback("correct", 1.0)
    agg = c.aggregate()
    assert agg["correct"] == pytest.approx(2 / 3)
    assert c.has_data()


def test_parse_thresholds():
    assert _parse_thresholds(["correct=0.8", "bad", "f1=0.5"]) == {"correct": 0.8, "f1": 0.5}


def test_compute_violations():
    agg = {"correct": 0.6}
    assert compute_violations(agg, {"correct": 0.8}) == [("correct", 0.6, 0.8)]
    assert compute_violations(agg, {"correct": 0.5}) == []
    # missing key is a violation
    assert compute_violations(agg, {"missing": 0.5}) == [("missing", None, 0.5)]


# ---- end-to-end via pytester ----

def test_plugin_gates_build_on_threshold(pytester):
    pytester.makepyfile("""
        import pytest
        @pytest.mark.potato_eval
        def test_low(potato_eval):
            potato_eval.log_outputs("3")
            potato_eval.log_feedback("correct", 0.0)  # wrong
    """)
    # Test itself passes, but the threshold gate should fail the run.
    # The plugin auto-loads via its pytest11 entry point (name "potato_eval"),
    # so passing "-p potato.testing.pytest_plugin" would register the same
    # module under a second name and raise a pluggy ValueError. Rely on the
    # entry point instead.
    result = pytester.runpytest("--potato-threshold", "correct=0.8")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*THRESHOLD FAILED: correct*"])


def test_plugin_passes_when_threshold_met(pytester):
    pytester.makepyfile("""
        import pytest
        @pytest.mark.potato_eval
        def test_ok(potato_eval):
            potato_eval.log_feedback("correct", 1.0)
    """)
    result = pytester.runpytest("--potato-threshold", "correct=0.8")
    assert result.ret == 0
