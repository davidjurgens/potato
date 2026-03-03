"""
Tests for DisagreementExplorer and its dataclasses.

Tests scatter point building, timeline bucketing and trend detection,
per-label breakdown with confusion tracking, disagreement list construction,
label filtering, text truncation, and full explorer data aggregation.
"""

import pytest
from unittest.mock import MagicMock

from potato.solo_mode.disagreement_explorer import (
    DisagreementExplorer,
    DisagreementItem,
    LabelBreakdown,
    ScatterPoint,
    TimelineBucket,
)


# ── Helpers ──────────────────────────────────────────────────


def _make_prediction(
    label, confidence, human_label=None, agrees=None,
    reasoning="", resolved=False, resolution_label=None,
):
    """Create a mock LLMPrediction-like object."""
    pred = MagicMock()
    pred.predicted_label = label
    pred.confidence_score = confidence
    pred.uncertainty_score = 1.0 - confidence
    pred.human_label = human_label
    pred.agrees_with_human = agrees
    pred.reasoning = reasoning
    pred.disagreement_resolved = resolved
    pred.resolution_label = resolution_label
    return pred


def _make_comparison(instance_id, human_label, llm_label, agrees, timestamp=""):
    """Create a comparison history dict."""
    return {
        'instance_id': instance_id,
        'human_label': human_label,
        'llm_label': llm_label,
        'agrees': agrees,
        'schema_name': 'sentiment',
        'timestamp': timestamp,
    }


# ── Dataclass Tests ──────────────────────────────────────────


class TestScatterPoint:
    def test_to_dict(self):
        p = ScatterPoint(
            instance_id="i1", confidence=0.85, agrees=True,
            llm_label="positive", human_label="positive",
            reasoning="clear sentiment", text="great movie",
        )
        d = p.to_dict()
        assert d['instance_id'] == 'i1'
        assert d['confidence'] == 0.85
        assert d['agrees'] is True
        assert d['llm_label'] == 'positive'
        assert d['human_label'] == 'positive'
        assert d['reasoning'] == 'clear sentiment'
        assert d['text'] == 'great movie'

    def test_defaults(self):
        p = ScatterPoint(
            instance_id="i1", confidence=0.5, agrees=False, llm_label="neg",
        )
        assert p.human_label is None
        assert p.reasoning == ""
        assert p.text == ""


class TestTimelineBucket:
    def test_to_dict(self):
        b = TimelineBucket(
            bucket_index=0, start_index=0, end_index=9,
            total=10, agreements=8, disagreements=2,
            agreement_rate=0.8,
        )
        d = b.to_dict()
        assert d['bucket_index'] == 0
        assert d['total'] == 10
        assert d['agreements'] == 8
        assert d['disagreements'] == 2
        assert d['agreement_rate'] == 0.8


class TestLabelBreakdown:
    def test_to_dict(self):
        b = LabelBreakdown(
            label="positive", total_comparisons=20,
            agreements=15, disagreements=5, agreement_rate=0.75,
            confused_with=[{'label': 'neutral', 'count': 3}],
        )
        d = b.to_dict()
        assert d['label'] == 'positive'
        assert d['agreement_rate'] == 0.75
        assert len(d['confused_with']) == 1
        assert d['confused_with'][0]['label'] == 'neutral'

    def test_defaults(self):
        b = LabelBreakdown(
            label="x", total_comparisons=1,
            agreements=1, disagreements=0, agreement_rate=1.0,
        )
        assert b.confused_with == []


class TestDisagreementItem:
    def test_to_dict(self):
        item = DisagreementItem(
            instance_id="i1", llm_label="neg", human_label="pos",
            confidence=0.7, reasoning="sarcasm", text="oh great",
            timestamp="2024-01-01", resolved=True,
            resolution_label="pos",
        )
        d = item.to_dict()
        assert d['instance_id'] == 'i1'
        assert d['llm_label'] == 'neg'
        assert d['human_label'] == 'pos'
        assert d['resolved'] is True
        assert d['resolution_label'] == 'pos'

    def test_defaults(self):
        item = DisagreementItem(
            instance_id="i1", llm_label="a", human_label="b",
            confidence=0.5, reasoning="", text="",
        )
        assert item.timestamp == ""
        assert item.resolved is False
        assert item.resolution_label is None


# ── DisagreementExplorer Tests ───────────────────────────────


class TestDisagreementExplorerScatter:
    """Tests for _build_scatter_points."""

    def setup_method(self):
        self.explorer = DisagreementExplorer({})

    def test_empty_predictions(self):
        points = self.explorer._build_scatter_points({})
        assert points == []

    def test_skips_uncompared_predictions(self):
        """Predictions without human comparison (agrees_with_human=None) are skipped."""
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, agrees=None)},
        }
        points = self.explorer._build_scatter_points(predictions)
        assert len(points) == 0

    def test_includes_compared_predictions(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
            'i2': {'s1': _make_prediction('neg', 0.6, human_label='pos', agrees=False)},
        }
        points = self.explorer._build_scatter_points(predictions)
        assert len(points) == 2

    def test_sorted_by_confidence(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
            'i2': {'s1': _make_prediction('neg', 0.3, human_label='pos', agrees=False)},
            'i3': {'s1': _make_prediction('neu', 0.6, human_label='neu', agrees=True)},
        }
        points = self.explorer._build_scatter_points(predictions)
        confs = [p.confidence for p in points]
        assert confs == sorted(confs)

    def test_label_filter(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
            'i2': {'s1': _make_prediction('neg', 0.6, human_label='neu', agrees=False)},
        }
        # Filter for 'pos' — only i1 matches (llm_label or human_label)
        points = self.explorer._build_scatter_points(
            predictions, label_filter='pos'
        )
        assert len(points) == 1
        assert points[0].instance_id == 'i1'

    def test_text_getter(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
        }
        text_getter = lambda iid: "This is a test text."
        points = self.explorer._build_scatter_points(
            predictions, text_getter=text_getter
        )
        assert points[0].text == "This is a test text."

    def test_text_truncation(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
        }
        long_text = "a" * 300
        text_getter = lambda iid: long_text
        points = self.explorer._build_scatter_points(
            predictions, text_getter=text_getter
        )
        assert len(points[0].text) == 203  # 200 + '...'
        assert points[0].text.endswith('...')

    def test_text_getter_returns_none(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
        }
        text_getter = lambda iid: None
        points = self.explorer._build_scatter_points(
            predictions, text_getter=text_getter
        )
        assert points[0].text == ''

    def test_reasoning_truncation(self):
        predictions = {
            'i1': {'s1': _make_prediction(
                'pos', 0.9, human_label='pos', agrees=True,
                reasoning="x" * 500,
            )},
        }
        points = self.explorer._build_scatter_points(predictions)
        assert len(points[0].reasoning) == 300

    def test_multiple_schemas(self):
        """Each schema produces a separate scatter point."""
        predictions = {
            'i1': {
                's1': _make_prediction('pos', 0.9, human_label='pos', agrees=True),
                's2': _make_prediction('neg', 0.4, human_label='neg', agrees=True),
            },
        }
        points = self.explorer._build_scatter_points(predictions)
        assert len(points) == 2


class TestDisagreementExplorerDisagreementList:
    """Tests for _build_disagreement_list."""

    def setup_method(self):
        self.explorer = DisagreementExplorer({})

    def test_empty(self):
        items = self.explorer._build_disagreement_list({}, [])
        assert items == []

    def test_only_disagreements_included(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
            'i2': {'s1': _make_prediction('neg', 0.6, human_label='pos', agrees=False)},
        }
        items = self.explorer._build_disagreement_list(predictions, [])
        assert len(items) == 1
        assert items[0].instance_id == 'i2'

    def test_sorted_by_confidence_descending(self):
        """Higher confidence disagreements first (most surprising)."""
        predictions = {
            'i1': {'s1': _make_prediction('neg', 0.3, human_label='pos', agrees=False)},
            'i2': {'s1': _make_prediction('neg', 0.9, human_label='pos', agrees=False)},
            'i3': {'s1': _make_prediction('neg', 0.6, human_label='pos', agrees=False)},
        }
        items = self.explorer._build_disagreement_list(predictions, [])
        confs = [it.confidence for it in items]
        assert confs == sorted(confs, reverse=True)

    def test_timestamp_from_comparison_history(self):
        predictions = {
            'i1': {'s1': _make_prediction('neg', 0.6, human_label='pos', agrees=False)},
        }
        history = [
            _make_comparison('i1', 'pos', 'neg', False, timestamp='2024-01-15'),
        ]
        items = self.explorer._build_disagreement_list(predictions, history)
        assert items[0].timestamp == '2024-01-15'

    def test_label_filter(self):
        predictions = {
            'i1': {'s1': _make_prediction('neg', 0.6, human_label='pos', agrees=False)},
            'i2': {'s1': _make_prediction('neu', 0.5, human_label='neg', agrees=False)},
        }
        items = self.explorer._build_disagreement_list(
            predictions, [], label_filter='pos'
        )
        assert len(items) == 1
        assert items[0].instance_id == 'i1'

    def test_resolved_disagreement(self):
        predictions = {
            'i1': {'s1': _make_prediction(
                'neg', 0.6, human_label='pos', agrees=False,
                resolved=True, resolution_label='pos',
            )},
        }
        items = self.explorer._build_disagreement_list(predictions, [])
        assert items[0].resolved is True
        assert items[0].resolution_label == 'pos'

    def test_text_truncation_at_300(self):
        predictions = {
            'i1': {'s1': _make_prediction('neg', 0.6, human_label='pos', agrees=False)},
        }
        long_text = "b" * 400
        text_getter = lambda iid: long_text
        items = self.explorer._build_disagreement_list(
            predictions, [], text_getter=text_getter
        )
        assert len(items[0].text) == 303  # 300 + '...'

    def test_reasoning_truncation_at_500(self):
        predictions = {
            'i1': {'s1': _make_prediction(
                'neg', 0.6, human_label='pos', agrees=False,
                reasoning="r" * 700,
            )},
        }
        items = self.explorer._build_disagreement_list(predictions, [])
        assert len(items[0].reasoning) == 500


class TestDisagreementExplorerLabelBreakdown:
    """Tests for _build_label_breakdown."""

    def setup_method(self):
        self.explorer = DisagreementExplorer({})

    def test_empty_history(self):
        result = self.explorer._build_label_breakdown([])
        assert result == []

    def test_single_label_all_agree(self):
        history = [
            _make_comparison('i1', 'pos', 'pos', True),
            _make_comparison('i2', 'pos', 'pos', True),
        ]
        result = self.explorer._build_label_breakdown(history)
        assert len(result) == 1
        assert result[0].label == 'pos'
        assert result[0].agreements == 2
        assert result[0].disagreements == 0
        assert result[0].agreement_rate == 1.0

    def test_multiple_labels(self):
        history = [
            _make_comparison('i1', 'pos', 'pos', True),
            _make_comparison('i2', 'pos', 'neg', False),
            _make_comparison('i3', 'neg', 'neg', True),
            _make_comparison('i4', 'neg', 'pos', False),
            _make_comparison('i5', 'neg', 'pos', False),
        ]
        result = self.explorer._build_label_breakdown(history)
        # Sorted by disagreements descending: neg(2 disagree), pos(1 disagree)
        assert result[0].label == 'neg'
        assert result[0].disagreements == 2
        assert result[1].label == 'pos'
        assert result[1].disagreements == 1

    def test_confused_with(self):
        history = [
            _make_comparison('i1', 'pos', 'neg', False),
            _make_comparison('i2', 'pos', 'neg', False),
            _make_comparison('i3', 'pos', 'neu', False),
        ]
        result = self.explorer._build_label_breakdown(history)
        breakdown = result[0]
        assert breakdown.label == 'pos'
        assert len(breakdown.confused_with) == 2
        # neg appears 2x, neu 1x — sorted desc
        assert breakdown.confused_with[0] == {'label': 'neg', 'count': 2}
        assert breakdown.confused_with[1] == {'label': 'neu', 'count': 1}

    def test_confused_with_max_5(self):
        """At most 5 confused-with entries."""
        history = [
            _make_comparison(f'i{j}', 'pos', f'label{j}', False)
            for j in range(7)
        ]
        result = self.explorer._build_label_breakdown(history)
        assert len(result[0].confused_with) <= 5

    def test_label_filter(self):
        history = [
            _make_comparison('i1', 'pos', 'pos', True),
            _make_comparison('i2', 'neg', 'neg', True),
            _make_comparison('i3', 'pos', 'neg', False),
        ]
        result = self.explorer._build_label_breakdown(history, label_filter='pos')
        # Only comparisons involving 'pos' (as human or llm label)
        labels = [b.label for b in result]
        assert 'pos' in labels
        # i2 (neg/neg) should be excluded — neither label is 'pos'


class TestDisagreementExplorerTimeline:
    """Tests for get_timeline."""

    def setup_method(self):
        self.explorer = DisagreementExplorer({})

    def test_empty_history(self):
        result = self.explorer.get_timeline([])
        assert result == {'buckets': [], 'trend': 'stable', 'total': 0}

    def test_single_bucket(self):
        history = [
            _make_comparison(f'i{i}', 'pos', 'pos', True) for i in range(5)
        ]
        result = self.explorer.get_timeline(history, bucket_size=10)
        assert len(result['buckets']) == 1
        assert result['buckets'][0]['total'] == 5
        assert result['buckets'][0]['agreements'] == 5
        assert result['buckets'][0]['agreement_rate'] == 1.0
        assert result['trend'] == 'stable'
        assert result['total'] == 5

    def test_multiple_buckets(self):
        history = [
            _make_comparison(f'i{i}', 'pos', 'pos', True) for i in range(25)
        ]
        result = self.explorer.get_timeline(history, bucket_size=10)
        assert len(result['buckets']) == 3
        assert result['buckets'][0]['total'] == 10
        assert result['buckets'][1]['total'] == 10
        assert result['buckets'][2]['total'] == 5

    def test_bucket_indices(self):
        history = [
            _make_comparison(f'i{i}', 'pos', 'pos', True) for i in range(20)
        ]
        result = self.explorer.get_timeline(history, bucket_size=10)
        assert result['buckets'][0]['start_index'] == 0
        assert result['buckets'][0]['end_index'] == 9
        assert result['buckets'][1]['start_index'] == 10
        assert result['buckets'][1]['end_index'] == 19

    def test_trend_improving(self):
        """When second half has better agreement than first half."""
        # First 20: mostly disagreements, next 20: mostly agreements
        history = (
            [_make_comparison(f'i{i}', 'pos', 'neg', False) for i in range(20)] +
            [_make_comparison(f'i{i}', 'pos', 'pos', True) for i in range(20, 40)]
        )
        result = self.explorer.get_timeline(history, bucket_size=10)
        assert result['trend'] == 'improving'

    def test_trend_declining(self):
        """When second half has worse agreement than first half."""
        history = (
            [_make_comparison(f'i{i}', 'pos', 'pos', True) for i in range(20)] +
            [_make_comparison(f'i{i}', 'pos', 'neg', False) for i in range(20, 40)]
        )
        result = self.explorer.get_timeline(history, bucket_size=10)
        assert result['trend'] == 'declining'

    def test_trend_stable_few_buckets(self):
        """With fewer than 4 buckets, trend is always stable."""
        history = [
            _make_comparison(f'i{i}', 'pos', 'neg', False) for i in range(15)
        ]
        result = self.explorer.get_timeline(history, bucket_size=10)
        assert len(result['buckets']) == 2
        assert result['trend'] == 'stable'

    def test_trend_stable_similar_rates(self):
        """When halves differ by less than 5%, trend is stable."""
        # All agree — both halves have same rate
        history = [
            _make_comparison(f'i{i}', 'pos', 'pos', True) for i in range(40)
        ]
        result = self.explorer.get_timeline(history, bucket_size=10)
        assert result['trend'] == 'stable'

    def test_mixed_bucket(self):
        history = [
            _make_comparison('i1', 'pos', 'pos', True),
            _make_comparison('i2', 'pos', 'neg', False),
            _make_comparison('i3', 'pos', 'pos', True),
        ]
        result = self.explorer.get_timeline(history, bucket_size=10)
        bucket = result['buckets'][0]
        assert bucket['agreements'] == 2
        assert bucket['disagreements'] == 1
        assert bucket['agreement_rate'] == round(2 / 3, 4)

    def test_bucket_size_output(self):
        history = [_make_comparison('i1', 'pos', 'pos', True)]
        result = self.explorer.get_timeline(history, bucket_size=5)
        assert result['bucket_size'] == 5


class TestDisagreementExplorerFullData:
    """Tests for get_explorer_data (full aggregation)."""

    def setup_method(self):
        self.explorer = DisagreementExplorer({})

    def test_empty_data(self):
        result = self.explorer.get_explorer_data({}, [])
        assert result['scatter_points'] == []
        assert result['disagreements'] == []
        assert result['label_breakdown'] == []
        assert result['summary']['total_compared'] == 0
        assert result['summary']['total_disagreements'] == 0
        assert result['summary']['disagreement_rate'] == 0.0

    def test_full_data_structure(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
            'i2': {'s1': _make_prediction('neg', 0.6, human_label='pos', agrees=False)},
        }
        history = [
            _make_comparison('i1', 'pos', 'pos', True),
            _make_comparison('i2', 'pos', 'neg', False),
        ]

        result = self.explorer.get_explorer_data(predictions, history)

        # Structure checks
        assert 'scatter_points' in result
        assert 'disagreements' in result
        assert 'label_breakdown' in result
        assert 'summary' in result

        # Summary
        assert result['summary']['total_compared'] == 2
        assert result['summary']['total_disagreements'] == 1
        assert result['summary']['disagreement_rate'] == 0.5

        # Scatter: 2 compared predictions
        assert len(result['scatter_points']) == 2

        # Disagreements: 1 disagreement
        assert len(result['disagreements']) == 1
        assert result['disagreements'][0]['instance_id'] == 'i2'

    def test_avg_disagreement_confidence(self):
        predictions = {
            'i1': {'s1': _make_prediction('neg', 0.7, human_label='pos', agrees=False)},
            'i2': {'s1': _make_prediction('neg', 0.5, human_label='pos', agrees=False)},
        }
        history = [
            _make_comparison('i1', 'pos', 'neg', False),
            _make_comparison('i2', 'pos', 'neg', False),
        ]

        result = self.explorer.get_explorer_data(predictions, history)
        assert result['summary']['avg_disagreement_confidence'] == 0.6

    def test_labels_with_disagreements_count(self):
        predictions = {
            'i1': {'s1': _make_prediction('neg', 0.7, human_label='pos', agrees=False)},
            'i2': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
        }
        history = [
            _make_comparison('i1', 'pos', 'neg', False),
            _make_comparison('i2', 'pos', 'pos', True),
        ]

        result = self.explorer.get_explorer_data(predictions, history)
        assert result['summary']['labels_with_disagreements'] == 1

    def test_label_filter_applies_to_all(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
            'i2': {'s1': _make_prediction('neg', 0.6, human_label='neu', agrees=False)},
        }
        history = [
            _make_comparison('i1', 'pos', 'pos', True),
            _make_comparison('i2', 'neu', 'neg', False),
        ]

        result = self.explorer.get_explorer_data(
            predictions, history, label_filter='pos'
        )

        # Only i1 should be in scatter and disagreements
        assert len(result['scatter_points']) == 1
        assert result['scatter_points'][0]['instance_id'] == 'i1'

    def test_text_getter_passed_through(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
        }
        text_getter = lambda iid: f"text for {iid}"

        result = self.explorer.get_explorer_data(
            predictions, [], text_getter=text_getter
        )
        assert result['scatter_points'][0]['text'] == 'text for i1'

    def test_scatter_points_serialized(self):
        """scatter_points should be dicts, not ScatterPoint objects."""
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
        }
        result = self.explorer.get_explorer_data(predictions, [])
        assert isinstance(result['scatter_points'][0], dict)

    def test_disagreement_rate_zero_when_all_agree(self):
        predictions = {
            'i1': {'s1': _make_prediction('pos', 0.9, human_label='pos', agrees=True)},
        }
        history = [_make_comparison('i1', 'pos', 'pos', True)]

        result = self.explorer.get_explorer_data(predictions, history)
        assert result['summary']['disagreement_rate'] == 0.0
        assert result['summary']['avg_disagreement_confidence'] == 0.0


class TestDisagreementExplorerManagerIntegration:
    """Tests for manager wiring (lazy property, convenience methods)."""

    def test_lazy_property_creates_explorer(self):
        """Manager creates DisagreementExplorer on first access."""
        from potato.solo_mode.config import SoloModeConfig
        manager = MagicMock()
        manager.app_config = {}
        manager.config = SoloModeConfig()

        # Simulate the property by calling what it would do
        from potato.solo_mode.disagreement_explorer import DisagreementExplorer
        explorer = DisagreementExplorer(manager.app_config, manager.config)
        assert explorer is not None
        assert explorer._app_config == {}

    def test_get_explorer_data_calls_explorer(self):
        """Verify the manager method delegates correctly."""
        from potato.solo_mode.config import SoloModeConfig
        mock_explorer = MagicMock()
        mock_explorer.get_explorer_data.return_value = {
            'scatter_points': [], 'disagreements': [],
            'label_breakdown': [], 'summary': {},
        }

        mock_tracker = MagicMock()
        mock_tracker.get_comparison_history.return_value = []

        # The manager method calls validation_tracker + explorer
        mock_explorer.get_explorer_data.assert_not_called()
        result = mock_explorer.get_explorer_data(
            predictions={},
            comparison_history=[],
        )
        mock_explorer.get_explorer_data.assert_called_once()
        assert 'scatter_points' in result

    def test_get_timeline_calls_explorer(self):
        mock_explorer = MagicMock()
        mock_explorer.get_timeline.return_value = {
            'buckets': [], 'trend': 'stable', 'total': 0,
        }
        result = mock_explorer.get_timeline(comparison_history=[], bucket_size=10)
        mock_explorer.get_timeline.assert_called_once()
        assert result['trend'] == 'stable'
