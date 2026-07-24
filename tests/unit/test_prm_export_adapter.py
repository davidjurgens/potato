"""Unit tests for the PRM export helpers (source/verified passthrough + step-agreement adapter)."""

import json

from potato.export.coding_eval_exporter import _prm_step_record, prm_blob_to_step_labels


class TestPrmStepRecord:
    def test_passes_through_ai_metadata(self):
        rec = _prm_step_record(
            {"index": 2, "reward": -1, "source": "ai", "verified": True, "confidence": 0.8}, 0)
        assert rec == {"index": 2, "reward": -1, "source": "ai",
                       "verified": True, "confidence": 0.8}

    def test_legacy_step_minimal(self):
        assert _prm_step_record({"index": 0, "reward": 1}, 0) == {"index": 0, "reward": 1}

    def test_non_dict_step(self):
        assert _prm_step_record("junk", 3) == {"index": 3, "reward": 0}

    def test_drops_none_metadata(self):
        rec = _prm_step_record({"index": 0, "reward": 1, "confidence": None}, 0)
        assert "confidence" not in rec


class TestStepAgreementAdapter:
    def test_maps_blob_to_step_labels(self):
        blob = json.dumps({"steps": [{"index": 0, "reward": 1}, {"index": 1, "reward": -1}]})
        assert prm_blob_to_step_labels(blob) == {0: 1, 1: -1}

    def test_accepts_dict_input(self):
        d = {"steps": [{"index": 0, "reward": 0}]}
        assert prm_blob_to_step_labels(d) == {0: 0}

    def test_skips_none_rewards(self):
        blob = json.dumps({"steps": [{"index": 0, "reward": None}, {"index": 1, "reward": 1}]})
        assert prm_blob_to_step_labels(blob) == {1: 1}

    def test_unparseable_returns_empty(self):
        assert prm_blob_to_step_labels("not json") == {}
        assert prm_blob_to_step_labels(None) == {}
        assert prm_blob_to_step_labels({"nope": 1}) == {}
