"""Integration tests for the Truth Serum API (/truth_serum/*)."""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "truth_serum_test_admin_key"

TEST_ITEMS = [
    {"id": "t1", "text": "Oh great, another Monday."},
    {"id": "t2", "text": "The conference wifi actually worked this year."},
]


class TestTruthSerumAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("truth_serum_api")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "sarcasm",
            "description": "Sarcastic or sincere?",
            "labels": ["Sarcastic", "Sincere"],
        }]
        config_path = create_test_config(
            test_dir,
            annotation_schemes,
            admin_api_key=ADMIN_KEY,
            additional_config={
                "truth_serum": {
                    "enabled": True,
                    "schema": "sarcasm",
                    "min_annotators": 2,
                },
            },
        )
        server = FlaskTestServer(port=9078, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    def _login(self, flask_server, name):
        session = requests.Session()
        user = {"email": name, "pass": "pass"}
        session.post(f"{flask_server.base_url}/register", data=user, timeout=5)
        response = session.post(f"{flask_server.base_url}/auth", data=user, timeout=5)
        assert response.status_code in (200, 302)
        session.headers.update({"Origin": flask_server.base_url})
        return session

    @pytest.fixture()
    def alice(self, flask_server):
        return self._login(flask_server, "ts_alice")

    def _predict(self, flask_server, session, instance_id="t1",
                 label="Sarcastic", pct=80):
        return session.post(
            f"{flask_server.base_url}/truth_serum/api/predict",
            json={"instance_id": instance_id, "label": label, "predicted_pct": pct},
            timeout=5,
        )

    # ------------------------------------------------------------- auth ----
    def test_predict_requires_login(self, flask_server):
        response = requests.post(
            f"{flask_server.base_url}/truth_serum/api/predict",
            json={"instance_id": "t1", "label": "Sarcastic", "predicted_pct": 80},
            timeout=5,
        )
        assert response.status_code == 401

    def test_stats_requires_admin(self, flask_server, alice):
        response = alice.get(f"{flask_server.base_url}/truth_serum/api/stats", timeout=5)
        assert response.status_code == 403

    def test_cross_origin_rejected(self, flask_server, alice):
        response = alice.post(
            f"{flask_server.base_url}/truth_serum/api/predict",
            json={"instance_id": "t1", "label": "Sarcastic", "predicted_pct": 80},
            headers={"Origin": "https://evil.example.com"},
            timeout=5,
        )
        assert response.status_code == 403

    # ------------------------------------------------------------ predict ----
    def test_predict_and_restore(self, flask_server, alice):
        response = self._predict(flask_server, alice, pct=75)
        assert response.status_code == 200
        assert response.json()["success"] is True

        mine = alice.get(
            f"{flask_server.base_url}/truth_serum/api/mine",
            params={"instance_id": "t1"}, timeout=5,
        ).json()
        assert mine["prediction"]["label"] == "Sarcastic"
        assert mine["prediction"]["predicted_pct"] == 75.0

    def test_predict_unknown_label_400(self, flask_server, alice):
        response = self._predict(flask_server, alice, label="Ironic")
        assert response.status_code == 400

    def test_predict_unknown_instance_404(self, flask_server, alice):
        response = self._predict(flask_server, alice, instance_id="nope")
        assert response.status_code == 404

    def test_predict_out_of_range_400(self, flask_server, alice):
        response = self._predict(flask_server, alice, pct=150)
        assert response.status_code == 400

    # ----------------------------------------------------------- verdicts ----
    def test_stats_computes_sp_verdict(self, flask_server, alice):
        # Three annotators on t2: majority Sincere overconfident, minority
        # Sarcastic well-calibrated -> SP should flag the item.
        self._predict(flask_server, alice, instance_id="t2",
                      label="Sincere", pct=95)
        bob = self._login(flask_server, "ts_bob")
        self._predict(flask_server, bob, instance_id="t2",
                      label="Sincere", pct=90)
        carol = self._login(flask_server, "ts_carol")
        self._predict(flask_server, carol, instance_id="t2",
                      label="Sarcastic", pct=20)

        stats = requests.get(
            f"{flask_server.base_url}/truth_serum/api/stats",
            headers={"X-API-Key": ADMIN_KEY}, timeout=5,
        ).json()
        item = next(i for i in stats["items"] if i["instance_id"] == "t2")
        assert item["majority_label"] == "Sincere"
        assert item["sp_label"] == "Sarcastic"
        assert item["disagrees"] is True
        assert item["text"].startswith("The conference wifi")
        assert "ts_carol" in stats["annotators"]

    def test_export_with_admin_key(self, flask_server):
        response = requests.get(
            f"{flask_server.base_url}/truth_serum/api/export",
            headers={"X-API-Key": ADMIN_KEY}, timeout=5,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema"] == "sarcasm"
        assert len(payload["predictions"]) >= 1

    def test_dashboard_page_with_admin_key(self, flask_server):
        response = requests.get(
            f"{flask_server.base_url}/truth_serum/dashboard",
            headers={"X-API-Key": ADMIN_KEY}, timeout=5,
        )
        assert response.status_code == 200
        assert "Truth Serum" in response.text
