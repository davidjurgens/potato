"""
Tests for the organized process-data export (potato/solo_mode/process_export.py).

Covers each file independently — behavioral metadata, validation (human
and LLM kept separate), cooperative annotation, and codebook version
history — plus the ZIP bundling.
"""

import json
import zipfile
from io import BytesIO
from unittest.mock import MagicMock, patch

from potato.solo_mode.process_export import (
    build_behavioral_rows,
    build_codebook_snapshots,
    build_codebook_version_rows,
    build_cooperative_rows,
    build_validation_human_rows,
    build_validation_llm_rows,
    build_zip,
)


def _prediction(predicted_label="a", confidence_score=0.8, human_label=None,
                 agrees_with_human=None, disagreement_resolved=False,
                 resolution_label=None):
    p = MagicMock()
    p.predicted_label = predicted_label
    p.confidence_score = confidence_score
    p.human_label = human_label
    p.agrees_with_human = agrees_with_human
    p.disagreement_resolved = disagreement_resolved
    p.resolution_label = resolution_label
    return p


def _manager(schema="sentiment", predictions=None, validation_sample_ids=None,
             validated_instance_ids=None, texts=None,
             codebook_version_history=None):
    m = MagicMock()
    m.app_config = {'annotation_schemes': [{'name': schema}]}
    m.predictions = predictions or {}
    m.validation_sample_ids = set(validation_sample_ids or [])
    m.validated_instance_ids = set(validated_instance_ids or [])
    m.codebook_version_history = codebook_version_history or {}
    texts = texts or {}
    m._get_instance_text.side_effect = lambda iid: texts.get(iid, "")
    return m


class TestValidationRows:
    """Tests for the split human/LLM validation files."""

    def test_human_file_has_no_llm_fields(self):
        m = _manager(
            predictions={"1": {"sentiment": _prediction(
                predicted_label="positive", human_label="negative")}},
            validation_sample_ids=["1"], validated_instance_ids=["1"],
            texts={"1": "meh"},
        )
        rows = build_validation_human_rows(m)
        assert len(rows) == 1
        assert rows[0] == {
            'instance_id': '1', 'text': 'meh', 'human_label': 'negative',
        }
        assert 'llm_label' not in rows[0]

    def test_llm_file_has_no_human_fields(self):
        m = _manager(
            predictions={"1": {"sentiment": _prediction(
                predicted_label="positive", human_label="negative",
                confidence_score=0.61)}},
            validation_sample_ids=["1"], validated_instance_ids=["1"],
            texts={"1": "meh"},
        )
        rows = build_validation_llm_rows(m)
        assert len(rows) == 1
        assert rows[0] == {
            'instance_id': '1', 'text': 'meh', 'llm_label': 'positive',
            'llm_confidence': 0.61,
        }
        assert 'human_label' not in rows[0]

    def test_excludes_not_yet_validated(self):
        m = _manager(
            predictions={"1": {"sentiment": _prediction(human_label=None)}},
            validation_sample_ids=["1"], validated_instance_ids=[],  # not done
        )
        assert build_validation_human_rows(m) == []
        assert build_validation_llm_rows(m) == []

    def test_excludes_instances_outside_sample(self):
        m = _manager(
            predictions={"1": {"sentiment": _prediction(human_label="x")}},
            validation_sample_ids=[],  # "1" isn't a validation instance
            validated_instance_ids=["1"],
        )
        assert build_validation_human_rows(m) == []


class TestCooperativeRows:
    """Tests for the main-annotation agreed/resolved file."""

    def test_agreed_instance(self):
        m = _manager(predictions={
            "1": {"sentiment": _prediction(
                predicted_label="positive", human_label="positive",
                agrees_with_human=True)},
        }, texts={"1": "great"})
        rows = build_cooperative_rows(m)
        assert len(rows) == 1
        assert rows[0]['outcome'] == 'agreed'
        assert rows[0]['final_label'] == 'positive'

    def test_resolved_instance(self):
        m = _manager(predictions={
            "1": {"sentiment": _prediction(
                predicted_label="wait times", human_label="access barriers",
                agrees_with_human=False, disagreement_resolved=True,
                resolution_label="access barriers")},
        })
        rows = build_cooperative_rows(m)
        assert rows[0]['outcome'] == 'resolved'
        assert rows[0]['final_label'] == 'access barriers'
        assert rows[0]['human_label'] == 'access barriers'
        assert rows[0]['llm_label'] == 'wait times'

    def test_pending_disagreement(self):
        m = _manager(predictions={
            "1": {"sentiment": _prediction(
                predicted_label="wait times", human_label="access barriers",
                agrees_with_human=False, disagreement_resolved=False)},
        })
        rows = build_cooperative_rows(m)
        assert rows[0]['outcome'] == 'pending'

    def test_excludes_validation_sample_instances(self):
        """Validation-sample instances belong in validation_*.csv, not
        cooperative.csv, even though both are (human_label, llm predicted
        label) pairs under the hood."""
        m = _manager(
            predictions={"1": {"sentiment": _prediction(
                human_label="x", agrees_with_human=True)}},
            validation_sample_ids=["1"],
        )
        assert build_cooperative_rows(m) == []

    def test_excludes_llm_only_instances(self):
        m = _manager(predictions={
            "1": {"sentiment": _prediction(human_label=None)},
        })
        assert build_cooperative_rows(m) == []


class TestBehavioralRows:
    """Tests for the interaction-summary file."""

    def _fake_behavioral_data(self, total_time_ms=5000, n_interactions=3,
                               n_changes=1, n_ai=0):
        bd = MagicMock()
        bd.total_time_ms = total_time_ms
        bd.interactions = [object()] * n_interactions
        bd.annotation_changes = [object()] * n_changes
        bd.ai_usage = [object()] * n_ai
        return bd

    def test_builds_one_row_per_user_instance(self):
        user_state = MagicMock()
        user_state.instance_id_to_behavioral_data = {
            "1": self._fake_behavioral_data(),
        }
        usm = MagicMock()
        usm.get_user_ids.return_value = ["alice"]
        usm.get_user_state.return_value = user_state

        with patch('potato.user_state_management.get_user_state_manager',
                    return_value=usm):
            rows = build_behavioral_rows(MagicMock())

        assert len(rows) == 1
        row = rows[0]
        assert row['user_id'] == 'alice'
        assert row['instance_id'] == '1'
        assert row['time_on_instance_seconds'] == 5.0
        assert row['num_interactions'] == 3
        assert row['num_annotation_changes'] == 1
        assert 'max_scroll_depth_pct' not in row

    def test_no_user_state_manager_returns_empty(self):
        with patch('potato.user_state_management.get_user_state_manager',
                    side_effect=Exception("no manager")):
            assert build_behavioral_rows(MagicMock()) == []


class TestCodebookVersionRows:
    """Tests for the codebook-version-history export — agreement rate
    and sample size per revision a relabel sweep has run against."""

    def test_empty_history_produces_no_rows(self):
        m = _manager(codebook_version_history={})
        assert build_codebook_version_rows(m) == []

    def test_one_completed_version(self):
        m = _manager(codebook_version_history={
            5: {'snapshot': [{'id': 'c1'}], 'agreement_rate': 0.8,
                'sample_size': 20, 'started_at': 100.0,
                'completed_at': 105.0},
        })
        rows = build_codebook_version_rows(m)
        assert rows == [{
            'revision': 5, 'agreement_rate': 80.0, 'sample_size': 20,
            'small_sample': '', 'started_at': 100.0, 'completed_at': 105.0,
        }]

    def test_small_sample_is_flagged(self):
        m = _manager(codebook_version_history={
            5: {'snapshot': [], 'agreement_rate': 1.0, 'sample_size': 3,
                'started_at': 100.0, 'completed_at': 101.0},
        })
        rows = build_codebook_version_rows(m)
        assert rows[0]['small_sample'] == 'yes'

    def test_incomplete_sweep_has_blank_agreement(self):
        m = _manager(codebook_version_history={
            5: {'snapshot': [], 'agreement_rate': None, 'sample_size': 0,
                'started_at': 100.0, 'completed_at': None},
        })
        rows = build_codebook_version_rows(m)
        assert rows[0]['agreement_rate'] == ''
        assert rows[0]['completed_at'] == ''

    def test_sorted_by_revision(self):
        m = _manager(codebook_version_history={
            9: {'snapshot': [], 'agreement_rate': 0.5, 'sample_size': 1,
                'started_at': 1, 'completed_at': 2},
            3: {'snapshot': [], 'agreement_rate': 0.5, 'sample_size': 1,
                'started_at': 1, 'completed_at': 2},
        })
        rows = build_codebook_version_rows(m)
        assert [r['revision'] for r in rows] == [3, 9]


class TestCodebookSnapshots:
    """Tests for the full-codebook-per-version JSON export."""

    def test_keys_snapshots_by_revision_string(self):
        m = _manager(codebook_version_history={
            5: {'snapshot': [{'id': 'c1', 'name': 'positive'}]},
        })
        data = json.loads(build_codebook_snapshots(m))
        assert data == {'5': [{'id': 'c1', 'name': 'positive'}]}

    def test_empty_history_produces_empty_object(self):
        m = _manager(codebook_version_history={})
        assert json.loads(build_codebook_snapshots(m)) == {}


class TestBuildZip:
    """Tests for the ZIP bundling — file names and that it's a valid zip."""

    def test_zip_contains_all_files(self):
        m = _manager()
        zip_bytes = build_zip(m)

        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())

        assert names == {
            'metadata_behavioral.csv', 'validation_human.csv',
            'validation_llm.csv', 'cooperative.csv',
            'codebook_versions.csv', 'codebook_snapshots.json',
        }

    def test_zip_files_have_headers_even_when_empty(self):
        m = _manager()
        with patch('potato.user_state_management.get_user_state_manager',
                    side_effect=Exception("none")):
            zip_bytes = build_zip(m)

        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            content = zf.read('cooperative.csv').decode()

        assert content.strip() == (
            'instance_id,text,human_label,llm_label,outcome,final_label')
