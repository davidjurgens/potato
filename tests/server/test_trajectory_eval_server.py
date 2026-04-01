"""Server integration tests for the trajectory_eval schema."""

import json
import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestTrajectoryEvalServer:
    """Test trajectory_eval with a running Flask server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        annotation_schemes = [
            {
                "annotation_type": "trajectory_eval",
                "name": "step_evaluation",
                "description": "Evaluate each agent step",
                "steps_key": "steps",
                "step_text_key": "action",
                "error_types": [
                    {"name": "reasoning", "subtypes": ["logical_error"]},
                    {"name": "execution"},
                ],
                "severities": [
                    {"name": "minor", "weight": -1},
                    {"name": "major", "weight": -5},
                ],
                "show_score": True,
            }
        ]

        # Create test data with steps
        import os
        from tests.helpers.test_utils import create_test_directory, create_test_config

        test_dir = create_test_directory("trajectory_eval_server")
        data_file = os.path.join(test_dir, "data.jsonl")

        items = [
            {
                "id": "trace_001",
                "text": "Find the weather",
                "steps": [
                    {"action": "search_web('weather')"},
                    {"action": "click_result(0)"},
                ],
            },
            {
                "id": "trace_002",
                "text": "Book a flight",
                "steps": [
                    {"action": "navigate('flights.com')"},
                    {"action": "fill_form(from='NYC')"},
                    {"action": "click_button('Search')"},
                ],
            },
        ]
        with open(data_file, "w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        config_file = create_test_config(
            test_dir,
            annotation_schemes=annotation_schemes,
            data_file=data_file,
            annotation_task_name="Trajectory Eval Test",
        )

        server = FlaskTestServer(port=0, config_file=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        yield server
        server.stop()

    def _login(self):
        session = requests.Session()
        session.post(
            f"{self.server.base_url}/register",
            data={"email": "traj_tester", "pass": "pass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": "traj_tester", "pass": "pass"},
        )
        return session

    def test_annotation_page_loads(self):
        session = self._login()
        resp = session.get(f"{self.server.base_url}/annotate")
        assert resp.status_code == 200
        assert "trajectory-eval-container" in resp.text

    def test_save_and_retrieve_trajectory_annotation(self):
        session = self._login()

        annotation_data = json.dumps({
            "steps": [
                {"step_index": 0, "correctness": "correct"},
                {
                    "step_index": 1,
                    "correctness": "incorrect",
                    "error_type": "reasoning",
                    "error_subtype": "logical_error",
                    "severity": "major",
                    "rationale": "Wrong selector used",
                },
            ],
            "score": 95,
        })

        # Save annotation
        resp = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "trace_001",
                "annotations": {
                    "step_evaluation": {"step_evaluation": annotation_data}
                },
            },
        )
        assert resp.status_code == 200

        # Retrieve
        resp = session.get(
            f"{self.server.base_url}/get_annotations",
            params={"instance_id": "trace_001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "step_evaluation" in str(data)

    def test_schema_html_has_step_containers(self):
        session = self._login()
        resp = session.get(f"{self.server.base_url}/annotate")
        assert "traj-steps-container" in resp.text
        assert "trajectory-eval-data-input" in resp.text
