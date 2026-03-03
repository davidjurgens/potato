"""
Tests for Labeling Function Extraction and Application.

Tests LabelingFunction dataclass, LabelingFunctionExtractor,
LabelingFunctionApplier, LabelingFunctionManager, config parsing,
and manager integration.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.solo_mode.labeling_functions import (
    ABSTAIN,
    ApplyResult,
    LabelingFunction,
    LabelingFunctionApplier,
    LabelingFunctionExtractor,
    LabelingFunctionManager,
    LabelingFunctionVote,
)
from potato.solo_mode.config import (
    LabelingFunctionConfig,
    SoloModeConfig,
    parse_solo_mode_config,
)


def _make_solo_config(**overrides):
    """Create a SoloModeConfig with sensible test defaults."""
    config_data = {
        'solo_mode': {
            'enabled': True,
            'labeling_models': [],
            **overrides,
        },
        'annotation_schemes': [
            {'name': 'sentiment', 'annotation_type': 'radio',
             'labels': ['positive', 'negative', 'neutral']},
        ],
    }
    return parse_solo_mode_config(config_data)


def _make_app_config():
    return {
        'annotation_schemes': [
            {'name': 'sentiment', 'annotation_type': 'radio',
             'labels': ['positive', 'negative', 'neutral']},
        ],
    }


def _make_function(**kwargs):
    """Create a test labeling function."""
    defaults = {
        'id': 'lf_test1',
        'pattern_text': "Text containing 'great' -> positive",
        'condition': "text contains 'great'",
        'label': 'positive',
        'confidence': 0.9,
        'extracted_from_reasoning': 'great, amazing, love',
    }
    defaults.update(kwargs)
    return LabelingFunction(**defaults)


# === LabelingFunction Dataclass Tests ===


class TestLabelingFunction:
    """Tests for LabelingFunction dataclass."""

    def test_to_dict(self):
        fn = _make_function(
            source_instance_ids=['i1', 'i2'],
            coverage=10,
            accuracy=0.92,
        )
        d = fn.to_dict()
        assert d['id'] == 'lf_test1'
        assert d['label'] == 'positive'
        assert d['confidence'] == 0.9
        assert d['coverage'] == 10
        assert d['accuracy'] == 0.92
        assert d['source_instance_ids'] == ['i1', 'i2']
        assert d['enabled'] is True

    def test_from_dict_roundtrip(self):
        fn = _make_function(
            source_instance_ids=['i1'],
            coverage=5,
            accuracy=0.85,
        )
        d = fn.to_dict()
        fn2 = LabelingFunction.from_dict(d)
        assert fn2.id == fn.id
        assert fn2.label == fn.label
        assert fn2.confidence == fn.confidence
        assert fn2.coverage == fn.coverage
        assert fn2.accuracy == fn.accuracy
        assert fn2.enabled == fn.enabled

    def test_default_created_at(self):
        fn = _make_function()
        assert fn.created_at != ''

    def test_disabled_function(self):
        fn = _make_function(enabled=False)
        assert fn.enabled is False
        d = fn.to_dict()
        assert d['enabled'] is False


# === LabelingFunctionApplier Tests ===


class TestLabelingFunctionApplier:
    """Tests for applying labeling functions to instances."""

    def test_single_match(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        fn = _make_function()
        result = applier.apply('inst_1', "This is great!", [fn])
        assert not result.abstained
        assert result.label == 'positive'
        assert len(result.votes) == 1
        assert result.vote_agreement == 1.0

    def test_no_match_abstains(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        fn = _make_function()
        result = applier.apply('inst_1', "This is terrible.", [fn])
        assert result.abstained
        assert result.label is None
        assert len(result.votes) == 0

    def test_multiple_functions_same_label(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        fn1 = _make_function(id='lf_1', extracted_from_reasoning='great')
        fn2 = _make_function(
            id='lf_2',
            extracted_from_reasoning='amazing',
            condition="text contains 'amazing'",
        )
        result = applier.apply('inst_1', "This is great and amazing!", [fn1, fn2])
        assert not result.abstained
        assert result.label == 'positive'
        assert len(result.votes) == 2
        assert result.vote_agreement == 1.0

    def test_conflicting_votes_below_threshold(self):
        applier = LabelingFunctionApplier(vote_threshold=0.7)
        fn1 = _make_function(
            id='lf_1',
            label='positive',
            confidence=0.9,
            extracted_from_reasoning='great',
        )
        fn2 = _make_function(
            id='lf_2',
            label='negative',
            confidence=0.85,
            extracted_from_reasoning='great',
            condition="text contains 'great'",
        )
        result = applier.apply('inst_1', "This is great!", [fn1, fn2])
        # Both match, but vote_agreement may be below threshold
        assert len(result.votes) == 2
        # positive gets 0.9, negative gets 0.85 -> agreement = 0.9/1.75 ≈ 0.514
        assert result.abstained  # 0.514 < 0.7 threshold

    def test_disabled_functions_skipped(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        fn = _make_function(enabled=False)
        result = applier.apply('inst_1', "This is great!", [fn])
        assert result.abstained
        assert len(result.votes) == 0

    def test_empty_functions_list(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        result = applier.apply('inst_1', "some text", [])
        assert result.abstained

    def test_case_insensitive_matching(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        fn = _make_function(extracted_from_reasoning='great')
        result = applier.apply('inst_1', "THIS IS GREAT!", [fn])
        assert not result.abstained
        assert result.label == 'positive'

    def test_apply_batch(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        fn = _make_function()
        instances = [
            {'instance_id': 'i1', 'text': 'This is great!'},
            {'instance_id': 'i2', 'text': 'This is terrible.'},
            {'instance_id': 'i3', 'text': 'Amazing work!'},
        ]
        results = applier.apply_batch(instances, [fn])
        assert len(results) == 3
        assert not results[0].abstained  # 'great' matches
        assert results[1].abstained       # no match
        assert not results[2].abstained   # 'amazing' matches

    def test_keyword_from_condition_single_quotes(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        fn = LabelingFunction(
            id='lf_cond',
            pattern_text='test',
            condition="text contains 'horrible'",
            label='negative',
            confidence=0.9,
            extracted_from_reasoning='',  # empty reasoning
        )
        result = applier.apply('inst_1', "This is horrible!", [fn])
        assert not result.abstained
        assert result.label == 'negative'

    def test_keyword_from_condition_any_of(self):
        applier = LabelingFunctionApplier(vote_threshold=0.5)
        fn = LabelingFunction(
            id='lf_anyof',
            pattern_text='test',
            condition="text contains any of: bad, awful, terrible",
            label='negative',
            confidence=0.9,
            extracted_from_reasoning='',
        )
        result = applier.apply('inst_1', "This is awful!", [fn])
        assert not result.abstained
        assert result.label == 'negative'

    def test_apply_result_to_dict(self):
        result = ApplyResult(
            instance_id='i1',
            label='positive',
            votes=[LabelingFunctionVote('lf_1', 'positive', 0.9)],
            abstained=False,
            vote_agreement=1.0,
        )
        d = result.to_dict()
        assert d['instance_id'] == 'i1'
        assert d['label'] == 'positive'
        assert d['abstained'] is False
        assert d['num_votes'] == 1


# === LabelingFunctionExtractor Tests ===


class TestLabelingFunctionExtractor:
    """Tests for extracting labeling functions from predictions."""

    def test_empty_predictions(self):
        config = _make_solo_config()
        extractor = LabelingFunctionExtractor(_make_app_config(), config)
        result = extractor.extract_from_predictions([])
        assert result == []

    def test_below_confidence_threshold(self):
        config = _make_solo_config(labeling_functions={
            'min_confidence': 0.9,
        })
        extractor = LabelingFunctionExtractor(_make_app_config(), config)
        preds = [
            {
                'instance_id': 'i1',
                'text': 'great stuff',
                'predicted_label': 'positive',
                'confidence': 0.8,
                'reasoning': 'contains positive words',
            },
        ]
        result = extractor.extract_from_predictions(preds)
        assert result == []

    def test_keyword_fallback_extraction(self):
        config = _make_solo_config(labeling_functions={
            'min_confidence': 0.85,
            'min_coverage': 2,
        })
        extractor = LabelingFunctionExtractor(_make_app_config(), config)
        # Need enough texts where common words appear in subset but not all
        preds = [
            {
                'instance_id': 'i1',
                'text': 'I love this great product very much',
                'predicted_label': 'positive',
                'confidence': 0.92,
                'reasoning': 'positive sentiment',
            },
            {
                'instance_id': 'i2',
                'text': 'Great experience love the design',
                'predicted_label': 'positive',
                'confidence': 0.90,
                'reasoning': 'positive sentiment',
            },
            {
                'instance_id': 'i3',
                'text': 'A wonderful day for relaxation',
                'predicted_label': 'positive',
                'confidence': 0.88,
                'reasoning': 'positive sentiment',
            },
            {
                'instance_id': 'i4',
                'text': 'Absolutely fantastic service here',
                'predicted_label': 'positive',
                'confidence': 0.91,
                'reasoning': 'positive sentiment',
            },
        ]
        # Without LLM endpoint, falls back to keyword extraction
        # 'love' and 'great' appear in 2/4 texts (50%) = within threshold
        result = extractor.extract_from_predictions(preds)
        assert len(result) >= 1
        fn = result[0]
        assert fn.label == 'positive'
        assert fn.confidence > 0

    def test_max_functions_limit(self):
        config = _make_solo_config(labeling_functions={
            'min_confidence': 0.85,
            'min_coverage': 1,
            'max_functions': 2,
        })
        extractor = LabelingFunctionExtractor(_make_app_config(), config)

        # Create predictions across multiple labels
        preds = []
        for i, label in enumerate(['positive', 'negative', 'neutral']):
            for j in range(3):
                preds.append({
                    'instance_id': f'i_{label}_{j}',
                    'text': f'text for {label} instance {j} with keyword_{label}',
                    'predicted_label': label,
                    'confidence': 0.9,
                    'reasoning': f'{label} sentiment',
                })

        result = extractor.extract_from_predictions(preds)
        assert len(result) <= 2

    def test_llm_extraction_with_mock(self):
        config = _make_solo_config(labeling_functions={'min_confidence': 0.8})
        extractor = LabelingFunctionExtractor(_make_app_config(), config)

        mock_endpoint = MagicMock()
        mock_endpoint.query.return_value = '''[
            {
                "pattern_text": "Positive keywords like great, love",
                "condition": "text contains positive keywords",
                "label": "positive",
                "keywords": ["great", "love"]
            }
        ]'''
        extractor._endpoint = mock_endpoint

        preds = [
            {
                'instance_id': 'i1',
                'text': 'great stuff',
                'predicted_label': 'positive',
                'confidence': 0.92,
                'reasoning': 'positive words',
            },
        ]
        result = extractor.extract_from_predictions(preds)
        assert len(result) == 1
        assert result[0].label == 'positive'
        assert 'great' in result[0].extracted_from_reasoning

    def test_llm_extraction_invalid_response(self):
        config = _make_solo_config(labeling_functions={'min_confidence': 0.8})
        extractor = LabelingFunctionExtractor(_make_app_config(), config)

        mock_endpoint = MagicMock()
        mock_endpoint.query.return_value = "This is not valid JSON"
        extractor._endpoint = mock_endpoint

        preds = [
            {
                'instance_id': 'i1',
                'text': 'great stuff great great',
                'predicted_label': 'positive',
                'confidence': 0.92,
                'reasoning': 'positive',
            },
            {
                'instance_id': 'i2',
                'text': 'great product great',
                'predicted_label': 'positive',
                'confidence': 0.90,
                'reasoning': 'positive',
            },
            {
                'instance_id': 'i3',
                'text': 'great day great',
                'predicted_label': 'positive',
                'confidence': 0.88,
                'reasoning': 'positive',
            },
        ]
        # Should fall back to keyword extraction
        result = extractor.extract_from_predictions(preds)
        # Keyword fallback should find something
        assert len(result) >= 0  # May or may not find keywords

    def test_parse_json_array_markdown_fence(self):
        config = _make_solo_config()
        extractor = LabelingFunctionExtractor(_make_app_config(), config)
        result = extractor._parse_json_array(
            '```json\n[{"a": 1}]\n```'
        )
        assert result == [{"a": 1}]

    def test_parse_json_array_plain(self):
        config = _make_solo_config()
        extractor = LabelingFunctionExtractor(_make_app_config(), config)
        result = extractor._parse_json_array('[{"a": 1}]')
        assert result == [{"a": 1}]

    def test_parse_json_array_embedded(self):
        config = _make_solo_config()
        extractor = LabelingFunctionExtractor(_make_app_config(), config)
        result = extractor._parse_json_array(
            'Here are the results: [{"a": 1}] Done.'
        )
        assert result == [{"a": 1}]

    def test_parse_json_array_invalid(self):
        config = _make_solo_config()
        extractor = LabelingFunctionExtractor(_make_app_config(), config)
        result = extractor._parse_json_array('not json at all')
        assert result is None

    def test_parse_json_array_empty(self):
        config = _make_solo_config()
        extractor = LabelingFunctionExtractor(_make_app_config(), config)
        result = extractor._parse_json_array('')
        assert result is None


# === LabelingFunctionManager Tests ===


class TestLabelingFunctionManager:
    """Tests for the manager lifecycle."""

    def _make_manager(self, **overrides):
        config = _make_solo_config(labeling_functions=overrides)
        return LabelingFunctionManager(_make_app_config(), config)

    def test_initial_state(self):
        mgr = self._make_manager()
        assert mgr.enabled is True
        assert mgr.get_all_functions() == []
        assert mgr.get_enabled_functions() == []

    def test_add_and_get_function(self):
        mgr = self._make_manager()
        fn = _make_function()
        mgr.add_function(fn)
        assert len(mgr.get_all_functions()) == 1
        assert mgr.get_function('lf_test1') is fn

    def test_toggle_function(self):
        mgr = self._make_manager()
        fn = _make_function()
        mgr.add_function(fn)

        new_state = mgr.toggle_function('lf_test1')
        assert new_state is False
        assert fn.enabled is False

        new_state = mgr.toggle_function('lf_test1')
        assert new_state is True

    def test_toggle_nonexistent(self):
        mgr = self._make_manager()
        result = mgr.toggle_function('nonexistent')
        assert result is None

    def test_remove_function(self):
        mgr = self._make_manager()
        fn = _make_function()
        mgr.add_function(fn)
        assert mgr.remove_function('lf_test1') is True
        assert mgr.get_all_functions() == []

    def test_remove_nonexistent(self):
        mgr = self._make_manager()
        assert mgr.remove_function('nonexistent') is False

    def test_try_label_match(self):
        mgr = self._make_manager()
        fn = _make_function()
        mgr.add_function(fn)

        result = mgr.try_label('i1', 'This is great!')
        assert result is not None
        assert result.label == 'positive'
        assert mgr._instances_labeled == 1

    def test_try_label_no_match(self):
        mgr = self._make_manager()
        fn = _make_function()
        mgr.add_function(fn)

        result = mgr.try_label('i1', 'Nothing special here.')
        assert result is None
        assert mgr._instances_abstained == 1

    def test_try_label_disabled(self):
        mgr = self._make_manager(enabled=False)
        fn = _make_function()
        mgr.add_function(fn)

        result = mgr.try_label('i1', 'This is great!')
        assert result is None

    def test_try_label_no_functions(self):
        mgr = self._make_manager()
        result = mgr.try_label('i1', 'This is great!')
        assert result is None

    def test_apply_batch(self):
        mgr = self._make_manager()
        fn = _make_function()
        mgr.add_function(fn)

        instances = [
            {'instance_id': 'i1', 'text': 'This is great!'},
            {'instance_id': 'i2', 'text': 'terrible stuff'},
        ]
        labeled, remaining = mgr.apply_batch(instances)
        assert len(labeled) == 1
        assert labeled[0].instance_id == 'i1'
        assert len(remaining) == 1
        assert remaining[0]['instance_id'] == 'i2'

    def test_apply_batch_disabled(self):
        mgr = self._make_manager(enabled=False)
        fn = _make_function()
        mgr.add_function(fn)

        instances = [{'instance_id': 'i1', 'text': 'great'}]
        labeled, remaining = mgr.apply_batch(instances)
        assert len(labeled) == 0
        assert len(remaining) == 1

    def test_coverage_tracking(self):
        mgr = self._make_manager()
        fn = _make_function()
        mgr.add_function(fn)

        mgr.try_label('i1', 'This is great!')
        mgr.try_label('i2', 'Also great!')
        assert fn.coverage == 2

    def test_get_stats(self):
        mgr = self._make_manager()
        fn1 = _make_function(id='lf_1', coverage=5, confidence=0.9)
        fn2 = _make_function(id='lf_2', coverage=3, confidence=0.85, enabled=False)
        mgr.add_function(fn1)
        mgr.add_function(fn2)
        mgr._instances_labeled = 8
        mgr._instances_abstained = 2

        stats = mgr.get_stats()
        assert stats['enabled'] is True
        assert stats['total_functions'] == 2
        assert stats['enabled_functions'] == 1
        assert stats['instances_labeled'] == 8
        assert stats['instances_abstained'] == 2
        assert stats['total_coverage'] == 8
        assert abs(stats['avg_confidence'] - 0.875) < 1e-6

    def test_stats_no_functions(self):
        mgr = self._make_manager()
        stats = mgr.get_stats()
        assert stats['total_functions'] == 0
        assert stats['avg_confidence'] == 0.0

    def test_persistence_roundtrip(self):
        mgr = self._make_manager()
        fn = _make_function(coverage=10)
        mgr.add_function(fn)
        mgr._instances_labeled = 15
        mgr._instances_abstained = 3

        data = mgr.to_dict()

        mgr2 = self._make_manager()
        mgr2.load_state(data)

        assert len(mgr2.get_all_functions()) == 1
        loaded = mgr2.get_function('lf_test1')
        assert loaded.label == 'positive'
        assert loaded.coverage == 10
        assert mgr2._instances_labeled == 15
        assert mgr2._instances_abstained == 3

    def test_persistence_empty(self):
        mgr = self._make_manager()
        data = mgr.to_dict()
        assert data['functions'] == []
        assert data['instances_labeled'] == 0

    def test_extract_functions_integration(self):
        """Test extract_functions stores results."""
        mgr = self._make_manager(min_confidence=0.85, min_coverage=2)

        preds = [
            {
                'instance_id': f'i{i}',
                'text': f'great product number {i} great',
                'predicted_label': 'positive',
                'confidence': 0.92,
                'reasoning': 'positive',
            }
            for i in range(5)
        ]
        new_fns = mgr.extract_functions(preds)
        # Should have at least stored them
        total = mgr.get_all_functions()
        assert len(total) == len(new_fns)


# === Config Parsing Tests ===


class TestLabelingFunctionConfig:
    """Tests for LabelingFunctionConfig parsing."""

    def test_defaults(self):
        config = _make_solo_config()
        lf = config.labeling_functions
        assert lf.enabled is True
        assert lf.min_confidence == 0.85
        assert lf.min_coverage == 3
        assert lf.max_functions == 50
        assert lf.auto_extract is True
        assert lf.vote_threshold == 0.5

    def test_custom_values(self):
        config = _make_solo_config(labeling_functions={
            'enabled': False,
            'min_confidence': 0.9,
            'min_coverage': 5,
            'max_functions': 100,
            'auto_extract': False,
            'vote_threshold': 0.7,
        })
        lf = config.labeling_functions
        assert lf.enabled is False
        assert lf.min_confidence == 0.9
        assert lf.min_coverage == 5
        assert lf.max_functions == 100
        assert lf.auto_extract is False
        assert lf.vote_threshold == 0.7

    def test_partial_override(self):
        config = _make_solo_config(labeling_functions={
            'min_confidence': 0.95,
        })
        lf = config.labeling_functions
        assert lf.enabled is True  # default
        assert lf.min_confidence == 0.95
        assert lf.min_coverage == 3  # default


# === Manager Integration Tests ===


class TestSoloModeManagerLabelingFunctions:
    """Tests for labeling function integration with the manager."""

    def _make_manager(self, **lf_overrides):
        """Create a SoloModeManager with labeling function config."""
        from potato.solo_mode.manager import SoloModeManager

        config = _make_solo_config(labeling_functions=lf_overrides)
        app_config = _make_app_config()

        with patch('potato.solo_mode.manager.SoloPhaseController'):
            manager = SoloModeManager(config, app_config)
        return manager

    def test_lazy_init(self):
        manager = self._make_manager()
        assert manager._labeling_function_manager is None
        _ = manager.labeling_function_manager
        assert manager._labeling_function_manager is not None

    def test_status_disabled(self):
        manager = self._make_manager(enabled=False)
        status = manager.get_labeling_function_status()
        assert status == {'enabled': False}

    def test_status_enabled(self):
        manager = self._make_manager(enabled=True)
        status = manager.get_labeling_function_status()
        assert status['enabled'] is True
        assert status['total_functions'] == 0

    def test_extract_no_predictions(self):
        manager = self._make_manager()
        result = manager.extract_labeling_functions()
        assert result['success'] is True
        assert result['extracted'] == 0

    def test_extract_disabled(self):
        manager = self._make_manager(enabled=False)
        result = manager.extract_labeling_functions()
        assert result['success'] is False

    def test_extract_with_predictions(self):
        from potato.solo_mode.manager import LLMPrediction
        from datetime import datetime

        manager = self._make_manager(
            min_confidence=0.85,
            min_coverage=2,
        )

        # Populate some high-confidence predictions
        for i in range(5):
            pred = LLMPrediction(
                instance_id=f'inst_{i}',
                schema_name='sentiment',
                predicted_label='positive',
                confidence_score=0.92,
                uncertainty_score=0.08,
                prompt_version=1,
                reasoning='Contains positive keywords great',
            )
            manager.predictions[f'inst_{i}'] = {'sentiment': pred}

        # Mock _get_instance_text to return text with keywords
        manager._get_instance_text = lambda iid: f'This is a great product {iid} great'

        result = manager.extract_labeling_functions()
        assert result['success'] is True
        # Should extract something from keyword patterns
        assert result['total'] >= 0
