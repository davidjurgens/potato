"""
Tests for the lean final-dataset export (potato/solo_mode/final_dataset.py).

Covers the source classification (human/llm/agreed/resolved/pending) and
the row-building/CSV-rendering logic, with a minimal mock manager rather
than a full SoloModeManager instance.
"""

import pytest
from unittest.mock import MagicMock

from potato.solo_mode.final_dataset import _classify, build_rows, to_csv


def _prediction(predicted_label="a", confidence_score=0.8,
                 disagreement_resolved=False, resolution_label=None):
    p = MagicMock()
    p.predicted_label = predicted_label
    p.confidence_score = confidence_score
    p.disagreement_resolved = disagreement_resolved
    p.resolution_label = resolution_label
    return p


class TestClassify:
    """Tests for the per-(instance, schema) source classification."""

    def test_human_only(self):
        label, source, note = _classify(None, "positive")
        assert label == "positive"
        assert source == "human"
        assert note == ""

    def test_llm_only(self):
        pred = _prediction(predicted_label="negative", confidence_score=0.73)
        label, source, note = _classify(pred, None)
        assert label == "negative"
        assert source == "llm"
        assert "0.73" in note

    def test_llm_only_no_confidence(self):
        pred = _prediction(predicted_label="negative", confidence_score=None)
        label, source, note = _classify(pred, None)
        assert source == "llm"
        assert note == "LLM only"

    def test_agreed(self):
        pred = _prediction(predicted_label="positive")
        label, source, note = _classify(pred, "positive")
        assert label == "positive"
        assert source == "agreed"
        assert note == ""

    def test_resolved(self):
        pred = _prediction(
            predicted_label="wait times", disagreement_resolved=True,
            resolution_label="access barriers")
        label, source, note = _classify(pred, "access barriers")
        assert label == "access barriers"
        assert source == "resolved"
        assert "wait times" in note

    def test_pending_disagreement(self):
        pred = _prediction(predicted_label="wait times",
                            disagreement_resolved=False)
        label, source, note = _classify(pred, "access barriers")
        assert label == "access barriers"  # human's current label stands
        assert source == "pending"
        assert "wait times" in note


class TestBuildRows:
    """Tests for build_rows against a mock manager."""

    def _manager(self, schemas, human_labeled_ids, predictions, human_labels,
                 texts=None):
        m = MagicMock()
        m.app_config = {'annotation_schemes': [{'name': s} for s in schemas]}
        m.human_labeled_ids = set(human_labeled_ids)
        m.predictions = predictions

        def get_human_label(instance_id, schema_name):
            return human_labels.get((instance_id, schema_name))
        m._get_stored_human_label.side_effect = get_human_label

        texts = texts or {}
        m._get_instance_text.side_effect = lambda iid: texts.get(iid, "")
        return m

    def test_single_schema_omits_schema_column(self):
        m = self._manager(
            schemas=["sentiment"],
            human_labeled_ids=["1"],
            predictions={},
            human_labels={("1", "sentiment"): "positive"},
            texts={"1": "great visit"},
        )
        rows = build_rows(m)
        assert len(rows) == 1
        assert rows[0] == {
            'instance_id': '1', 'text': 'great visit',
            'final_label': 'positive', 'source': 'human', 'note': '',
        }
        assert 'schema' not in rows[0]

    def test_multi_schema_includes_schema_column(self):
        m = self._manager(
            schemas=["sentiment", "topic"],
            human_labeled_ids=["1"],
            predictions={},
            human_labels={
                ("1", "sentiment"): "positive",
                ("1", "topic"): "billing",
            },
            texts={"1": "great visit"},
        )
        rows = build_rows(m)
        assert len(rows) == 2
        schemas_seen = {r['schema'] for r in rows}
        assert schemas_seen == {"sentiment", "topic"}

    def test_llm_only_instance_included(self):
        pred = _prediction(predicted_label="negative", confidence_score=0.5)
        m = self._manager(
            schemas=["sentiment"],
            human_labeled_ids=[],
            predictions={"2": {"sentiment": pred}},
            human_labels={},
            texts={"2": "bad visit"},
        )
        rows = build_rows(m)
        assert len(rows) == 1
        assert rows[0]['source'] == 'llm'
        assert rows[0]['final_label'] == 'negative'

    def test_instance_with_neither_label_excluded(self):
        m = self._manager(
            schemas=["sentiment"],
            human_labeled_ids=[],
            predictions={},
            human_labels={},
        )
        # Nothing labeled at all -> no rows, even if instance existed.
        assert build_rows(m) == []

    def test_rows_sorted_by_instance_id(self):
        m = self._manager(
            schemas=["sentiment"],
            human_labeled_ids=["10", "2"],
            predictions={},
            human_labels={("10", "sentiment"): "a", ("2", "sentiment"): "b"},
        )
        rows = build_rows(m)
        # String-sorted, not numeric — just confirms deterministic order.
        assert [r['instance_id'] for r in rows] == sorted(["10", "2"])


class TestToCsv:
    """Tests for CSV rendering."""

    def test_renders_header_and_rows(self):
        rows = [{
            'instance_id': '1', 'text': 'hello', 'final_label': 'positive',
            'source': 'human', 'note': '',
        }]
        csv_text = to_csv(rows)
        lines = csv_text.strip().splitlines()
        assert lines[0] == 'instance_id,text,final_label,source,note'
        assert lines[1] == '1,hello,positive,human,'

    def test_empty_rows_still_has_default_header(self):
        csv_text = to_csv([])
        lines = csv_text.strip().splitlines()
        assert lines == ['instance_id,text,final_label,source,note']

    def test_quotes_fields_with_commas(self):
        rows = [{
            'instance_id': '1', 'text': 'hello, world', 'final_label': 'x',
            'source': 'human', 'note': '',
        }]
        csv_text = to_csv(rows)
        assert '"hello, world"' in csv_text
