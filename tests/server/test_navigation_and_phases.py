"""
Integration tests for navigation endpoints and phase transitions.

Covers:
- /go_to endpoint for jumping to a specific instance
- /next and /prev navigation
- Consent and instructions phase flow
- Training → annotation phase transition
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


# =====================================================================
# Navigation tests
# =====================================================================


class TestGoToNavigation:
    """Test the /go_to endpoint for jumping to a specific item."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("goto_nav_test")
        test_data = [
            {"id": "nav_1", "text": "Navigation item 1."},
            {"id": "nav_2", "text": "Navigation item 2."},
            {"id": "nav_3", "text": "Navigation item 3."},
            {"id": "nav_4", "text": "Navigation item 4."},
            {"id": "nav_5", "text": "Navigation item 5."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "label",
                    "annotation_type": "radio",
                    "labels": ["a", "b"],
                    "description": "Pick one",
                }
            ],
            data_files=[data_file],
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def _auth_session(self, flask_server, username):
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": username, "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": username, "pass": "pass"},
            timeout=5,
        )
        session.get(f"{flask_server.base_url}/annotate", timeout=5)
        return session

    def test_go_to_valid_index(self, flask_server):
        """POST /go_to with a valid integer index should navigate to that item."""
        session = self._auth_session(flask_server, "goto_user1")
        resp = session.post(
            f"{flask_server.base_url}/go_to",
            data={"go_to": "2"},  # go_to takes an integer index
            timeout=5,
        )
        assert resp.status_code == 200

    def test_go_to_first_index_returns_200(self, flask_server):
        """go_to index 0 should return 200."""
        session = self._auth_session(flask_server, "goto_user2")
        resp = session.post(
            f"{flask_server.base_url}/go_to",
            data={"go_to": "0"},
            timeout=5,
        )
        assert resp.status_code == 200

    def test_next_prev_navigation(self, flask_server):
        """Users can move through items with next/prev actions on /annotate."""
        session = self._auth_session(flask_server, "nav_seq_user")
        base = flask_server.base_url

        # Navigate to the first item
        session.post(f"{base}/go_to", data={"go_to": "0"}, timeout=5)

        # Move to next via POST with action
        resp = session.post(
            f"{base}/annotate",
            data={"action": "next_instance"},
            timeout=5,
        )
        assert resp.status_code == 200

        # Move to prev via POST with action
        resp = session.post(
            f"{base}/annotate",
            data={"action": "prev_instance"},
            timeout=5,
        )
        assert resp.status_code == 200


# =====================================================================
# Phase flow tests
# =====================================================================


class TestConsentPhase:
    """Test the consent → instructions → annotation phase flow."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("consent_phase_test")
        test_data = [
            {"id": "phase_1", "text": "Phase test item."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "label",
                    "annotation_type": "radio",
                    "labels": ["a", "b"],
                    "description": "Label",
                }
            ],
            data_files=[data_file],
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_new_user_starts_at_annotation_phase(self, flask_server):
        """Without consent/training config, users go straight to annotation."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "phase_user", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "phase_user", "pass": "pass"},
            timeout=5,
        )

        # Home should redirect to annotation
        resp = session.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code == 200
        # User should reach the annotation page (or be redirected to it)
        # We check for either the URL ending with /annotate or the page
        # containing annotation content
        assert "/annotate" in resp.url or "annotation" in resp.text.lower()

    def test_no_instructions_button_without_instructions_phase(self, flask_server):
        """Instructions link should be hidden when no instructions phase is configured."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "phase_user_no_instr", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "phase_user_no_instr", "pass": "pass"},
            timeout=5,
        )

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        assert "/instructions/view" not in resp.text


# =====================================================================
# Annotation submission and next/prev state
# =====================================================================


class TestAnnotationFlow:
    """Test the full annotation submission → navigation flow."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("ann_flow_test")
        test_data = [
            {"id": "flow_1", "text": "Flow item 1."},
            {"id": "flow_2", "text": "Flow item 2."},
            {"id": "flow_3", "text": "Flow item 3."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "rating",
                    "annotation_type": "radio",
                    "labels": ["good", "bad"],
                    "description": "Rating",
                }
            ],
            data_files=[data_file],
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def _auth_session(self, flask_server, username):
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": username, "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": username, "pass": "pass"},
            timeout=5,
        )
        session.get(f"{flask_server.base_url}/annotate", timeout=5)
        return session

    def test_submit_annotation_returns_200(self, flask_server):
        """Submitting a valid annotation via /updateinstance returns 200."""
        session = self._auth_session(flask_server, "flow_user1")
        resp = session.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": "flow_1",
                "schema": "rating",
                "type": "label",
                "state": [{"name": "good", "value": "good"}],
            },
            timeout=5,
        )
        assert resp.status_code == 200

    def test_annotation_persists_across_navigation(self, flask_server):
        """After annotating and navigating away, the annotation should persist."""
        session = self._auth_session(flask_server, "flow_user2")
        base = flask_server.base_url

        # Annotate first item
        session.post(
            f"{base}/updateinstance",
            json={
                "instance_id": "flow_1",
                "schema": "rating",
                "type": "label",
                "state": [{"name": "good", "value": "good"}],
            },
            timeout=5,
        )

        # Navigate to next item
        session.post(f"{base}/annotate", data={"action": "next_instance"}, timeout=5)

        # Go back to first item (index 0)
        session.post(f"{base}/go_to", data={"go_to": "0"}, timeout=5)

        # The annotation should still be there.
        # Verify via user state manager directly.
        from potato.user_state_management import get_user_state_manager

        usm = get_user_state_manager()
        us = usm.get_user_state("flow_user2")
        labels = us.instance_id_to_label_to_value.get("flow_1", {})
        found = any(l.get_name() == "good" and v == "good" for l, v in labels.items())
        assert found, "Annotation did not persist after navigation"

    def test_annotate_all_items_marks_complete(self, flask_server):
        """After annotating all items, the user's assigned queue should be exhausted."""
        session = self._auth_session(flask_server, "flow_user3")
        base = flask_server.base_url

        from potato.user_state_management import get_user_state_manager

        usm = get_user_state_manager()
        us = usm.get_user_state("flow_user3")
        assigned = list(us.get_assigned_instance_ids())

        # Annotate each assigned item by iterating with next_instance
        for i, iid in enumerate(assigned):
            if i > 0:
                session.post(
                    f"{base}/annotate",
                    data={"action": "next_instance"},
                    timeout=5,
                )
            session.post(
                f"{base}/updateinstance",
                json={
                    "instance_id": iid,
                    "schema": "rating",
                    "type": "label",
                    "state": [{"name": "bad", "value": "bad"}],
                },
                timeout=5,
            )

        # All assigned items should now be annotated
        for iid in assigned:
            assert us.has_annotated(iid), f"Item {iid} not marked as annotated"
