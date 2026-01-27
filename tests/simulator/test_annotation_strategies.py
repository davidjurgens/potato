"""Tests for annotation strategies."""

import pytest
from potato.simulator.annotation_strategies import (
    RandomStrategy,
    BiasedStrategy,
    GoldStandardStrategy,
    create_strategy,
)
from potato.simulator.competence_profiles import (
    PerfectCompetence,
    RandomCompetence,
    AdversarialCompetence,
)
from potato.simulator.config import (
    BiasedStrategyConfig,
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
