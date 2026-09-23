"""The ``require_declaration`` refusal, driven through a real server.

The unit tests cover the membership rule and the config guard. Neither touches
the route, and a rule that is never wired into ``/updateinstance`` refuses
nothing however correct it is -- testing the unit is not testing the wiring.

What matters here beyond "it returns 403":

* The refusal carries an HTTP status. ``annotation.js`` only checks
  ``response.ok``, so a refusal answering 200 looks to the page exactly like a
  save that was stored, and the annotator loses the work without being told.
* A listed person and a declared machine both still save, so the guard refuses
  strangers rather than everybody.
* Phase-page autosaves are exempt: consent and survey answers are not dataset
  annotations.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

PORT = 9241

SCHEMES = [
    {
        "annotation_type": "radio",
        "name": "sentiment",
        "description": "Sentiment?",
        "labels": ["positive", "negative"],
    },
]

ITEMS = [{"id": f"item_{i}", "text": f"Review {i}"} for i in range(1, 5)]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("require_declaration_api")
    try:
        create_test_data_file(test_dir, ITEMS)
        config_file = create_test_config(
            test_dir,
            SCHEMES,
            data_files=["test_data.jsonl"],
            annotation_task_name="Require Declaration",
            # require_declaration needs a roster of people to compare a
            # participant against; the config refuses to load without one.
            user_config={"allow_all_users": False, "users": ["alice", "carol"]},
            additional_config={
                "machine_annotators": {
                    "enabled": True,
                    "require_declaration": True,
                    "annotators": [
                        {"id": "prokka", "kind": "tool", "version": "1.14.6"},
                    ],
                },
            },
        )
        srv = FlaskTestServer(port=PORT, config_file=config_file)
        if not srv.start():
            pytest.fail("Failed to start server for require_declaration tests")
        yield srv
        srv.stop()
    finally:
        cleanup_test_directory(test_dir)


def _session(server, username):
    """Register and log in.

    Closed enrolment admits two kinds of participant: a listed person and a
    declared machine. Both must reach the write path, or the refusal under test
    could never fire for anyone and this file would pass by never running.
    """
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"action": "signup", "email": username, "pass": "pw12345"})
    s.post(f"{server.base_url}/auth",
           data={"action": "login", "email": username, "pass": "pw12345"})
    return s


def _save(session, server, instance_id="item_1", value="positive"):
    return session.post(
        f"{server.base_url}/updateinstance",
        json={
            "instance_id": instance_id,
            "annotations": {f"sentiment:::{value}": value},
            "span_annotations": [],
        },
    )


class TestTheRefusalReachesTheRoute:
    def test_a_stranger_never_gets_a_session_in_the_first_place(self, server):
        """Not the require_declaration guard -- closed enrolment, which is older.

        `require_declaration` forces `allow_all_users: false`, and that already
        refuses a username on neither roster. So a stranger is stopped before a
        session exists and answers 401 "No active session", never reaching
        `/updateinstance`. Asserting 403 here would look like coverage of the
        guard while measuring something else entirely.
        """
        s = _session(server, "mallory")
        response = _save(s, server)
        assert response.status_code == 401, response.text

    def test_the_guard_fires_when_a_declaration_is_withdrawn(self, server):
        """The path that does reach it: a roster edited while the server runs.

        Logins are held in memory, so a participant dropped from the roster
        keeps a valid session. The write-path check is what stops the next
        save, and it sits downstream of every route that mints a session
        rather than at any one login door.
        """
        s = _session(server, "carol")
        assert _save(s, server, "item_4").status_code == 200, (
            "carol is on the roster and must be able to save first")

        from potato.authentication import UserAuthenticator
        authenticator = UserAuthenticator.get_instance()
        original = list(authenticator.authorized_users)
        authenticator.authorized_users = [u for u in original if u != "carol"]
        try:
            refused = _save(s, server, "item_1")
        finally:
            authenticator.authorized_users = original

        assert refused.status_code == 403, refused.text
        assert "not declared" in refused.text.lower()

    def test_a_listed_person_still_saves(self, server):
        s = _session(server, "alice")
        assert _save(s, server, "item_2").status_code == 200

    def test_a_declared_machine_still_saves(self, server):
        """The regression that matters.

        require_declaration demands closed enrolment, and a declared machine is
        not on the human roster. Unless enrolment admits it too, the setting
        locks out the raters it was configured to accept.
        """
        s = _session(server, "prokka")
        assert _save(s, server, "item_3").status_code == 200


class TestPhasePagesAreExempt:
    def test_a_phase_page_autosave_is_not_refused(self, server):
        """Consent and survey answers are not dataset annotations."""
        s = _session(server, "alice")
        response = s.post(
            f"{server.base_url}/updateinstance",
            json={
                "instance_id": "__phase_page__",
                "annotations": {"consent:::yes": "yes"},
                "span_annotations": [],
            },
        )
        assert response.status_code != 403, response.text
