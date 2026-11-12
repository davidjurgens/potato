"""Adjudicators see the UNION of all per-cohort schemes.

With per-cohort schemas, each annotator is served only their cohort's schemes
(covered by test_cohort_schemes_routes.py). An adjudicator, however, reviews
every cohort, so the `/adjudicate` page must render the union of all cohort
scheme sets. This is `routes.py`'s
`get_cohort_scheme_resolver().union_of_all_schemes()`.

cohortA binds only `sentiment` (label marker "poslabel"); cohortB binds
`sentiment` + `topic` (marker "alphalabel"). The adjudicator page must contain
BOTH markers, while cohortA's own annotation page contains only "poslabel".
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
    "adjudication": {
        "enabled": True,
        "adjudicator_users": ["judge@x.com"],
        "min_annotations": 2,
        "error_taxonomy": ["ambiguous_text"],
    },
}


class TestCohortAdjudicatorUnion:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "cohort_adjudicator_union",
            ANNOTATION_SCHEMES,
            num_instances=3,
            additional_config=ADDITIONAL,
        ) as cfg:
            server = FlaskTestServer(port=9043, config_file=cfg.config_path)
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
        for _ in range(6):
            r = session.get(f"{self.base_url}/annotate")
            if "alphalabel" in r.text or "poslabel" in r.text:
                return r.text
            session.post(f"{self.base_url}/annotate", data={"src": "next"})
        return r.text

    def test_adjudicator_page_shows_union_of_schemes(self):
        s = self._login("judge@x.com")
        r = s.get(f"{self.base_url}/adjudicate", allow_redirects=False)
        assert r.status_code == 200, "adjudicator should reach the adjudication page"
        assert "poslabel" in r.text, "union must include cohortA's sentiment scheme"
        assert "alphalabel" in r.text, "union must include cohortB's topic scheme"

    def test_cohortA_annotator_still_sees_only_their_schemes(self):
        # Sanity: enabling adjudication does not leak cohortB's schemes to cohortA.
        html = self._annotate_html(self._login("alice@x.com"))
        assert "poslabel" in html
        assert "alphalabel" not in html
