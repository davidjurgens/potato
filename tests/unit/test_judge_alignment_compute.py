"""
Unit tests for judge↔human alignment computation + persistence
(potato/server_utils/judge_alignment.py).
"""

import json
import os

import pytest

from potato.server_utils import judge_alignment as ja


# ----- pure compute core --------------------------------------------------

class TestComputeFromPairs:
    def test_kappa_matches_agreement_module(self):
        import pandas as pd
        from potato.agreement import cohen_kappa_pairwise
        pairs = [(f"i{i}", "pass", "pass", 0.9, "") for i in range(7)]
        pairs += [("a", "fail", "fail", 0.9, ""), ("b", "fail", "pass", 0.5, ""),
                  ("c", "pass", "fail", 0.5, "")]
        res = ja.compute_alignment_from_pairs({"v": pairs})["v"]
        rows = []
        for inst, h, j, *_ in pairs:
            rows.append({"unit": inst, "annotator": "human", "annotation": h})
            rows.append({"unit": inst, "annotator": "judge", "annotation": j})
        direct = cohen_kappa_pairwise(pd.DataFrame(rows))["mean_kappa"]
        assert res["kappa"] == round(direct, 3)
        assert res["n"] == len(pairs)

    def test_agreement_rate_and_confusion_and_disagreements(self):
        pairs = [("i1", "pass", "pass", 0.9, "ok"),
                 ("i2", "fail", "pass", 0.4, "judge too lenient")]
        res = ja.compute_alignment_from_pairs({"v": pairs})["v"]
        assert res["agreement_rate"] == 0.5
        assert res["confusion"]["fail"]["pass"] == 1
        assert res["confusion"]["pass"]["pass"] == 1
        assert len(res["disagreements"]) == 1
        d = res["disagreements"][0]
        assert d["instance_id"] == "i2" and d["human_label"] == "fail" and d["judge_label"] == "pass"
        assert d["judge_confidence"] == 0.4 and d["reasoning"] == "judge too lenient"

    def test_no_overlap(self):
        res = ja.compute_alignment_from_pairs({"v": []})["v"]
        assert res["kappa"] is None and res["n"] == 0 and res["interpretation"] == "no overlap"

    def test_drops_pairs_with_missing_side(self):
        pairs = [("i1", "pass", None, None, ""), ("i2", None, "pass", None, ""),
                 ("i3", "pass", "pass", 0.9, "")]
        res = ja.compute_alignment_from_pairs({"v": pairs})["v"]
        assert res["n"] == 1


# ----- persistence --------------------------------------------------------

class TestPersistence:
    def _cfg(self, tmp_path):
        return {"task_dir": str(tmp_path), "output_annotation_dir": str(tmp_path)}

    def test_save_and_load_prediction(self, tmp_path):
        from potato.ai.judge import JudgePrediction
        cfg = self._cfg(tmp_path)
        ja.save_prediction(cfg, JudgePrediction("i1", "verdict", "pass", 0.9, "r", "m", "v_a"))
        ja.save_prediction(cfg, JudgePrediction("i2", "verdict", "fail", 0.8, "r", "m", "v_a"))
        data = ja.load_predictions(cfg)
        assert "v_a" in data
        assert data["v_a"]["i1::verdict"]["predicted_label"] == "pass"
        assert ja.latest_prompt_version(cfg) == "v_a"

    def test_record_comparison_and_running(self, tmp_path):
        cfg = self._cfg(tmp_path)
        ja.record_comparison(cfg, "i1", "verdict", "pass", "pass", "v_a")
        ja.record_comparison(cfg, "i2", "verdict", "fail", "pass", "v_a")
        run = ja.running_agreement(cfg, "verdict")
        assert run["n"] == 2 and run["agreements"] == 1 and run["agreement_rate"] == 0.5


# ----- gather + full report (human labels mocked) -------------------------

class TestGatherAndReport:
    def _cfg(self, tmp_path):
        return {
            "task_dir": str(tmp_path),
            "output_annotation_dir": str(tmp_path),
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "verdict",
                 "labels": [{"name": "pass"}, {"name": "fail"}]},
            ],
            "judge_alignment": {"schemas": {"verdict": {"rubric": "x"}}},
        }

    def test_compute_judge_alignment_pairs_humans_with_judge(self, tmp_path, monkeypatch):
        from potato.ai.judge import JudgePrediction
        cfg = self._cfg(tmp_path)
        # Judge predictions
        ja.save_prediction(cfg, JudgePrediction("i1", "verdict", "pass", 0.9, "", "m", "v_a"))
        ja.save_prediction(cfg, JudgePrediction("i2", "verdict", "pass", 0.9, "", "m", "v_a"))
        # Human gold (mock majority_human_label): i1 agrees, i2 disagrees
        gold = {"i1": "pass", "i2": "fail"}
        monkeypatch.setattr(ja, "majority_human_label",
                            lambda iid, schema, users: gold.get(iid))
        report = ja.compute_judge_alignment(cfg, users=["u1"], prompt_version="v_a")
        r = report["per_schema"]["verdict"]
        assert r["n"] == 2
        assert r["agreement_rate"] == 0.5
        assert any(v["prompt_version"] == "v_a" for v in report["prompt_versions"])

    def test_scoped_schemas_filters_to_allowlist_and_categorical(self, tmp_path):
        cfg = self._cfg(tmp_path)
        cfg["annotation_schemes"].append(
            {"annotation_type": "text", "name": "notes"})  # non-categorical, excluded
        cfg["annotation_schemes"].append(
            {"annotation_type": "radio", "name": "other", "labels": ["x"]})  # not in allowlist
        names = [s["name"] for s in ja.judge_scoped_schemas(cfg)]
        assert names == ["verdict"]
