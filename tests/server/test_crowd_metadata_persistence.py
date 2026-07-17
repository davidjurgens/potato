"""
Integration tests for Tier-2 crowdsourcing parity:

- STUDY_ID/SESSION_ID are persisted into the annotation output
  (user_state.json crowd_metadata) so results can be joined with the
  platform's submission records.
- A returning participant (fresh browser, same PROLIFIC_PID) resumes with
  their assignments and annotations intact.
- The done page flushes state server-side before offering the redirect.
"""

import json
import os
import time

import pytest
import requests

from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
from tests.server.test_prolific_server_integration import (
    SimpleTestServer,
    create_prolific_test_config,
)


class TestCrowdMetadataPersistence:
    @pytest.fixture
    def prolific_server(self, request):
        port = find_free_port(preferred_port=9800)
        test_dir = create_test_directory(f"crowd_metadata_test_{port}")
        config_file = create_prolific_test_config(
            test_dir, port, completion_code="METADATA-CODE-1")

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def _arrive(self, server, session, pid, **params):
        query = {"PROLIFIC_PID": pid}
        query.update(params)
        response = session.get(
            f"{server.base_url}/", params=query, allow_redirects=True, timeout=5)
        assert response.status_code == 200
        return response

    def _annotate(self, server, session, item_id):
        response = session.post(
            f"{server.base_url}/updateinstance",
            json={
                "instance_id": item_id,
                "annotations": {"sentiment:positive": "true"},
                "span_annotations": [],
            },
            timeout=5,
        )
        assert response.status_code == 200
        response = session.post(
            f"{server.base_url}/annotate",
            json={"action": "next_instance", "instance_id": item_id},
            allow_redirects=True,
            timeout=5,
        )
        assert response.status_code == 200

    def _read_user_state(self, test_dir, username):
        state_file = os.path.join(test_dir, "output", username, "user_state.json")
        assert os.path.exists(state_file), f"user_state.json missing for {username}"
        with open(state_file) as f:
            return json.load(f)

    def test_study_and_session_ids_persisted_in_output(self, prolific_server):
        server, test_dir = prolific_server
        session = requests.Session()

        self._arrive(server, session, "metadata_worker",
                     SESSION_ID="sess_meta_1", STUDY_ID="study_meta_9")
        self._annotate(server, session, "item_1")
        self._annotate(server, session, "item_2")
        session.get(f"{server.base_url}/done", allow_redirects=True, timeout=5)

        state = self._read_user_state(test_dir, "metadata_worker")
        metadata = state.get("crowd_metadata", {})
        assert metadata.get("worker_id") == "metadata_worker"
        assert metadata.get("session_id") == "sess_meta_1"
        assert metadata.get("study_id") == "study_meta_9"
        assert metadata.get("provider") == "url_direct"

    def test_returning_participant_resumes(self, prolific_server):
        """Fresh browser + same PROLIFIC_PID must resume, not restart."""
        server, test_dir = prolific_server

        first_browser = requests.Session()
        self._arrive(server, first_browser, "resume_worker", SESSION_ID="s1")
        self._annotate(server, first_browser, "item_1")

        # Simulate a closed browser: brand-new cookie jar, same PID
        second_browser = requests.Session()
        response = self._arrive(server, second_browser, "resume_worker", SESSION_ID="s1")
        assert "sentiment" in response.text.lower()

        state = self._read_user_state(test_dir, "resume_worker")
        assert state["instance_id_to_label_to_value"].get("item_1"), \
            "annotation from the first session should survive the return"
        assert set(state["instance_id_ordering"]) == {"item_1", "item_2"}, \
            "assignments should be unchanged after returning"

    def test_done_page_flushes_state_before_redirect(self, prolific_server):
        server, test_dir = prolific_server
        session = requests.Session()

        self._arrive(server, session, "flush_worker", SESSION_ID="s2")
        self._annotate(server, session, "item_1")
        self._annotate(server, session, "item_2")

        response = session.get(f"{server.base_url}/done", allow_redirects=True, timeout=5)
        assert response.status_code == 200
        assert "METADATA-CODE-1" in response.text

        # State on disk must already include everything at render time
        state = self._read_user_state(test_dir, "flush_worker")
        assert len(state["instance_id_to_label_to_value"]) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
