"""
Back-navigation and phase-flow regression tests.

These tests cover gaps discovered during the post-mortem of PR #147
("Fix annotation-page back-navigation crash"). The original bug only
reproduced when `user_state.has_annotated(instance_id)` was True — i.e.
when a user navigated BACK to an instance they had already annotated.
Existing back-nav tests navigated back to an UNannotated instance, so
they missed it.

Tests in this file:
- TestBackNavToAnnotatedInstance: the direct regression coverage.
- TestMultipleBackForwardCycles: stress test back/forward navigation.
- TestPhaseRetreatAllowed: back-nav across phase boundaries with
  `allow_phase_back_navigation: True`.
- TestPhaseRetreatBlocked: same but with the flag off — must NOT retreat.
"""

import json
from pathlib import Path

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)


def _auth_session(base_url: str, username: str) -> requests.Session:
    session = requests.Session()
    session.post(
        f"{base_url}/register",
        data={"action": "signup", "email": username, "pass": "pass"},
        timeout=5,
    )
    session.post(
        f"{base_url}/auth",
        data={"action": "login", "email": username, "pass": "pass"},
        timeout=5,
    )
    # Touch /annotate so user state is initialized
    session.get(f"{base_url}/annotate", timeout=5)
    return session


def _submit_rating(session, base_url, instance_id, value="good"):
    """Submit a radio annotation via /updateinstance (the real-time save endpoint)."""
    resp = session.post(
        f"{base_url}/updateinstance",
        json={
            "instance_id": instance_id,
            "schema": "rating",
            "type": "label",
            "state": [{"name": value, "value": value}],
        },
        timeout=5,
    )
    assert resp.status_code == 200, f"updateinstance failed: {resp.status_code} {resp.text}"
    return resp


def _post_action(session, base_url, action):
    """POST an action (next_instance / prev_instance) to /annotate."""
    return session.post(
        f"{base_url}/annotate",
        data={"action": action},
        timeout=5,
    )


# =====================================================================
# TestBackNavToAnnotatedInstance — PR #147 regression at server level
# =====================================================================


class TestBackNavToAnnotatedInstance:
    """Navigate back to an instance that has already been annotated.

    The critical path: the render branch where
    `user_state.has_annotated(instance_id)` is True executes the
    required-annotation check. Prior to PR #147 this branch did a
    request-time `from potato.routes import ...` that could fail after
    Flask's route lockdown. We need a server-level test that actually
    exercises this branch.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("back_nav_annotated_test")
        test_data = [
            {"id": "bn_1", "text": "First item."},
            {"id": "bn_2", "text": "Second item."},
            {"id": "bn_3", "text": "Third item."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "rating",
                    "annotation_type": "radio",
                    "labels": ["good", "bad"],
                    "description": "Rate the item.",
                }
            ],
            data_files=[data_file],
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_back_nav_to_annotated_instance_returns_200(self, flask_server):
        """
        Core PR #147 regression: annotate instance 0, advance to instance 1,
        navigate back to instance 0, assert render succeeds (200).

        Before the fix, this would crash because `render_page_with_annotations`
        lazily imported `potato.routes` from inside a request handler.
        """
        session = _auth_session(flask_server.base_url, "back_nav_user_1")

        _submit_rating(session, flask_server.base_url, "bn_1", "good")
        resp_next = _post_action(session, flask_server.base_url, "next_instance")
        assert resp_next.status_code == 200, "next_instance failed"

        resp_prev = _post_action(session, flask_server.base_url, "prev_instance")
        assert resp_prev.status_code == 200, (
            f"prev_instance to annotated instance failed: {resp_prev.status_code}"
        )
        assert "bn_1" in resp_prev.text, (
            "Expected back-navigated page to render instance bn_1"
        )

    def test_back_nav_hits_annotated_render_branch(self, flask_server):
        """
        Prove the test actually exercises the `if has_annotated` branch in
        `render_page_with_annotations`. That branch sets
        `annotation_status = 'labeled'` which renders as
        `class="status-badge labeled"` in the page header.

        Without this assertion the test could pass even if the annotated
        branch was silently skipped.
        """
        session = _auth_session(flask_server.base_url, "back_nav_user_2")

        _submit_rating(session, flask_server.base_url, "bn_1", "good")
        _post_action(session, flask_server.base_url, "next_instance")
        resp = _post_action(session, flask_server.base_url, "prev_instance")

        assert resp.status_code == 200
        # The status badge should indicate labeled (annotated + all required met)
        assert "status-badge labeled" in resp.text, (
            "Back-navigated page did not render the 'labeled' status badge — "
            "the has_annotated=True render branch was not exercised."
        )

    def test_back_nav_on_get_annotate(self, flask_server):
        """
        After POSTing prev_instance, a subsequent GET /annotate should still
        render the annotated instance cleanly. Tests that the render path
        is stable across both POST and GET entry points.
        """
        session = _auth_session(flask_server.base_url, "back_nav_user_3")

        _submit_rating(session, flask_server.base_url, "bn_1", "good")
        _post_action(session, flask_server.base_url, "next_instance")
        _post_action(session, flask_server.base_url, "prev_instance")

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        assert "bn_1" in resp.text


# =====================================================================
# TestMultipleBackForwardCycles — stability under repeated navigation
# =====================================================================


class TestMultipleBackForwardCycles:
    """Stress back/forward navigation over annotated instances."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("back_nav_cycles_test")
        test_data = [
            {"id": f"cyc_{i}", "text": f"Cycle item {i}."} for i in range(5)
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "rating",
                    "annotation_type": "radio",
                    "labels": ["good", "bad"],
                    "description": "Rate the item.",
                }
            ],
            data_files=[data_file],
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_annotate_all_then_walk_backward(self, flask_server):
        """
        Annotate 5 instances in order, then walk back through all 5 via
        prev_instance. Every back-navigation hits the annotated-render path.
        """
        session = _auth_session(flask_server.base_url, "cycle_user_1")

        # Annotate forward
        for i in range(5):
            _submit_rating(session, flask_server.base_url, f"cyc_{i}", "good")
            if i < 4:
                resp = _post_action(session, flask_server.base_url, "next_instance")
                assert resp.status_code == 200

        # Walk back through all of them
        for i in range(4, -1, -1):
            resp = _post_action(session, flask_server.base_url, "prev_instance")
            assert resp.status_code == 200, f"prev to cyc_{i} failed"

    def test_interleaved_next_prev_cycles(self, flask_server):
        """Next, prev, next, prev, next... repeatedly across annotated items."""
        session = _auth_session(flask_server.base_url, "cycle_user_2")

        _submit_rating(session, flask_server.base_url, "cyc_0", "good")
        _post_action(session, flask_server.base_url, "next_instance")
        _submit_rating(session, flask_server.base_url, "cyc_1", "good")

        for _ in range(5):
            resp_prev = _post_action(session, flask_server.base_url, "prev_instance")
            assert resp_prev.status_code == 200
            resp_next = _post_action(session, flask_server.base_url, "next_instance")
            assert resp_next.status_code == 200


# =====================================================================
# TestPhaseRetreat — back-navigation across phase boundaries
# =====================================================================


def _write_phase_scheme(test_dir, filename, schemes):
    path = Path(test_dir) / filename
    with open(path, "w") as f:
        json.dump(schemes, f)
    return filename


class TestPhaseRetreatAllowed:
    """With `allow_phase_back_navigation: True`, retreating from the first
    annotation instance should move back into the previous phase page."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("phase_retreat_allowed_test")
        test_data = [
            {"id": "pr_1", "text": "Phase retreat item 1."},
            {"id": "pr_2", "text": "Phase retreat item 2."},
        ]
        data_file = create_test_data_file(test_dir, test_data)

        instructions_file = _write_phase_scheme(
            test_dir,
            "instructions_phase.json",
            [
                {
                    "name": "read_instructions",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Have you read the instructions?",
                }
            ],
        )

        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "rating",
                    "annotation_type": "radio",
                    "labels": ["good", "bad"],
                    "description": "Rate the item.",
                }
            ],
            data_files=[data_file],
            phases={
                "order": ["instructions", "annotation"],
                "instructions": {
                    "type": "instructions",
                    "file": instructions_file,
                },
            },
            additional_config={"allow_phase_back_navigation": True},
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_retreat_from_first_annotation_returns_to_instructions(self, flask_server):
        """User completes instructions → reaches annotation → hits prev at
        first instance → lands back on instructions phase."""
        session = _auth_session(flask_server.base_url, "retreat_allowed_user")

        # Advance past instructions phase
        resp = session.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code == 200
        assert "Have you read the instructions?" in resp.text

        resp = session.post(
            f"{flask_server.base_url}/annotate",
            data={"read_instructions:::Yes": "true"},
            timeout=5,
            allow_redirects=True,
        )
        assert resp.status_code == 200

        # Now on annotation phase
        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        assert "pr_1" in resp.text

        # Retreat from first annotation instance
        resp = _post_action(session, flask_server.base_url, "prev_instance")
        assert resp.status_code == 200

        # Should be back on the instructions page
        resp = session.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code == 200
        assert "Have you read the instructions?" in resp.text, (
            "Retreat from first annotation did not return to instructions phase"
        )


class TestPhaseRetreatBlocked:
    """Without `allow_phase_back_navigation`, retreat from first annotation
    instance must NOT escape to a previous phase — user should stay put."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("phase_retreat_blocked_test")
        test_data = [
            {"id": "rb_1", "text": "Retreat blocked item 1."},
            {"id": "rb_2", "text": "Retreat blocked item 2."},
        ]
        data_file = create_test_data_file(test_dir, test_data)

        instructions_file = _write_phase_scheme(
            test_dir,
            "instructions_phase.json",
            [
                {
                    "name": "read_instructions",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Have you read the instructions?",
                }
            ],
        )

        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "rating",
                    "annotation_type": "radio",
                    "labels": ["good", "bad"],
                    "description": "Rate the item.",
                }
            ],
            data_files=[data_file],
            phases={
                "order": ["instructions", "annotation"],
                "instructions": {
                    "type": "instructions",
                    "file": instructions_file,
                },
            },
            # NOTE: allow_phase_back_navigation intentionally NOT set
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_retreat_blocked_keeps_user_on_annotation(self, flask_server):
        """prev_instance at first annotation must return 200 without
        escaping to the previous phase."""
        session = _auth_session(flask_server.base_url, "retreat_blocked_user")

        # Advance past instructions
        session.post(
            f"{flask_server.base_url}/annotate",
            data={"read_instructions:::Yes": "true"},
            timeout=5,
            allow_redirects=True,
        )

        # Load annotation page
        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        assert "rb_1" in resp.text

        # Retreat should be blocked — still on annotation phase
        resp = _post_action(session, flask_server.base_url, "prev_instance")
        assert resp.status_code == 200

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        # Must still be on annotation, NOT on instructions
        assert "rb_1" in resp.text
        assert "Have you read the instructions?" not in resp.text
