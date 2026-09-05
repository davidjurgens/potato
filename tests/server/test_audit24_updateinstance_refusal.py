"""A /updateinstance payload that stores nothing must say so.

Audit 24 filed no Potato findings. This came out of chasing the one loose end
it left open -- a second annotator that "never arrived" -- which turned out to
be a harness mistake on both sides rather than a defect. Mine was posting
`{"sentiment": {"positive": "true"}}`, whose keys name no label, so every entry
was skipped and nothing was written. The route answered 200, so the probe
recorded eight annotated items and the agreement report came back empty with
no explanation anywhere the caller could see.

The browser always sends `schema:::label`, so this only reaches programmatic
callers -- the MCP tools, the simulator, an evaluation harness -- which is
exactly the population that cannot read the server log.

Same rule as every other refusal on this route: say no with a status.
See internal note: a refused save needs an HTTP status, not 200 + an error body.
"""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


SCHEMES = [{
    "annotation_type": "radio",
    "name": "sentiment",
    "description": "Sentiment",
    "labels": ["positive", "negative"],
}]


class TestUpdateInstanceRejectsUnreadableKeys:

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self):
        with TestConfigManager("audit24_updateinstance", SCHEMES) as cfg:
            server = FlaskTestServer(port=9042, config_file=cfg.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    @pytest.fixture
    def session(self, flask_server):
        import uuid
        user = f"u{uuid.uuid4().hex[:10]}@x.com"
        s = requests.Session()
        s.post(f"{flask_server.base_url}/register",
               data={"email": user, "pass": "pw", "action": "signup"})
        s.post(f"{flask_server.base_url}/auth",
               data={"email": user, "pass": "pw", "action": "login"})
        page = s.get(f"{flask_server.base_url}/annotate")
        match = re.search(r'name="instance_id"[^>]*value="([^"]*)"', page.text)
        assert match and match.group(1), "no instance was served"
        s._instance_id = match.group(1)
        s._base = flask_server.base_url
        return s

    def _save(self, session, annotations):
        return session.post(f"{session._base}/updateinstance",
                            json={"instance_id": session._instance_id,
                                  "annotations": annotations})

    def test_a_nested_payload_is_refused(self, session):
        """The shape a caller reaches for first, and the one that cost the
        most time: it looks like the stored format, and it stores nothing."""
        response = self._save(session, {"sentiment": {"positive": "true"}})
        assert response.status_code == 400

    def test_the_refusal_names_the_format_it_wanted(self, session):
        response = self._save(session, {"sentiment": {"positive": "true"}})
        body = response.json().get("message", "")
        assert "schema:::label" in body
        assert "sentiment" in body, "the refusal must quote the key it refused"

    def test_every_key_unreadable_is_refused(self, session):
        response = self._save(session, {"a": "1", "b": "2"})
        assert response.status_code == 400

    def test_the_canonical_form_is_accepted(self, session):
        response = self._save(session, {"sentiment:::positive": "true"})
        assert response.status_code == 200

    def test_the_legacy_single_colon_form_is_accepted(self, session):
        """Still in use; refusing it would break stored callers."""
        response = self._save(session, {"sentiment:positive": "true"})
        assert response.status_code == 200

    def test_a_partly_readable_payload_is_accepted(self, session):
        """One good key means the write is real. Refusing the whole payload
        would lose an annotation the caller did express correctly."""
        response = self._save(
            session, {"sentiment:::positive": "true", "junk": "x"})
        assert response.status_code == 200

    def test_a_partly_readable_payload_stores_the_good_key(self, session):
        self._save(session, {"sentiment:::negative": "true", "junk": "x"})
        stored = session.get(
            f"{session._base}/get_annotations",
            params={"instance_id": session._instance_id}).json()
        assert "negative" in str(stored.get("label_annotations", {}))

    def test_an_empty_payload_is_accepted(self, session):
        """Clearing every answer is a legitimate save, not a malformed one."""
        response = self._save(session, {})
        assert response.status_code == 200

    def test_a_refusal_does_not_destroy_existing_answers(self, session):
        """The refusal is decided after the pre-clear that drops stale labels
        for the incoming schemas. That is only safe because a malformed key
        contributes no schema name, so the clear set is empty -- assert the
        outcome rather than trusting the reasoning."""
        self._save(session, {"sentiment:::positive": "true"})
        before = session.get(
            f"{session._base}/get_annotations",
            params={"instance_id": session._instance_id}).json()
        assert before.get("label_annotations"), "setup did not store"

        refused = self._save(session, {"sentiment": {"negative": "true"}})
        assert refused.status_code == 400

        after = session.get(
            f"{session._base}/get_annotations",
            params={"instance_id": session._instance_id}).json()
        assert after.get("label_annotations") == before.get("label_annotations"), (
            "a refused save wiped the answer that was already stored")

    def test_a_refused_payload_stores_nothing(self, session):
        self._save(session, {"sentiment": {"positive": "true"}})
        stored = session.get(
            f"{session._base}/get_annotations",
            params={"instance_id": session._instance_id}).json()
        assert not stored.get("label_annotations"), (
            "a refused save must not half-write")


# Phase pages are exempt from the refusal: a consent or survey question posts
# `{"age_consent": "Yes"}` -- the schema name with the answer as the value,
# because a phase question has no label to name. The first version of this
# guard refused that and broke every consent page. Only the full server suite
# caught it.
#
# Not re-tested here. This module's config has no consent phase, so a fresh
# user is already in ANNOTATION, where a `__phase_page__` save takes an earlier
# `return 200` and never reaches the guard at all -- a test written here would
# pass with the exemption removed. The real coverage is
# tests/server/test_phase_validation.py::TestPhaseResponsePersistence
# ::test_phase_page_save_via_updateinstance_accepted, which runs against a
# config that has phases and does fail without it.
