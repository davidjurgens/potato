"""Integration tests for the Psychometrics API (/psychometrics/*).

Boots a real server with ``psychometrics.enabled`` and
``assignment_strategy: psychometric`` so the adaptive-routing branch in
ItemStateManager runs live (cold-start fallback first, ranked assignment
once labels accumulate), then drives annotations over HTTP from users of
deliberately different quality and checks the fitted model through the API.
"""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "psychometrics_test_admin_key"

# 8 items; g1/g2/g3 will agree on all of them (the "signal"), noisy will
# disagree on half — enough structure for the model to separate abilities.
TEST_ITEMS = [
    {"id": f"p{i}", "text": f"Test message number {i}."} for i in range(1, 9)
]
GOOD_LABELS = {f"p{i}": ("Sarcastic" if i % 2 else "Sincere") for i in range(1, 9)}


class TestPsychometricsAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("psychometrics_api")
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
                "assignment_strategy": "psychometric",
                "num_annotators_per_item": 10,
                "psychometrics": {
                    "enabled": True,
                    "schema": "sarcasm",
                    "refit_interval": 1,
                    "min_observations": 12,
                    # Keep items open through seeding: the early stop excludes
                    # resolved items from assignment, and with 2 agreeing good
                    # users everything would resolve at a lower bar, starving
                    # the remaining seed users.
                    "min_annotators_per_item": 4,
                    "confidence_threshold": 0.99,
                    "cost_per_judgment": 0.05,
                },
            },
        )
        server = FlaskTestServer(port=9079, config_file=config_path)
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
        # Triggers assignment — exercises the psychometric strategy branch
        # (cold-start random fallback first, ranked once the model is warm).
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200
        return session

    def _current_instance(self, flask_server, session):
        """Instance id currently served to this user on /annotate."""
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200
        match = re.search(
            r'id="instance_id"[^>]*value="([^"]*)"', response.text
        )
        return match.group(1) if match and match.group(1) else None

    def _advance(self, flask_server, session):
        response = session.post(
            f"{flask_server.base_url}/annotate",
            data={"action": "next_instance"},
            timeout=5,
        )
        assert response.status_code == 200

    def _annotate(self, flask_server, session, instance_id, label):
        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "annotations": {f"sarcasm:{label}": "true"},
            },
            timeout=5,
        )
        assert response.status_code == 200, response.text
        assert '"error"' not in response.text, response.text

    def _annotate_all_served(self, flask_server, session, label_for):
        """Follow the server's adaptive serving order, labeling every item.

        This is the honest end-to-end flow: /updateinstance only accepts the
        currently-assigned instance, and each advance re-enters the
        psychometric assignment branch.
        """
        labeled = set()
        for _ in range(3 * len(TEST_ITEMS)):  # generous safety bound
            instance_id = self._current_instance(flask_server, session)
            if not instance_id:
                break
            if instance_id not in labeled:
                self._annotate(
                    flask_server, session, instance_id, label_for(instance_id)
                )
                labeled.add(instance_id)
            if len(labeled) == len(TEST_ITEMS):
                break
            self._advance(flask_server, session)
        return labeled

    def _admin_get(self, flask_server, path, **kwargs):
        return requests.get(
            f"{flask_server.base_url}{path}",
            headers={"X-API-Key": ADMIN_KEY},
            timeout=30,
            **kwargs,
        )

    # ------------------------------------------------------------- auth ----
    def test_01_stats_requires_admin(self, flask_server):
        response = requests.get(
            f"{flask_server.base_url}/psychometrics/api/stats", timeout=5
        )
        assert response.status_code in (401, 403)
        session = self._login(flask_server, "ps_plain")
        response = session.get(
            f"{flask_server.base_url}/psychometrics/api/stats", timeout=5
        )
        assert response.status_code == 403

    def test_02_stats_unfitted_before_annotations(self, flask_server):
        payload = self._admin_get(flask_server, "/psychometrics/api/stats").json()
        assert payload["schema"] == "sarcasm"
        assert payload["adaptive_routing"] is True
        assert payload["fitted"] is False

    # ------------------------------------------------- seed annotations ----
    def test_03_seed_annotations(self, flask_server):
        def flipped(label):
            return "Sincere" if label == "Sarcastic" else "Sarcastic"

        def noisy_label(iid):
            # Correct on p1-p4, wrong on p5-p8: 50% agreement with the group.
            return (GOOD_LABELS[iid] if int(iid[1:]) <= 4
                    else flipped(GOOD_LABELS[iid]))

        for name in ("ps_good1", "ps_good2", "ps_good3"):
            session = self._login(flask_server, name)
            labeled = self._annotate_all_served(
                flask_server, session, lambda iid: GOOD_LABELS[iid]
            )
            assert labeled == set(GOOD_LABELS), f"{name} labeled {labeled}"
        noisy = self._login(flask_server, "ps_noisy")
        labeled = self._annotate_all_served(flask_server, noisy, noisy_label)
        assert labeled == set(GOOD_LABELS)

    def test_04_stats_fitted_and_orders_abilities(self, flask_server):
        payload = self._admin_get(flask_server, "/psychometrics/api/stats").json()
        assert payload["fitted"] is True
        assert payload["n_observations"] == 32
        assert payload["n_annotators"] == 4
        thetas = {a["annotator"]: a["theta"] for a in payload["annotators"]}
        assert thetas["ps_noisy"] < min(
            thetas["ps_good1"], thetas["ps_good2"], thetas["ps_good3"]
        )
        assert len(payload["items"]) == 8
        row = payload["items"][0]
        assert row["prob_lo"] <= row["prob"] <= row["prob_hi"] + 1e-9
        assert "text" in row
        summary = payload["summary"]
        assert summary["target_annotators_per_item"] == 10
        assert summary["raw_alpha"] is not None

    def test_05_export_carries_error_bars(self, flask_server):
        payload = self._admin_get(flask_server, "/psychometrics/api/export").json()
        assert payload["fitted"] is True
        assert len(payload["items"]) == 8
        item = payload["items"][0]
        assert set(GOOD_LABELS.values()) >= {item["label"]}
        assert abs(sum(item["posterior"].values()) - 1.0) < 1e-6
        assert len(payload["annotators"]) == 4

    def test_06_new_user_gets_ranked_assignment(self, flask_server):
        # 32 observations > min_observations=12: this /annotate call takes
        # the warm adaptive path (rank_items) rather than the fallback.
        session = self._login(flask_server, "ps_fresh")
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200

    def test_07_dashboard_page(self, flask_server):
        response = self._admin_get(flask_server, "/psychometrics/dashboard")
        assert response.status_code == 200
        assert "Psychometrics" in response.text

    def test_08_design_endpoint(self, flask_server):
        response = self._admin_get(
            flask_server,
            "/psychometrics/api/design",
            params={"items": 60, "accuracy": 0.8, "classes": 2,
                    "target_ci": 0.4, "max_annotators": 3, "sims": 12},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["rows"]
        assert payload["rows"][0]["annotators_per_item"] == 2
        # cost defaults from config's cost_per_judgment
        assert payload["rows"][0]["cost"] == pytest.approx(60 * 2 * 0.05)

    def test_09_design_validation_error(self, flask_server):
        response = self._admin_get(
            flask_server,
            "/psychometrics/api/design",
            params={"items": 60, "accuracy": 5.0},
        )
        assert response.status_code == 400
        assert "error" in response.json()
