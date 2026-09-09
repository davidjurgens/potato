"""The provenance fields are populated by the live save path, not just settable.

`BehavioralData.record_final_annotations` and `record_pre_annotation_seeds` are
unit-tested in `tests/unit/test_model_answer_provenance.py`. Those tests call
the methods directly and every one of them passed with both call sites removed,
which is the failure this file exists to prevent: testing the unit is not
testing the wiring, and only the second catches a call site being deleted.

So this drives a real server. It posts an AI accept, saves a DIFFERENT answer,
and reads back what was stored -- which is the exact case `final_annotation`
exists for and the one that used to read `null`.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

PORT = 9081
SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
            "description": "Sentiment", "labels": ["positive", "negative"]}]


@pytest.fixture(scope="class", autouse=True)
def server(request):
    with TestConfigManager("provenance_wiring", SCHEMES, num_instances=3) as cfg:
        srv = FlaskTestServer(port=PORT, config_file=cfg.config_path)
        if not srv.start():
            pytest.fail("server failed to start")
        request.cls.base = srv.base_url
        yield srv
        srv.stop()


class TestFinalAnnotationReachesTheRecord:

    def _session(self, email):
        s = requests.Session()
        s.post(f"{self.base}/register",
               data={"email": email, "pass": "x", "action": "signup"})
        s.post(f"{self.base}/auth",
               data={"email": email, "pass": "x", "action": "login"})
        s.get(f"{self.base}/annotate")
        return s

    def _current(self, session):
        return session.get(f"{self.base}/api/current_instance").json().get(
            "instance_id")

    def test_an_overridden_suggestion_records_both_halves(self):
        session = self._session("override@test.com")
        iid = self._current(session)

        for payload in (
            {"event_type": "request"},
            {"event_type": "response", "suggestions": ["positive"]},
            {"event_type": "accept", "accepted_value": "positive"},
        ):
            r = session.post(f"{self.base}/api/track_ai_usage",
                             json={"instance_id": iid,
                                   "schema_name": "sentiment", **payload})
            assert r.status_code == 200, r.text

        # Saved answer differs from the one accepted.
        saved = session.post(f"{self.base}/updateinstance",
                             json={"instance_id": iid,
                                   "annotations": {"sentiment:::negative": "on"}})
        assert saved.status_code == 200, saved.text

        events = self._ai_usage(session, iid)
        assert events, "no AI usage event was stored at all"
        event = events[-1]
        assert event.get("suggestion_accepted") == "positive"
        assert event.get("final_annotation") == "negative", (
            "the record said the suggestion was accepted and nothing said "
            "what was actually submitted")

    def test_an_accepted_and_kept_suggestion_records_the_same_value(self):
        session = self._session("kept@test.com")
        iid = self._current(session)
        for payload in (
            {"event_type": "request"},
            {"event_type": "response", "suggestions": ["positive"]},
            {"event_type": "accept", "accepted_value": "positive"},
        ):
            session.post(f"{self.base}/api/track_ai_usage",
                         json={"instance_id": iid, "schema_name": "sentiment",
                               **payload})
        session.post(f"{self.base}/updateinstance",
                     json={"instance_id": iid,
                           "annotations": {"sentiment:::positive": "on"}})
        event = self._ai_usage(session, iid)[-1]
        assert event.get("final_annotation") == "positive"

    def test_an_orphan_accept_is_recorded_and_marked(self):
        session = self._session("orphan@test.com")
        iid = self._current(session)
        r = session.post(f"{self.base}/api/track_ai_usage",
                         json={"instance_id": iid, "schema_name": "sentiment",
                               "event_type": "accept",
                               "accepted_value": "positive"})
        assert r.status_code == 200
        assert r.json().get("reconstructed") is True, (
            "an accept with no open request was dropped and answered ok, so "
            "the annotator appears never to have used the assistant")

        session.post(f"{self.base}/updateinstance",
                     json={"instance_id": iid,
                           "annotations": {"sentiment:::positive": "on"}})
        events = self._ai_usage(session, iid)
        assert events and events[-1].get("suggestion_accepted") == "positive"
        assert events[-1].get("reconstructed") is True

    def _record(self, session, instance_id):
        """The stored behavioral record, read through the server's own API.

        Through the endpoint rather than by reaching into the singletons: the
        singletons are shared in-process here, so a lookup that walked them
        could find another test's user and report the wrong record.
        """
        response = session.get(f"{self.base}/api/behavioral_data/{instance_id}")
        assert response.status_code == 200, response.text
        return response.json()

    def _ai_usage(self, session, instance_id):
        return self._record(session, instance_id).get("ai_usage", [])
