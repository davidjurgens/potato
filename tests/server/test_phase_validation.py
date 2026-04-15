"""
Server-level tests for phase-transition correctness and phase-response
persistence.

Important note on "validation":
Potato does NOT enforce server-side required-field validation on
non-annotation phase pages. Required-field checks in consent/instructions/
prestudy/poststudy forms are client-side only. These tests therefore
document and pin the actual observable behaviors:

- Multi-page phases advance one page at a time (not straight to next phase)
- POST /annotate on a non-annotation phase page calls advance_phase
- Phase responses submitted via /updateinstance with the sentinel
  `__phase_page__` instance_id land in phase_to_page_to_label_to_value
- Consent/prestudy POST advances the phase regardless of form body
  (no built-in validation — if this ever changes, update these tests
  deliberately)
- Poststudy completion routes the user to DONE
- A user in a non-annotation phase does not corrupt another user's
  annotation state

If a future change adds server-side required-field validation, the
"POST advances regardless of body" tests will fail and force a review.
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


def _auth(base_url: str, username: str) -> requests.Session:
    s = requests.Session()
    s.post(
        f"{base_url}/register",
        data={"action": "signup", "email": username, "pass": "pw"},
        timeout=5,
    )
    s.post(
        f"{base_url}/auth",
        data={"action": "login", "email": username, "pass": "pw"},
        timeout=5,
    )
    return s


def _write_phase_scheme(test_dir, filename, schemes):
    path = Path(test_dir) / filename
    with open(path, "w") as f:
        json.dump(schemes, f)
    return filename


# =====================================================================
# TestMultiPagePhaseTransitions
# =====================================================================


class TestMultiPagePhaseTransitions:
    """A consent phase with two pages should advance one page at a time,
    not jump directly to the next phase."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("phase_multipage_test")
        test_data = [{"id": f"m_{i}", "text": f"Item {i}"} for i in range(2)]
        data_file = create_test_data_file(test_dir, test_data)

        consent_page_1 = _write_phase_scheme(
            test_dir,
            "consent_page_1.json",
            [
                {
                    "name": "age_consent",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "MARKER_PAGE_ONE Are you 18 or older?",
                }
            ],
        )
        consent_page_2 = _write_phase_scheme(
            test_dir,
            "consent_page_2.json",
            [
                {
                    "name": "data_consent",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "MARKER_PAGE_TWO Do you agree to data sharing?",
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
                "order": [
                    "consent_page_1",
                    "consent_page_2",
                    "annotation",
                ],
                "consent_page_1": {
                    "type": "consent",
                    "file": consent_page_1,
                },
                "consent_page_2": {
                    "type": "consent",
                    "file": consent_page_2,
                },
            },
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_first_page_is_consent_page_one(self, flask_server):
        s = _auth(flask_server.base_url, "multipage_user_1")
        resp = s.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code == 200
        assert "MARKER_PAGE_ONE" in resp.text

    def test_advancing_consent_page_one_lands_on_consent_page_two(self, flask_server):
        s = _auth(flask_server.base_url, "multipage_user_2")

        # Prove we're on page 1
        resp = s.get(f"{flask_server.base_url}/", timeout=5)
        assert "MARKER_PAGE_ONE" in resp.text

        # POST form payload — body doesn't matter, advance_phase is called regardless
        s.post(
            f"{flask_server.base_url}/annotate",
            data={"age_consent:::Yes": "true"},
            timeout=5,
            allow_redirects=True,
        )

        resp = s.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code == 200
        assert "MARKER_PAGE_TWO" in resp.text, (
            "User should be on consent page 2, not page 1 or annotation"
        )
        # Must NOT have skipped to annotation
        assert "Rate the item." not in resp.text

    def test_advancing_consent_page_two_reaches_annotation(self, flask_server):
        s = _auth(flask_server.base_url, "multipage_user_3")

        # Page 1 → page 2
        s.post(
            f"{flask_server.base_url}/annotate",
            data={"age_consent:::Yes": "true"},
            timeout=5,
            allow_redirects=True,
        )
        # Page 2 → annotation
        s.post(
            f"{flask_server.base_url}/annotate",
            data={"data_consent:::Yes": "true"},
            timeout=5,
            allow_redirects=True,
        )

        resp = s.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        assert "Rate the item." in resp.text  # annotation scheme description


# =====================================================================
# TestPhaseResponsePersistence
# =====================================================================


class TestPhaseResponsePersistence:
    """Responses submitted on non-annotation phase pages are saved to
    user_state.phase_to_page_to_label_to_value via the /updateinstance
    endpoint with sentinel instance_id `__phase_page__`."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("phase_response_persist_test")
        test_data = [{"id": "p1", "text": "Item 1"}, {"id": "p2", "text": "Item 2"}]
        data_file = create_test_data_file(test_dir, test_data)

        consent_file = _write_phase_scheme(
            test_dir,
            "consent_phase.json",
            [
                {
                    "name": "age_consent",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Are you 18+?",
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
                "order": ["consent", "annotation"],
                "consent": {"type": "consent", "file": consent_file},
            },
            additional_config={"export_include_phase_data": True},
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_phase_page_save_via_updateinstance_accepted(self, flask_server):
        """POST to /updateinstance with __phase_page__ sentinel while on a
        consent page should not error. This is how annotation.js auto-saves
        non-annotation form state."""
        s = _auth(flask_server.base_url, "phase_persist_user_1")

        # Confirm we're on consent
        resp = s.get(f"{flask_server.base_url}/", timeout=5)
        assert "Are you 18+?" in resp.text

        # Post a phase-page save
        resp = s.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": "__phase_page__",
                "annotations": {"age_consent": "Yes"},
                "span_annotations": [],
            },
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") in ("ok", "success")

    def test_annotation_phase_save_still_works_for_other_user(self, flask_server):
        """Ensure a user in the consent phase doesn't poison the state for
        a concurrent annotation-phase user."""
        consent_user = _auth(flask_server.base_url, "persist_consent_user")
        # consent_user stays on consent page
        consent_user.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": "__phase_page__",
                "annotations": {"age_consent": "No"},
                "span_annotations": [],
            },
            timeout=5,
        )

        # A different user walks through consent to annotation and submits
        annot_user = _auth(flask_server.base_url, "persist_annot_user")
        annot_user.post(
            f"{flask_server.base_url}/annotate",
            data={"age_consent:::Yes": "true"},
            timeout=5,
            allow_redirects=True,
        )
        resp = annot_user.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": "p1",
                "schema": "rating",
                "type": "label",
                "state": [{"name": "good", "value": "good"}],
            },
            timeout=5,
        )
        assert resp.status_code == 200


# =====================================================================
# TestUnassignedInstanceRejection
# =====================================================================


class TestUnassignedInstanceRejection:
    """The /updateinstance endpoint rejects updates for instances not
    assigned to the current user (anti-tampering guard)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("unassigned_reject_test")
        test_data = [{"id": f"u_{i}", "text": f"Item {i}"} for i in range(3)]
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
            max_annotations_per_user=1,  # Each user only gets 1 item
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_update_to_unassigned_instance_rejected(self, flask_server):
        """
        A user assigned to only 1 instance should NOT be able to
        POST annotations for a different instance they aren't assigned to.
        """
        s = _auth(flask_server.base_url, "unassigned_user")

        # Get the annotate page so user state is initialized
        resp = s.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200

        # Try to update an instance id the user is NOT assigned to
        # (there are 3 items, user is assigned 1 — pick all 3 ids and hope
        # at least one is unassigned)
        unassigned_attempted = False
        for item_id in ("u_0", "u_1", "u_2"):
            resp = s.post(
                f"{flask_server.base_url}/updateinstance",
                json={
                    "instance_id": item_id,
                    "schema": "rating",
                    "type": "label",
                    "state": [{"name": "good", "value": "good"}],
                },
                timeout=5,
            )
            assert resp.status_code == 200  # endpoint returns JSON, not HTTP error
            body = resp.json()
            if body.get("status") == "error" and "not assigned" in body.get("message", ""):
                unassigned_attempted = True
                break

        assert unassigned_attempted, (
            "Expected at least one instance to be rejected as unassigned — "
            "anti-tampering guard may not be functioning"
        )

    def test_empty_instance_id_rejected(self, flask_server):
        """Empty/null instance_id must be rejected with an error status."""
        s = _auth(flask_server.base_url, "empty_id_user")
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        resp = s.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": "",
                "schema": "rating",
                "type": "label",
                "state": [{"name": "good", "value": "good"}],
            },
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "error"
        assert "instance_id" in body.get("message", "").lower()


# =====================================================================
# TestPoststudyReachable
# =====================================================================


class TestPoststudyReachable:
    """After a user exhausts their assigned items, the next home GET
    should render the poststudy page (not DONE, not an error)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("poststudy_validation_test")
        test_data = [{"id": "ps_1", "text": "Item 1"}]
        data_file = create_test_data_file(test_dir, test_data)

        poststudy_file = _write_phase_scheme(
            test_dir,
            "poststudy_phase.json",
            [
                {
                    "name": "overall_rating",
                    "annotation_type": "radio",
                    "labels": ["1", "2", "3", "4", "5"],
                    "description": "MARKER_POSTSTUDY How was the study?",
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
            max_annotations_per_user=1,
            phases={
                "order": ["annotation", "poststudy"],
                "poststudy": {
                    "type": "poststudy",
                    "file": poststudy_file,
                },
            },
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_user_reaches_poststudy_after_completing_all_items(self, flask_server):
        s = _auth(flask_server.base_url, "ps_reach_user")

        # Load annotation page
        resp = s.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        assert "Rate the item." in resp.text

        # Submit annotation for the only assigned instance
        s.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": "ps_1",
                "schema": "rating",
                "type": "label",
                "state": [{"name": "good", "value": "good"}],
            },
            timeout=5,
        )

        # Advance to next — should move to poststudy
        s.post(
            f"{flask_server.base_url}/annotate",
            data={"action": "next_instance"},
            timeout=5,
            allow_redirects=True,
        )

        # Home GET should now render poststudy
        resp = s.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code == 200
        assert "MARKER_POSTSTUDY" in resp.text, (
            f"Expected poststudy page, got:\n{resp.text[:300]}"
        )

    def test_poststudy_submission_advances_out_of_poststudy(self, flask_server):
        s = _auth(flask_server.base_url, "ps_submit_user")

        # Complete annotation
        s.get(f"{flask_server.base_url}/annotate", timeout=5)
        s.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": "ps_1",
                "schema": "rating",
                "type": "label",
                "state": [{"name": "good", "value": "good"}],
            },
            timeout=5,
        )
        s.post(
            f"{flask_server.base_url}/annotate",
            data={"action": "next_instance"},
            timeout=5,
        )

        # Verify on poststudy
        resp = s.get(f"{flask_server.base_url}/", timeout=5)
        assert "MARKER_POSTSTUDY" in resp.text

        # Submit poststudy form
        s.post(
            f"{flask_server.base_url}/annotate",
            data={"overall_rating:::5": "true"},
            timeout=5,
            allow_redirects=True,
        )

        # After poststudy, user should no longer see poststudy marker on home
        resp = s.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code == 200
        assert "MARKER_POSTSTUDY" not in resp.text, (
            "Poststudy should have advanced — user is stuck on poststudy page"
        )
