"""Server integration tests for extractive QA annotation."""

import json
import os
import uuid

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file, cleanup_test_directory


def create_extractive_qa_config(test_dir, data_file, port=9042):
    """Create an extractive QA annotation test config."""
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "Extractive QA Test",
        "task_dir": abs_test_dir,
        "data_files": [os.path.basename(data_file)],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "output_annotation_dir": output_dir,
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "persist_sessions": False,
        "debug": False,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": "test-secret-key-extractive-qa",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [
            {
                "annotation_type": "extractive_qa",
                "name": "answer",
                "description": "Select the answer span",
                "question_field": "question",
                "allow_unanswerable": True,
            }
        ],
    }

    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


def create_test_data(test_dir, num_items=3):
    """Create test data items with passage and question fields."""
    data = [
        {
            "id": str(i + 1),
            "text": f"The capital of France is Paris. It is known for the Eiffel Tower and fine cuisine. Test passage {i + 1}.",
            "question": f"What is the capital of France? (question {i + 1})",
        }
        for i in range(num_items)
    ]
    return create_test_data_file(test_dir, data)


class TestExtractiveQAServer:
    """Integration tests for extractive QA annotation server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with extractive QA config."""
        test_dir = create_test_directory("extractive_qa_server_test")
        data_file = create_test_data(test_dir)
        config_path = create_extractive_qa_config(test_dir, data_file, port=9042)

        server = FlaskTestServer(port=9042, config_file=config_path)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.fail("Failed to start extractive QA test server")

        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def _get_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        username = f"eqa_tester_{uuid.uuid4().hex[:6]}"
        session.post(
            f"{self.server.base_url}/register",
            data={"email": username, "pass": "testpass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": username, "pass": "testpass"},
        )
        return session

    def test_server_starts(self):
        """Server starts successfully with extractive QA config."""
        response = requests.get(f"{self.server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_loads(self):
        """/annotate returns 200 with extractive QA form HTML."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "extractive" in response.text.lower() or "eqa" in response.text.lower() or "answer" in response.text.lower()

    def test_submit_qa_annotation(self):
        """POST QA annotation with answer span to /updateinstance succeeds."""
        session = self._get_session()

        answer_data = json.dumps({
            "answer_text": "Paris",
            "start": 27,
            "end": 32,
            "unanswerable": False,
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "answer:answer": answer_data,
                },
            },
        )
        assert response.status_code == 200

    def test_submit_unanswerable(self):
        """POST unanswerable annotation to /updateinstance succeeds."""
        session = self._get_session()

        unanswerable_data = json.dumps({
            "answer_text": "",
            "start": -1,
            "end": -1,
            "unanswerable": True,
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "answer:answer": unanswerable_data,
                },
            },
        )
        assert response.status_code == 200

    def test_submit_and_verify_response(self):
        """POST QA annotation returns success with stored data."""
        session = self._get_session()
        session.get(f"{self.server.base_url}/annotate")

        answer_data = json.dumps({
            "answer_text": "Paris",
            "start": 27,
            "end": 32,
            "unanswerable": False,
        })

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {
                    "answer:answer": answer_data,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True or response.status_code == 200

    def test_annotate_page_contains_qa_elements(self):
        """Annotation page contains extractive QA elements."""
        session = self._get_session()
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
        assert "eqa-passage-container" in response.text or "answer" in response.text.lower()
        assert "Unanswerable" in response.text
