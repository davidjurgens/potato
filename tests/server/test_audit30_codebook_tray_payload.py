"""
GET /api/codebook must carry each code's definition, and /version must move
when one is edited.

Audit 27 (e). The tray on the annotation page renders from this payload; if
the definition is not in it there is nothing for the tray to show. And the
client only re-fetches when /version reports a change, so a poll that reported
the structural revision alone would keep serving a cached tray with wording the
researcher had already replaced.

The degenerate shape is the one that matters here: one code, one edit, no
structural change at all. That is precisely the case where the two revisions
disagree.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory, create_test_data_file, create_test_config,
    cleanup_test_directory)

_CB = [{"name": "themes", "description": "T",
        "annotation_type": "multiselect", "codebook": True,
        "labels": [{"name": "delay", "color": "#4682b4",
                    "description": "The agent stalled before acting."}]}]


class TestTrayPayload:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cb_tray_payload")
        data_file = create_test_data_file(
            test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _CB, data_files=[data_file], require_password=False,
            additional_config={"codebook_mode": "open"})
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    @pytest.fixture
    def session(self):
        s = requests.Session()
        base = self.server.base_url
        s.post(f"{base}/register", data={"email": "tray", "pass": "pw"})
        s.post(f"{base}/auth", data={"email": "tray", "pass": "pw"})
        return s

    def _url(self, path=""):
        return f"{self.server.base_url}/api/codebook{path}"

    def _delay(self, session):
        tree = session.get(self._url()).json()["tree"]
        return next(n for n in tree if n["name"] == "delay")

    def test_the_seeded_definition_and_colour_are_in_the_payload(
            self, session):
        node = self._delay(session)
        assert node["definition"] == "The agent stalled before acting."
        assert node["color"] == "#4682b4"

    def test_version_reports_the_content_revision(self, session):
        body = session.get(self._url("/version")).json()
        assert "content_revision" in body
        assert body["content_revision"] == (
            session.get(self._url()).json()["content_revision"])

    def test_editing_a_definition_moves_version_without_a_structural_change(
            self, session):
        node = self._delay(session)
        before = session.get(self._url("/version")).json()

        scope = session.get(
            self._url("/blocks"),
            params={"scope_kind": "code", "scope_id": node["id"]}).json()
        put = session.put(self._url("/blocks"), json={
            "scope_kind": "code", "scope_id": node["id"],
            "base_version": scope["scope_version"],
            "blocks": [{"block_type": "short_def",
                        "body_md": "Rewritten by the researcher."}],
        })
        assert put.status_code == 200, put.text

        after = session.get(self._url("/version")).json()
        assert after["revision"] == before["revision"], (
            "editing prose is not a structural change")
        assert after["content_revision"] != before["content_revision"], (
            "the client caches on this value; if it does not move, the tray "
            "keeps showing the wording that was just replaced")
        assert (self._delay(session)["definition"]
                == "Rewritten by the researcher.")
