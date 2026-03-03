"""
Tests for ConfusionAnalyzer.

Tests confusion pattern analysis, heatmap data generation,
dataclass serialization, config parsing, and LLM integration.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.solo_mode.confusion_analyzer import (
    ConfusionAnalyzer,
    ConfusionExample,
    ConfusionPattern,
)
from potato.solo_mode.config import (
    ConfusionAnalysisConfig,
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


def _make_analyzer(solo_config=None, app_config=None):
    """Create a ConfusionAnalyzer for testing."""
    if solo_config is None:
        solo_config = _make_solo_config()
    if app_config is None:
        app_config = {
            'annotation_schemes': [
                {'name': 'sentiment', 'annotation_type': 'radio',
                 'labels': ['positive', 'negative', 'neutral']},
            ],
        }
    return ConfusionAnalyzer(app_config, solo_config)


def _make_comparison(instance_id, llm_label, human_label, agrees=None):
    """Create a comparison history record."""
    if agrees is None:
        agrees = (llm_label == human_label)
    return {
        'instance_id': instance_id,
        'llm_label': llm_label,
        'human_label': human_label,
        'schema_name': 'sentiment',
        'agrees': agrees,
        'timestamp': '2025-01-01T00:00:00',
    }


# === Dataclass Tests ===


class TestConfusionExample:
    """Tests for ConfusionExample dataclass."""

    def test_to_dict_basic(self):
        ex = ConfusionExample(
            instance_id='i1',
            text='Sample text',
        )
        d = ex.to_dict()
        assert d['instance_id'] == 'i1'
        assert d['text'] == 'Sample text'
        assert 'llm_reasoning' not in d
        assert 'llm_confidence' not in d

    def test_to_dict_with_optional_fields(self):
        ex = ConfusionExample(
            instance_id='i2',
            text='Another text',
            llm_reasoning='It seemed positive',
            llm_confidence=0.85,
        )
        d = ex.to_dict()
        assert d['llm_reasoning'] == 'It seemed positive'
        assert d['llm_confidence'] == 0.85


class TestConfusionPattern:
    """Tests for ConfusionPattern dataclass."""

    def test_to_dict_minimal(self):
        p = ConfusionPattern(
            predicted_label='positive',
            actual_label='negative',
            count=5,
            percent=25.0,
        )
        d = p.to_dict()
        assert d['predicted_label'] == 'positive'
        assert d['actual_label'] == 'negative'
        assert d['count'] == 5
        assert d['percent'] == 25.0
        assert d['examples'] == []
        assert 'root_cause' not in d
        assert 'guideline_suggestion' not in d

    def test_to_dict_with_examples(self):
        p = ConfusionPattern(
            predicted_label='positive',
            actual_label='negative',
            count=3,
            percent=15.0,
            examples=[
                ConfusionExample(instance_id='i1', text='text1'),
                ConfusionExample(instance_id='i2', text='text2'),
            ],
        )
        d = p.to_dict()
        assert len(d['examples']) == 2
        assert d['examples'][0]['instance_id'] == 'i1'

    def test_to_dict_with_root_cause_and_suggestion(self):
        p = ConfusionPattern(
            predicted_label='positive',
            actual_label='neutral',
            count=4,
            percent=20.0,
            root_cause='Sarcasm is ambiguous',
            guideline_suggestion='Look for ironic markers',
        )
        d = p.to_dict()
        assert d['root_cause'] == 'Sarcasm is ambiguous'
        assert d['guideline_suggestion'] == 'Look for ironic markers'


# === Analyze Tests ===


class TestConfusionAnalyzerAnalyze:
    """Tests for ConfusionAnalyzer.analyze()."""

    def test_empty_history(self):
        analyzer = _make_analyzer()
        result = analyzer.analyze([], {})
        assert result == []

    def test_agreements_only(self):
        analyzer = _make_analyzer()
        history = [
            _make_comparison('i1', 'positive', 'positive'),
            _make_comparison('i2', 'negative', 'negative'),
        ]
        result = analyzer.analyze(history, {})
        assert result == []

    def test_groups_by_label_pair(self):
        config = _make_solo_config(confusion_analysis={'min_instances_for_pattern': 2})
        analyzer = _make_analyzer(solo_config=config)

        history = [
            _make_comparison('i1', 'positive', 'negative'),
            _make_comparison('i2', 'positive', 'negative'),
            _make_comparison('i3', 'positive', 'negative'),
            _make_comparison('i4', 'neutral', 'positive'),
            _make_comparison('i5', 'neutral', 'positive'),
        ]

        result = analyzer.analyze(history, {})
        assert len(result) == 2
        # Sorted by count descending
        assert result[0].predicted_label == 'positive'
        assert result[0].actual_label == 'negative'
        assert result[0].count == 3
        assert result[1].predicted_label == 'neutral'
        assert result[1].actual_label == 'positive'
        assert result[1].count == 2

    def test_min_instances_filter(self):
        config = _make_solo_config(confusion_analysis={'min_instances_for_pattern': 3})
        analyzer = _make_analyzer(solo_config=config)

        history = [
            _make_comparison('i1', 'positive', 'negative'),
            _make_comparison('i2', 'positive', 'negative'),
            # Only 2 instances — should be filtered out
        ]

        result = analyzer.analyze(history, {})
        assert result == []

    def test_max_patterns_limit(self):
        config = _make_solo_config(confusion_analysis={
            'min_instances_for_pattern': 1,
            'max_patterns': 2,
        })
        analyzer = _make_analyzer(solo_config=config)

        history = [
            _make_comparison('i1', 'A', 'B'),
            _make_comparison('i2', 'C', 'D'),
            _make_comparison('i3', 'E', 'F'),
        ]

        result = analyzer.analyze(history, {})
        assert len(result) == 2

    def test_percent_calculation(self):
        config = _make_solo_config(confusion_analysis={'min_instances_for_pattern': 1})
        analyzer = _make_analyzer(solo_config=config)

        history = [
            _make_comparison('i1', 'positive', 'negative'),
            _make_comparison('i2', 'positive', 'negative'),
            _make_comparison('i3', 'neutral', 'positive'),
            _make_comparison('i4', 'neutral', 'positive'),
            _make_comparison('i5', 'positive', 'positive'),  # agreement, excluded
        ]

        result = analyzer.analyze(history, {})
        # 4 total disagreements; each pattern has 2 = 50%
        for pattern in result:
            assert abs(pattern.percent - 50.0) < 0.1

    def test_examples_from_text_getter(self):
        config = _make_solo_config(confusion_analysis={'min_instances_for_pattern': 1})
        analyzer = _make_analyzer(solo_config=config)

        history = [
            _make_comparison('i1', 'positive', 'negative'),
        ]

        def text_getter(iid):
            return f"Text for {iid}"

        result = analyzer.analyze(history, {}, text_getter=text_getter)
        assert len(result) == 1
        assert len(result[0].examples) == 1
        assert result[0].examples[0].text == 'Text for i1'

    def test_examples_with_predictions(self):
        config = _make_solo_config(confusion_analysis={'min_instances_for_pattern': 1})
        analyzer = _make_analyzer(solo_config=config)

        history = [
            _make_comparison('i1', 'positive', 'negative'),
        ]

        mock_pred = MagicMock()
        mock_pred.reasoning = 'It has positive words'
        mock_pred.confidence_score = 0.75

        predictions = {'i1': {'sentiment': mock_pred}}

        result = analyzer.analyze(history, predictions)
        ex = result[0].examples[0]
        assert ex.llm_reasoning == 'It has positive words'
        assert ex.llm_confidence == 0.75

    def test_text_getter_exception_handled(self):
        config = _make_solo_config(confusion_analysis={'min_instances_for_pattern': 1})
        analyzer = _make_analyzer(solo_config=config)

        history = [
            _make_comparison('i1', 'positive', 'negative'),
        ]

        def bad_getter(iid):
            raise ValueError("Item not found")

        result = analyzer.analyze(history, {}, text_getter=bad_getter)
        assert len(result) == 1
        assert result[0].examples[0].text == ''

    def test_text_truncation(self):
        config = _make_solo_config(confusion_analysis={'min_instances_for_pattern': 1})
        analyzer = _make_analyzer(solo_config=config)

        history = [
            _make_comparison('i1', 'positive', 'negative'),
        ]

        long_text = 'x' * 500

        result = analyzer.analyze(history, {}, text_getter=lambda _: long_text)
        assert len(result[0].examples[0].text) == 203  # 200 + '...'
        assert result[0].examples[0].text.endswith('...')


# === Heatmap Data Tests ===


class TestConfusionMatrixData:
    """Tests for get_confusion_matrix_data()."""

    def test_complete_matrix(self):
        analyzer = _make_analyzer()
        matrix = {
            ('positive', 'negative'): 5,
            ('neutral', 'positive'): 3,
        }
        labels = ['positive', 'negative', 'neutral']

        result = analyzer.get_confusion_matrix_data(matrix, labels)

        assert result['labels'] == labels
        assert result['max_count'] == 5
        assert len(result['cells']) == 9  # 3x3

        # Verify specific cells
        cell_map = {(c['predicted'], c['actual']): c['count'] for c in result['cells']}
        assert cell_map[('positive', 'negative')] == 5
        assert cell_map[('neutral', 'positive')] == 3
        assert cell_map[('positive', 'positive')] == 0

    def test_empty_matrix(self):
        analyzer = _make_analyzer()
        result = analyzer.get_confusion_matrix_data({}, ['A', 'B'])

        assert result['max_count'] == 0
        assert len(result['cells']) == 4
        assert all(c['count'] == 0 for c in result['cells'])

    def test_with_label_accuracy(self):
        analyzer = _make_analyzer()
        accuracy = {'positive': 0.9, 'negative': 0.7}
        result = analyzer.get_confusion_matrix_data({}, ['positive', 'negative'],
                                                    label_accuracy=accuracy)
        assert result['label_accuracy'] == accuracy

    def test_no_labels(self):
        analyzer = _make_analyzer()
        result = analyzer.get_confusion_matrix_data({}, [])
        assert result['cells'] == []
        assert result['max_count'] == 0


# === LLM Integration Tests ===


class TestConfusionAnalyzerLLM:
    """Tests for LLM-powered root cause and suggestion generation."""

    def test_root_cause_without_endpoint_returns_none(self):
        analyzer = _make_analyzer()
        pattern = ConfusionPattern(
            predicted_label='positive',
            actual_label='negative',
            count=5,
            percent=25.0,
        )
        result = analyzer.generate_root_cause(pattern)
        assert result is None

    def test_root_cause_with_mock_endpoint(self):
        analyzer = _make_analyzer()
        mock_endpoint = MagicMock()
        mock_endpoint.query.return_value = '{"root_cause": "Sarcasm is ambiguous"}'
        analyzer._endpoint = mock_endpoint

        pattern = ConfusionPattern(
            predicted_label='positive',
            actual_label='negative',
            count=5,
            percent=25.0,
            examples=[
                ConfusionExample(instance_id='i1', text='Great product, if you like trash'),
            ],
        )

        result = analyzer.generate_root_cause(pattern)
        assert result == 'Sarcasm is ambiguous'
        mock_endpoint.query.assert_called_once()

    def test_suggest_guideline_without_endpoint_returns_none(self):
        analyzer = _make_analyzer()
        pattern = ConfusionPattern(
            predicted_label='positive',
            actual_label='negative',
            count=5,
            percent=25.0,
        )
        result = analyzer.suggest_guideline(pattern, 'test prompt')
        assert result is None

    def test_suggest_guideline_with_mock_endpoint(self):
        analyzer = _make_analyzer()
        mock_endpoint = MagicMock()
        mock_endpoint.query.return_value = '{"suggestion": "Check for sarcastic markers"}'
        analyzer._endpoint = mock_endpoint

        pattern = ConfusionPattern(
            predicted_label='positive',
            actual_label='negative',
            count=5,
            percent=25.0,
            root_cause='Sarcasm is ambiguous',
        )

        result = analyzer.suggest_guideline(pattern, 'Label sentiment as positive or negative')
        assert result == 'Check for sarcastic markers'

    def test_root_cause_handles_llm_error(self):
        analyzer = _make_analyzer()
        mock_endpoint = MagicMock()
        mock_endpoint.query.side_effect = Exception("API error")
        analyzer._endpoint = mock_endpoint

        pattern = ConfusionPattern(
            predicted_label='positive',
            actual_label='negative',
            count=5,
            percent=25.0,
        )

        result = analyzer.generate_root_cause(pattern)
        assert result is None

    def test_suggest_guideline_handles_llm_error(self):
        analyzer = _make_analyzer()
        mock_endpoint = MagicMock()
        mock_endpoint.query.side_effect = Exception("API error")
        analyzer._endpoint = mock_endpoint

        pattern = ConfusionPattern(
            predicted_label='positive',
            actual_label='negative',
            count=5,
            percent=25.0,
        )

        result = analyzer.suggest_guideline(pattern, 'test prompt')
        assert result is None

    def test_parse_json_markdown_fenced(self):
        analyzer = _make_analyzer()
        response = '```json\n{"root_cause": "value"}\n```'
        result = analyzer._parse_json(response)
        assert result == {'root_cause': 'value'}

    def test_parse_json_plain(self):
        analyzer = _make_analyzer()
        result = analyzer._parse_json('{"key": "val"}')
        assert result == {'key': 'val'}

    def test_parse_json_dict_passthrough(self):
        analyzer = _make_analyzer()
        d = {'key': 'val'}
        result = analyzer._parse_json(d)
        assert result is d

    def test_parse_json_invalid_returns_empty(self):
        analyzer = _make_analyzer()
        result = analyzer._parse_json('not json at all')
        assert result == {}


# === Config Parsing Tests ===


class TestConfusionAnalysisConfig:
    """Tests for ConfusionAnalysisConfig parsing."""

    def test_defaults(self):
        config = _make_solo_config()
        ca = config.confusion_analysis
        assert ca.enabled is True
        assert ca.min_instances_for_pattern == 3
        assert ca.max_patterns == 20
        assert ca.auto_suggest_guidelines is False

    def test_custom_values(self):
        config = _make_solo_config(confusion_analysis={
            'enabled': False,
            'min_instances_for_pattern': 5,
            'max_patterns': 50,
            'auto_suggest_guidelines': True,
        })
        ca = config.confusion_analysis
        assert ca.enabled is False
        assert ca.min_instances_for_pattern == 5
        assert ca.max_patterns == 50
        assert ca.auto_suggest_guidelines is True

    def test_partial_override(self):
        config = _make_solo_config(confusion_analysis={
            'min_instances_for_pattern': 10,
        })
        ca = config.confusion_analysis
        assert ca.enabled is True  # default kept
        assert ca.min_instances_for_pattern == 10
        assert ca.max_patterns == 20  # default kept


# === Truncation Tests ===


class TestTruncation:
    """Tests for text truncation helper."""

    def test_short_text_unchanged(self):
        analyzer = _make_analyzer()
        assert analyzer._truncate('short') == 'short'

    def test_empty_text(self):
        analyzer = _make_analyzer()
        assert analyzer._truncate('') == ''

    def test_none_text(self):
        analyzer = _make_analyzer()
        assert analyzer._truncate(None) == ''

    def test_long_text_truncated(self):
        analyzer = _make_analyzer()
        text = 'a' * 300
        result = analyzer._truncate(text)
        assert len(result) == 203
        assert result.endswith('...')

    def test_exact_limit_unchanged(self):
        analyzer = _make_analyzer()
        text = 'b' * 200
        assert analyzer._truncate(text) == text
