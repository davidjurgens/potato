"""Tests for annotation strategies."""

from unittest.mock import MagicMock

import pytest
from potato.simulator.annotation_strategies import (
    LLMStrategy,
    RandomStrategy,
    BiasedStrategy,
    GoldStandardStrategy,
    _LLMResponse,
    create_strategy,
)
from potato.simulator.competence_profiles import (
    PerfectCompetence,
    RandomCompetence,
    AdversarialCompetence,
)
from potato.simulator.config import (
    BiasedStrategyConfig,
    LLMStrategyConfig,
    AnnotationStrategyType,
)


class TestRandomStrategy:
    """Tests for RandomStrategy."""

    @pytest.fixture
    def strategy(self):
        return RandomStrategy()

    @pytest.fixture
    def radio_schema(self):
        return {
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral"],
        }

    @pytest.fixture
    def multiselect_schema(self):
        return {
            "name": "topics",
            "annotation_type": "multiselect",
            "labels": ["politics", "sports", "technology"],
        }

    @pytest.fixture
    def likert_schema(self):
        return {
            "name": "rating",
            "annotation_type": "likert",
            "size": 5,
        }

    @pytest.fixture
    def instance(self):
        return {
            "instance_id": "test_001",
            "text": "This is a test instance with some text content.",
        }

    def test_radio_annotation(self, strategy, radio_schema, instance):
        """Should generate valid radio annotation."""
        competence = RandomCompetence()
        result = strategy.generate_annotation(instance, radio_schema, competence)

        # New format: {"schema:label": "on"}
        assert len(result) == 1
        key = list(result.keys())[0]
        assert key.startswith("sentiment:")
        assert result[key] == "on"
        label = key.split(":")[1]
        assert label in ["positive", "negative", "neutral"]

    def test_multiselect_annotation(self, strategy, multiselect_schema, instance):
        """Should generate valid multiselect annotation."""
        competence = RandomCompetence()
        result = strategy.generate_annotation(instance, multiselect_schema, competence)

        # Should have at least one selection
        assert len(result) >= 1
        for key in result:
            assert key.startswith("topics:")
            assert result[key] == "on"

    def test_likert_annotation(self, strategy, likert_schema, instance):
        """Should generate valid likert annotation."""
        competence = RandomCompetence()
        result = strategy.generate_annotation(instance, likert_schema, competence)

        # New format: {"schema:value": "on"}
        assert len(result) == 1
        key = list(result.keys())[0]
        assert key.startswith("rating:")
        assert result[key] == "on"
        value = int(key.split(":")[1])
        assert value >= 1
        assert value <= 5

    def test_uses_gold_answer_when_correct(self, strategy, radio_schema, instance):
        """Should use gold answer when competence says be correct."""
        competence = PerfectCompetence()
        gold_answer = {"sentiment": "positive"}
        result = strategy.generate_annotation(
            instance, radio_schema, competence, gold_answer
        )

        # New format: {"schema:label": "on"}
        assert "sentiment:positive" in result
        assert result["sentiment:positive"] == "on"

    def test_avoids_gold_answer_when_adversarial(
        self, strategy, radio_schema, instance
    ):
        """Should avoid gold answer when adversarial."""
        competence = AdversarialCompetence()
        gold_answer = {"sentiment": "positive"}

        # Run many times to ensure it never selects positive
        for _ in range(50):
            result = strategy.generate_annotation(
                instance, radio_schema, competence, gold_answer
            )
            # New format: should not have sentiment:positive
            assert "sentiment:positive" not in result

    def test_extract_labels_dict_format(self, strategy):
        """Should extract labels from dict format."""
        schema = {
            "labels": [
                {"name": "positive", "tooltip": "Positive sentiment"},
                {"name": "negative", "tooltip": "Negative sentiment"},
            ]
        }
        labels = strategy._extract_labels(schema)
        assert labels == ["positive", "negative"]

    def test_extract_labels_list_format(self, strategy):
        """Should extract labels from list format."""
        schema = {"labels": ["positive", "negative", "neutral"]}
        labels = strategy._extract_labels(schema)
        assert labels == ["positive", "negative", "neutral"]


class TestBiasedStrategy:
    """Tests for BiasedStrategy."""

    @pytest.fixture
    def biased_config(self):
        return BiasedStrategyConfig(
            label_weights={"positive": 0.8, "negative": 0.1, "neutral": 0.1}
        )

    @pytest.fixture
    def strategy(self, biased_config):
        return BiasedStrategy(biased_config)

    @pytest.fixture
    def radio_schema(self):
        return {
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral"],
        }

    @pytest.fixture
    def instance(self):
        return {"instance_id": "test_001", "text": "Test text"}

    def test_biased_selection(self, strategy, radio_schema, instance):
        """Should select biased towards weighted labels."""
        competence = RandomCompetence()

        # Run many times and count selections
        selections = {}
        for _ in range(1000):
            result = strategy.generate_annotation(instance, radio_schema, competence)
            # New format: {"sentiment:label": "on"}
            key = list(result.keys())[0]
            label = key.split(":")[1]
            selections[label] = selections.get(label, 0) + 1

        # Positive should be most common (80% weight)
        assert selections["positive"] > selections["negative"]
        assert selections["positive"] > selections["neutral"]


class TestGoldStandardStrategy:
    """Tests for GoldStandardStrategy."""

    @pytest.fixture
    def strategy(self):
        return GoldStandardStrategy()

    @pytest.fixture
    def schema(self):
        return {
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral"],
        }

    @pytest.fixture
    def instance(self):
        return {"instance_id": "test_001", "text": "Test text"}

    def test_uses_gold_when_correct(self, strategy, schema, instance):
        """Should use gold answer when competence is correct."""
        competence = PerfectCompetence()
        gold_answer = {"sentiment": "positive"}

        result = strategy.generate_annotation(instance, schema, competence, gold_answer)
        # New format: {"schema:label": "on"}
        assert "sentiment:positive" in result
        assert result["sentiment:positive"] == "on"

    def test_avoids_gold_when_wrong(self, strategy, schema, instance):
        """Should avoid gold answer when competence is wrong."""
        competence = AdversarialCompetence()
        gold_answer = {"sentiment": "positive"}

        for _ in range(50):
            result = strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )
            # New format: should not have sentiment:positive
            assert "sentiment:positive" not in result

    def test_falls_back_to_random_without_gold(self, strategy, schema, instance):
        """Should use random when no gold standard available."""
        competence = PerfectCompetence()

        result = strategy.generate_annotation(instance, schema, competence, None)
        # New format: {"schema:label": "on"}
        assert len(result) == 1
        key = list(result.keys())[0]
        assert key.startswith("sentiment:")
        label = key.split(":")[1]
        assert label in ["positive", "negative", "neutral"]


class TestCreateStrategy:
    """Tests for strategy factory function."""

    def test_create_random(self):
        """Should create RandomStrategy."""
        strategy = create_strategy(AnnotationStrategyType.RANDOM)
        assert isinstance(strategy, RandomStrategy)

    def test_create_biased_with_config(self):
        """Should create BiasedStrategy with config."""
        config = BiasedStrategyConfig(label_weights={"a": 0.5, "b": 0.5})
        strategy = create_strategy(AnnotationStrategyType.BIASED, biased_config=config)
        assert isinstance(strategy, BiasedStrategy)

    def test_create_biased_without_config(self):
        """Should fall back to RandomStrategy without config."""
        strategy = create_strategy(AnnotationStrategyType.BIASED)
        assert isinstance(strategy, RandomStrategy)

    def test_create_gold_standard(self):
        """Should create GoldStandardStrategy."""
        strategy = create_strategy(AnnotationStrategyType.GOLD_STANDARD)
        assert isinstance(strategy, GoldStandardStrategy)


def _make_llm_strategy_with_endpoint(endpoint):
    """Build an LLMStrategy whose endpoint is a pre-built mock.

    Skips the real `_create_endpoint` so tests don't need Ollama / network.
    """
    cfg = LLMStrategyConfig(endpoint_type="ollama", model="llama3.2")
    strat = LLMStrategy.__new__(LLMStrategy)
    strat.config = cfg
    strat.endpoint = endpoint
    strat.random_strategy = RandomStrategy()
    return strat


class TestLLMStrategyEndpointInteraction:
    """Verify LLMStrategy passes a Pydantic schema to query() so structured
    endpoints (Ollama, OllamaVision, OpenAI) don't crash on
    ``output_format.model_json_schema()`` -- and produces wire-format
    annotations the server actually accepts.
    """

    @pytest.fixture
    def radio_schema(self):
        return {
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral"],
        }

    @pytest.fixture
    def likert_schema(self):
        return {"name": "rating", "annotation_type": "likert", "size": 5}

    @pytest.fixture
    def text_schema(self):
        return {"name": "notes", "annotation_type": "text"}

    def test_query_called_with_pydantic_schema_not_none(self, radio_schema):
        endpoint = MagicMock()
        endpoint.query.return_value = _LLMResponse(label="positive")
        strat = _make_llm_strategy_with_endpoint(endpoint)

        out = strat.generate_annotation(
            {"text": "I loved it"}, radio_schema, PerfectCompetence(), None
        )
        # Critical: the second positional arg must be the Pydantic class,
        # not None. Endpoints call `output_format.model_json_schema()`.
        endpoint.query.assert_called_once()
        args, _ = endpoint.query.call_args
        assert len(args) >= 2
        assert args[1] is _LLMResponse
        assert hasattr(args[1], "model_json_schema")

        # And the wire format must be the server-accepted "schema:label": "on"
        assert out == {"sentiment:positive": "on"}

    def test_falls_back_to_single_arg_query_on_TypeError(self, radio_schema):
        """AnthropicEndpoint's query(prompt) takes only one positional arg.

        Calling query(prompt, _LLMResponse) raises TypeError; the strategy
        must catch it and retry with query(prompt) alone.
        """
        endpoint = MagicMock()

        def query_side_effect(*args, **kwargs):
            if len(args) == 2:
                raise TypeError(
                    "query() takes 2 positional arguments but 3 were given"
                )
            return "negative"

        endpoint.query.side_effect = query_side_effect
        strat = _make_llm_strategy_with_endpoint(endpoint)

        out = strat.generate_annotation(
            {"text": "boring"}, radio_schema, PerfectCompetence(), None
        )
        assert endpoint.query.call_count == 2
        assert out == {"sentiment:negative": "on"}

    def test_endpoint_exception_falls_back_to_random(self, radio_schema):
        endpoint = MagicMock()
        endpoint.query.side_effect = RuntimeError("model unavailable")
        strat = _make_llm_strategy_with_endpoint(endpoint)
        out = strat.generate_annotation(
            {"text": "x"}, radio_schema, PerfectCompetence(), None
        )
        # Random fallback always returns *some* annotation
        assert out
        assert any(k.startswith("sentiment:") for k in out)

    def test_radio_emits_server_wire_format(self, radio_schema):
        endpoint = MagicMock()
        endpoint.query.return_value = {"label": "neutral"}
        strat = _make_llm_strategy_with_endpoint(endpoint)
        out = strat.generate_annotation(
            {"text": "ok"}, radio_schema, PerfectCompetence(), None
        )
        # Old buggy code returned {"sentiment": "neutral"} (no colon, no "on")
        assert out == {"sentiment:neutral": "on"}

    def test_likert_emits_server_wire_format(self, likert_schema):
        endpoint = MagicMock()
        endpoint.query.return_value = _LLMResponse(label="4")
        strat = _make_llm_strategy_with_endpoint(endpoint)
        out = strat.generate_annotation(
            {"text": "great"}, likert_schema, PerfectCompetence(), None
        )
        # Old buggy code returned {"rating": "4"} (no colon, no "on")
        assert out == {"rating:4": "on"}

    def test_text_emits_server_wire_format(self, text_schema):
        endpoint = MagicMock()
        endpoint.query.return_value = _LLMResponse(label="some annotator note")
        strat = _make_llm_strategy_with_endpoint(endpoint)
        out = strat.generate_annotation(
            {"text": "x"}, text_schema, PerfectCompetence(), None
        )
        # Old buggy code returned {"notes": "..."}; server expects schema:text
        assert out == {"notes:text": "some annotator note"}

    def test_pydantic_response_label_is_unwrapped(self, radio_schema):
        endpoint = MagicMock()
        endpoint.query.return_value = _LLMResponse(label="positive")
        strat = _make_llm_strategy_with_endpoint(endpoint)
        out = strat.generate_annotation(
            {"text": "great"}, radio_schema, PerfectCompetence(), None
        )
        assert out == {"sentiment:positive": "on"}

    def test_dict_response_with_response_key_unwrapped(self, radio_schema):
        # OllamaEndpoint's parseStringToJson fallback returns
        # ``{"response": "..."}`` for unstructured replies.
        endpoint = MagicMock()
        endpoint.query.return_value = {"response": "negative please"}
        strat = _make_llm_strategy_with_endpoint(endpoint)
        out = strat.generate_annotation(
            {"text": "x"}, radio_schema, PerfectCompetence(), None
        )
        assert out == {"sentiment:negative": "on"}
