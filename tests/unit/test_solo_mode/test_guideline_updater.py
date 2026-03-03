"""
Tests for the guideline updater (prompt injection and re-annotation scoping).
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from potato.solo_mode.guideline_updater import GuidelineUpdater
from potato.solo_mode.edge_case_rules import EdgeCaseCategory


def _make_mock_solo_config(
    reannotation_confidence_threshold: float = 0.60,
    max_reannotations: int = 2,
):
    config = MagicMock()
    config.edge_case_rules.reannotation_confidence_threshold = reannotation_confidence_threshold
    config.edge_case_rules.max_reannotations_per_instance = max_reannotations
    config.revision_models = []
    config.labeling_models = []
    return config


class TestDirectInjection:
    """Tests for direct prompt injection (no LLM)."""

    def test_inject_appends_section(self):
        updater = GuidelineUpdater({}, _make_mock_solo_config())

        categories = [
            EdgeCaseCategory(
                id="c1",
                summary_rule="When sarcasm is present -> label as negative",
            ),
            EdgeCaseCategory(
                id="c2",
                summary_rule="When text is ambiguous -> choose neutral",
            ),
        ]

        result = updater.inject_rules_into_prompt(
            "Label the text as positive, negative, or neutral.",
            categories,
        )

        assert "Edge Case Guidelines" in result
        assert "sarcasm" in result
        assert "ambiguous" in result
        # Original prompt preserved
        assert "Label the text as positive" in result

    def test_inject_before_response_format(self):
        updater = GuidelineUpdater({}, _make_mock_solo_config())

        categories = [
            EdgeCaseCategory(id="c1", summary_rule="Rule 1"),
        ]

        prompt = "Instructions here.\n\nRespond with JSON:\n{\"label\": \"...\"}"
        result = updater.inject_rules_into_prompt(prompt, categories)

        # Edge case section should appear before "Respond with JSON"
        ecg_idx = result.index("Edge Case Guidelines")
        json_idx = result.index("Respond with JSON")
        assert ecg_idx < json_idx

    def test_inject_empty_categories(self):
        updater = GuidelineUpdater({}, _make_mock_solo_config())
        result = updater.inject_rules_into_prompt("Original prompt", [])
        assert result == "Original prompt"

    def test_inject_with_mock_endpoint(self):
        updater = GuidelineUpdater({}, _make_mock_solo_config())

        mock_endpoint = MagicMock()
        mock_endpoint.query.return_value = '{"updated_prompt": "Enhanced prompt with rules"}'
        updater._endpoint = mock_endpoint

        categories = [
            EdgeCaseCategory(id="c1", summary_rule="Rule 1"),
        ]
        result = updater.inject_rules_into_prompt("Original", categories)
        assert result == "Enhanced prompt with rules"


class TestReannotationScoping:
    """Tests for identifying instances for re-annotation."""

    def _make_prediction(self, confidence=0.5, prompt_version=1):
        """Create a mock prediction object."""
        pred = MagicMock()
        pred.confidence_score = confidence
        pred.prompt_version = prompt_version
        return pred

    def test_finds_low_confidence_instances(self):
        updater = GuidelineUpdater({}, _make_mock_solo_config(
            reannotation_confidence_threshold=0.60,
        ))

        predictions = {
            'inst_1': {'schema': self._make_prediction(confidence=0.3, prompt_version=1)},
            'inst_2': {'schema': self._make_prediction(confidence=0.5, prompt_version=1)},
            'inst_3': {'schema': self._make_prediction(confidence=0.8, prompt_version=1)},
        }

        result = updater.get_instances_for_reannotation(
            predictions, old_prompt_version=1,
        )

        # inst_1 (0.3) and inst_2 (0.5) are below 0.60 threshold
        assert 'inst_1' in result
        assert 'inst_2' in result
        assert 'inst_3' not in result

    def test_only_old_version(self):
        updater = GuidelineUpdater({}, _make_mock_solo_config())

        predictions = {
            'inst_1': {'schema': self._make_prediction(confidence=0.3, prompt_version=1)},
            'inst_2': {'schema': self._make_prediction(confidence=0.3, prompt_version=2)},
        }

        result = updater.get_instances_for_reannotation(
            predictions, old_prompt_version=1,
        )

        # Only inst_1 was labeled with old version
        assert 'inst_1' in result
        assert 'inst_2' not in result

    def test_respects_max_reannotations(self):
        updater = GuidelineUpdater({}, _make_mock_solo_config(
            max_reannotations=2,
        ))

        predictions = {
            'inst_1': {'schema': self._make_prediction(confidence=0.3, prompt_version=1)},
            'inst_2': {'schema': self._make_prediction(confidence=0.3, prompt_version=1)},
        }

        counts = {'inst_1': 2}  # Already re-annotated twice

        result = updater.get_instances_for_reannotation(
            predictions, old_prompt_version=1,
            reannotation_counts=counts,
        )

        # inst_1 is at max, inst_2 hasn't been re-annotated
        assert 'inst_1' not in result
        assert 'inst_2' in result

    def test_empty_predictions(self):
        updater = GuidelineUpdater({}, _make_mock_solo_config())
        result = updater.get_instances_for_reannotation({}, old_prompt_version=1)
        assert result == []

    def test_dict_predictions(self):
        """Test with dict-style predictions (from deserialized state)."""
        updater = GuidelineUpdater({}, _make_mock_solo_config(
            reannotation_confidence_threshold=0.60,
        ))

        predictions = {
            'inst_1': {'schema': {
                'confidence_score': 0.3,
                'prompt_version': 1,
            }},
            'inst_2': {'schema': {
                'confidence_score': 0.8,
                'prompt_version': 1,
            }},
        }

        result = updater.get_instances_for_reannotation(
            predictions, old_prompt_version=1,
        )

        assert 'inst_1' in result
        assert 'inst_2' not in result
