"""Integration tests for the Boundary Lab API (/boundary/*)."""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "boundary_test_admin_key"

TEST_ITEMS = [
    {
        "id": "b1",
        "text": "Please send me the report when you get a chance.",
        "counterfactuals": [
            {"text": "Send me the report when you get a chance.",
             "kind": "flip", "edit_hint": "removed please"},
            {"text": "Please send me the report now.",
             "kind": "flip", "edit_hint": "added urgency"},
            {"text": "When you have a moment, please send the report over.",
             "kind": "invariance", "edit_hint": "reordered"},
        ],
    },
    {
        "id": "b2",
        "text": "Fix the numbers in this spreadsheet.",
        "counterfactuals": [
            {"text": "Please fix the numbers in this spreadsheet.",
             "kind": "flip", "edit_hint": "added please"},
            {"text": "The numbers in this spreadsheet need fixing.",
             "kind": "invariance", "edit_hint": "passive rewording"},
        ],
    },
]


class TestBoundaryAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("boundary_api")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "politeness",
            "description": "How polite is this message?",
            "labels": ["Polite", "Neutral", "Impolite"],
        }]
        config_path = create_test_config(
            test_dir,
            annotation_schemes,
            admin_api_key=ADMIN_KEY,
            additional_config={
                "boundary_probing": {
                    "enabled": True,
                    "schema": "politeness",
                    "probes_per_item": 3,
                    "sources": ["precomputed", "rules"],
                },
            },
        )
        server = FlaskTestServer(port=9077, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    @pytest.fixture()
    def authed_session(self, flask_server):
        session = requests.Session()
        user = {"email": "boundary_user", "pass": "pass"}
        session.post(f"{flask_server.base_url}/register", data=user, timeout=5)
        response = session.post(f"{flask_server.base_url}/auth", data=user, timeout=5)
        assert response.status_code in (200, 302)
        # Same-origin headers for the CSRF check on POST endpoints
        session.headers.update({"Origin": flask_server.base_url})
        return session

    def _probe(self, flask_server, session, instance_id="b1", label="Polite"):
        return session.post(
            f"{flask_server.base_url}/boundary/api/probe",
            json={"instance_id": instance_id, "schema": "politeness", "label": label},
            timeout=10,
        )

    # ------------------------------------------------------------- auth ----
    def test_probe_requires_login(self, flask_server):
        response = requests.post(
            f"{flask_server.base_url}/boundary/api/probe",
            json={"instance_id": "b1", "schema": "politeness", "label": "Polite"},
            timeout=5,
        )
        assert response.status_code == 401

    def test_respond_requires_login(self, flask_server):
        response = requests.post(
            f"{flask_server.base_url}/boundary/api/respond",
            json={"probe_id": "x", "verdict": "holds"},
            timeout=5,
        )
        assert response.status_code == 401

    def test_stats_requires_admin(self, flask_server, authed_session):
        response = authed_session.get(
            f"{flask_server.base_url}/boundary/api/stats", timeout=5)
        assert response.status_code == 403

    def test_cross_origin_post_rejected(self, flask_server, authed_session):
        response = authed_session.post(
            f"{flask_server.base_url}/boundary/api/probe",
            json={"instance_id": "b1", "schema": "politeness", "label": "Polite"},
            headers={"Origin": "https://evil.example.com"},
            timeout=5,
        )
        assert response.status_code == 403

    # ------------------------------------------------------------ probes ----
    def test_probe_returns_precomputed_counterfactuals(self, flask_server, authed_session):
        response = self._probe(flask_server, authed_session)
        assert response.status_code == 200
        data = response.json()
        assert data["original_label"] == "Polite"
        assert data["labels"] == ["Polite", "Neutral", "Impolite"]
        assert len(data["probes"]) == 3
        kinds = [p["kind"] for p in data["probes"]]
        assert kinds == ["flip", "flip", "invariance"]
        assert all(p["source"] == "precomputed" for p in data["probes"])

    def test_probe_unknown_instance_404(self, flask_server, authed_session):
        response = self._probe(flask_server, authed_session, instance_id="nope")
        assert response.status_code == 404

    def test_probe_unknown_label_400(self, flask_server, authed_session):
        response = self._probe(flask_server, authed_session, label="Sarcastic")
        assert response.status_code == 400

    def test_probe_wrong_schema_400(self, flask_server, authed_session):
        response = authed_session.post(
            f"{flask_server.base_url}/boundary/api/probe",
            json={"instance_id": "b1", "schema": "other", "label": "Polite"},
            timeout=5,
        )
        assert response.status_code == 400

    # --------------------------------------------------------- responses ----
    def test_respond_roundtrip_and_restore(self, flask_server, authed_session):
        probes = self._probe(flask_server, authed_session, instance_id="b2",
                             label="Impolite").json()["probes"]
        flip_probe = next(p for p in probes if p["kind"] == "flip")

        response = authed_session.post(
            f"{flask_server.base_url}/boundary/api/respond",
            json={
                "instance_id": "b2",
                "probe_id": flip_probe["probe_id"],
                "verdict": "flips",
                "new_label": "Neutral",
                "rationale": "please softens the command",
            },
            timeout=5,
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Re-fetching probes returns the stored verdict (panel state restore)
        data = self._probe(flask_server, authed_session, instance_id="b2",
                           label="Impolite").json()
        stored = data["responses"][flip_probe["probe_id"]]
        assert stored["verdict"] == "flips"
        assert stored["new_label"] == "Neutral"

    def test_respond_flips_requires_new_label(self, flask_server, authed_session):
        probes = self._probe(flask_server, authed_session).json()["probes"]
        response = authed_session.post(
            f"{flask_server.base_url}/boundary/api/respond",
            json={"probe_id": probes[0]["probe_id"], "verdict": "flips"},
            timeout=5,
        )
        assert response.status_code == 400

    def test_respond_invalid_verdict_400(self, flask_server, authed_session):
        probes = self._probe(flask_server, authed_session).json()["probes"]
        response = authed_session.post(
            f"{flask_server.base_url}/boundary/api/respond",
            json={"probe_id": probes[0]["probe_id"], "verdict": "perhaps"},
            timeout=5,
        )
        assert response.status_code == 400

    def test_respond_unknown_probe_404(self, flask_server, authed_session):
        response = authed_session.post(
            f"{flask_server.base_url}/boundary/api/respond",
            json={"probe_id": "deadbeef", "verdict": "holds"},
            timeout=5,
        )
        assert response.status_code == 404

    # ------------------------------------------------------ admin surface ----
    def test_stats_with_admin_key(self, flask_server, authed_session):
        probes = self._probe(flask_server, authed_session).json()["probes"]
        invariance = next(p for p in probes if p["kind"] == "invariance")
        authed_session.post(
            f"{flask_server.base_url}/boundary/api/respond",
            json={"probe_id": invariance["probe_id"], "verdict": "holds"},
            timeout=5,
        )
        response = requests.get(
            f"{flask_server.base_url}/boundary/api/stats",
            headers={"X-API-Key": ADMIN_KEY},
            timeout=5,
        )
        assert response.status_code == 200
        stats = response.json()
        assert stats["totals"]["probes_answered"] >= 1
        assert "boundary_user" in stats["annotators"]

    def test_export_contrast_set_jsonl(self, flask_server):
        response = requests.get(
            f"{flask_server.base_url}/boundary/api/export",
            headers={"X-API-Key": ADMIN_KEY},
            timeout=5,
        )
        assert response.status_code == 200
        lines = [json.loads(l) for l in response.text.splitlines() if l.strip()]
        assert lines, "expected at least one contrast record from earlier tests"
        record = lines[0]
        for key in ("original_text", "counterfactual_text", "original_label",
                    "counterfactual_label", "flipped", "annotator"):
            assert key in record

    def test_dashboard_page_with_admin_key(self, flask_server):
        response = requests.get(
            f"{flask_server.base_url}/boundary/dashboard",
            headers={"X-API-Key": ADMIN_KEY},
            timeout=5,
        )
        assert response.status_code == 200
        assert "Boundary Lab" in response.text
