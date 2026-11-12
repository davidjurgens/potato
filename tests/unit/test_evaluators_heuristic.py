"""Unit tests for heuristic evaluators and the registry."""

import pytest

from potato.evaluators import (
    ExactMatch,
    Contains,
    RegexMatch,
    EditDistance,
    JSONValid,
    JSONSchemaMatch,
    EmbeddingDistance,
    build_evaluator,
    get_supported_evaluators,
    list_evaluators,
)


def test_exact_match():
    assert ExactMatch().evaluate(outputs="hi", reference_outputs="hi").score == 1.0
    assert ExactMatch().evaluate(outputs="hi ", reference_outputs="hi").score == 1.0  # strip
    assert ExactMatch(case_sensitive=False).evaluate(outputs="HI", reference_outputs="hi").score == 1.0
    assert ExactMatch().evaluate(outputs="HI", reference_outputs="hi").score == 0.0


def test_contains_substring_and_reference():
    assert Contains(substring="cat").evaluate(outputs="the cat sat").score == 1.0
    assert Contains().evaluate(outputs="the cat sat", reference_outputs="CAT").score == 1.0
    assert Contains(substring="dog").evaluate(outputs="the cat sat").score == 0.0


def test_regex_match():
    assert RegexMatch(r"\d{3}").evaluate(outputs="abc123").score == 1.0
    assert RegexMatch(r"^\d+$").evaluate(outputs="abc").score == 0.0


def test_edit_distance_identical_and_different():
    assert EditDistance().evaluate(outputs="kitten", reference_outputs="kitten").score == 1.0
    r = EditDistance().evaluate(outputs="kitten", reference_outputs="sitting")
    assert r.value == 3  # classic levenshtein distance
    assert 0.0 < r.score < 1.0


def test_output_dict_extraction():
    # _as_text pulls a known key out of dict outputs
    assert ExactMatch().evaluate(outputs={"output": "hi"}, reference_outputs="hi").score == 1.0


def test_json_valid():
    assert JSONValid().evaluate(outputs='{"a": 1}').score == 1.0
    assert JSONValid().evaluate(outputs="not json").score == 0.0


def test_json_schema_match():
    pytest.importorskip("jsonschema")
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
    assert JSONSchemaMatch(schema).evaluate(outputs='{"a": 1}').score == 1.0
    assert JSONSchemaMatch(schema).evaluate(outputs='{"a": "x"}').score == 0.0
    assert JSONSchemaMatch(schema).evaluate(outputs="{}").score == 0.0


def test_embedding_distance_with_injected_fn():
    # Inject a trivial embed fn so the test is hermetic (no ML import).
    vocab = {"cat": [1.0, 0.0], "dog": [0.0, 1.0], "feline": [0.9, 0.1]}
    embed = lambda s: vocab.get(s.strip(), [0.0, 0.0])
    ev = EmbeddingDistance(embed_fn=embed)
    same = ev.evaluate(outputs="cat", reference_outputs="cat").score
    close = ev.evaluate(outputs="cat", reference_outputs="feline").score
    far = ev.evaluate(outputs="cat", reference_outputs="dog").score
    assert same == pytest.approx(1.0)
    assert close > far


def test_registry_build_and_list():
    assert "trajectory_match" in get_supported_evaluators()
    assert any(e["name"] == "exact_match" for e in list_evaluators())
    ev = build_evaluator("contains", {"substring": "x"})
    assert ev.evaluate(outputs="xyz").score == 1.0


def test_registry_unknown_raises():
    with pytest.raises(KeyError):
        build_evaluator("does_not_exist")
