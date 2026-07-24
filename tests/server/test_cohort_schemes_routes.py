"""Server integration tests for per-cohort schema assignment.

Two cohorts bind different scheme sets; each annotator should be served their
cohort's schemes. cohortA sees only `sentiment`; cohortB sees `sentiment` +
`topic` (whose distinctive label "alphalabel" must appear only for cohortB).
Adjudicators see the union of all cohort schemes.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


ANNOTATION_SCHEMES = [
    {
        "name": "sentiment",
        "annotation_type": "radio",
        "description": "Sentiment",
        "labels": ["poslabel", "neglabel"],
    },
    {
        "name": "topic",
        "annotation_type": "radio",
        "description": "Topic",
        "labels": ["alphalabel", "betalabel"],
    },
]

ADDITIONAL = {
    "assignment_strategy": "batch",
    "scheme_sets": {"minimal": ["sentiment"]},
    "batch_assignment": {
        "groups": [
            {"name": "cohortA", "annotators": ["alice@x.com"], "instances": ["1", "2"], "schemes": "minimal"},
            {"name": "cohortB", "annotators": ["bob@x.com"], "instances": ["3"], "schemes": ["sentiment", "topic"]},
        ]
    },
}


class TestCohortSchemesRoutes:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "cohort_schemes",
            ANNOTATION_SCHEMES,
            num_instances=3,
            additional_config=ADDITIONAL,
        ) as test_config:
            server = FlaskTestServer(port=9038, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            request.cls.server = server
            request.cls.base_url = server.base_url
            yield server
            server.stop()

    def _login(self, username):
        s = requests.Session()
        s.post(f"{self.base_url}/register", data={"email": username, "pass": "pass"})
        s.post(f"{self.base_url}/auth", data={"email": username, "pass": "pass"})
        return s

    def _annotate_html(self, session):
        # Advance through any pre-annotation phases to reach the annotation page.
        for _ in range(6):
            r = session.get(f"{self.base_url}/annotate")
            if "alphalabel" in r.text or "poslabel" in r.text:
                return r.text
            # Try to advance the phase (consent/instructions) if present.
            session.post(f"{self.base_url}/annotate", data={"src": "next"})
        return r.text

    def test_cohortA_sees_only_sentiment(self):
        s = self._login("alice@x.com")
        html = self._annotate_html(s)
        assert "poslabel" in html, "cohortA should see the sentiment scheme"
        assert "alphalabel" not in html, "cohortA must NOT see the topic scheme"

    def test_cohortB_sees_both_schemes(self):
        s = self._login("bob@x.com")
        html = self._annotate_html(s)
        assert "poslabel" in html
        assert "alphalabel" in html, "cohortB should see the topic scheme"

    def test_cohort_pages_differ(self):
        a = self._annotate_html(self._login("alice@x.com"))
        b = self._annotate_html(self._login("bob@x.com"))
        assert a != b
