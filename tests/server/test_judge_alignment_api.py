"""
Server tests for the judge↔human alignment admin API + inline record-on-save.

Uses a set admin_api_key (non-debug) so the auth gate is exercised. The judge
LLM is never called: we fabricate a persisted judge prediction directly, which
is exactly what the admin batch would have written.
"""

import json
import os
import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

PORT = 9669
ADMIN_KEY = "judge-test-key-123"

SCHEMES = [{"annotation_type": "radio", "name": "correctness",
            "description": "Correct?", "labels": ["correct", "incorrect"]}]

EXTRA = {
    "admin_api_key": ADMIN_KEY,
    "ai_support": {"enabled": True, "endpoint_type": "ollama",
                   "ai_config": {"model": "llama3.2"}},
    "judge_alignment": {
        "enabled": True,
        "schemas": {"correctness": {"rubric": "Be strict."}},
        "inline": {"enabled": True, "schemas": ["correctness"]},
    },
}


def _ja_dir(task_dir):
    # TestConfigManager sets output_annotation_dir = {task_dir}/output, and the
    # helper persists under {output_annotation_dir}/judge_alignment.
    return os.path.join(task_dir, "output", "judge_alignment")


def _write_prediction(task_dir, instance_id, label):
    d = _ja_dir(task_dir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "predictions.json")
    data = {}
    if os.path.exists(path):
        data = json.load(open(path))
    data.setdefault("v_test", {})[f"{instance_id}::correctness"] = {
        "instance_id": instance_id, "schema_name": "correctness",
        "predicted_label": label, "confidence": 0.9, "reasoning": "because",
        "model_name": "m", "prompt_version": "v_test", "examples_used": [],
    }
    json.dump(data, open(path, "w"))
    return path


class TestJudgeAlignmentAPI:
    @pytest.fixture(scope="class", autouse=True)
    def server(self, request):
        with TestConfigManager("judge_align_api", SCHEMES, num_instances=2,
                               additional_config=EXTRA) as cfg:
            request.cls.task_dir = cfg.task_dir
            srv = FlaskTestServer(port=PORT, config_file=cfg.config_path)
            if not srv.start():
                pytest.fail("server failed to start")
            request.cls.base = srv.base_url
            yield srv
            srv.stop()

    def test_requires_api_key(self):
        r = requests.get(f"{self.base}/admin/judge-alignment")
        assert r.status_code == 403

    def test_report_with_key(self):
        # Fabricate a judge prediction for instance "1" (correct) and have a
        # human label it "incorrect" → a recorded disagreement.
        _write_prediction(self.task_dir, "1", "correct")

        s = requests.Session()
        s.post(f"{self.base}/register", data={"email": "ju", "pass": "x", "action": "signup"})
        s.post(f"{self.base}/auth", data={"email": "ju", "pass": "x", "action": "login"})
        s.get(f"{self.base}/annotate")
        j = s.get(f"{self.base}/api/current_instance").json()
        iid = j.get("instance_id")
        _write_prediction(self.task_dir, iid, "correct")
        s.post(f"{self.base}/updateinstance",
               json={"instance_id": iid, "annotations": {"correctness:incorrect": "incorrect"}})
        time.sleep(0.3)

        r = requests.get(f"{self.base}/admin/judge-alignment",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200
        report = r.json()
        assert "per_schema" in report
        # The human-vs-judge comparison was recorded on save.
        comp_path = os.path.join(_ja_dir(self.task_dir), "comparisons.json")
        assert os.path.exists(comp_path), "comparison not recorded on save"
        comps = json.load(open(comp_path))
        assert any(c["instance_id"] == iid and c["schema"] == "correctness" for c in comps)

    def test_html_report_renders(self):
        r = requests.get(f"{self.base}/admin/judge-alignment?format=html",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200
        assert "Judge" in r.text and "Alignment" in r.text

    def test_run_endpoint_requires_key(self):
        r = requests.post(f"{self.base}/admin/api/judge-alignment/run")
        assert r.status_code == 403

    def test_run_endpoint_returns_summary(self):
        # No live ollama in CI → judged may be 0/failed>0, but the endpoint must
        # respond with the summary shape, not error.
        r = requests.post(f"{self.base}/admin/api/judge-alignment/run",
                          headers={"X-API-Key": ADMIN_KEY},
                          json={"max_per_schema": 1})
        assert r.status_code == 200
        body = r.json()
        assert "judged" in body and "failed" in body
