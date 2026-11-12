"""
The navbar counter on a phase page.

Audit 25: after finishing all eight items, the post-study page read
"Progress 0/8 - Instance #1" for both annotators. Phase pages render through
``get_current_page_html`` rather than ``render_page_with_annotations``, and
that function hardcoded ``finished: 0`` and ``instance_index: 0`` -- so the one
page an annotator looks at to confirm they are done said they had done nothing,
and every consent, instruction and survey page claimed to be instance #1.

This is the two-render-path hazard again: the count is now computed once, in
``progress_counts``, and both paths call it.
"""

import json
import os
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


PHASES = {
    "order": ["consent", "annotation", "poststudy"],
    "consent": {"type": "consent", "file": "surveys/consent.json"},
    "annotation": {"type": "annotation"},
    "poststudy": {"type": "poststudy", "file": "surveys/poststudy.json"},
}

CONSENT_PAGE = [{
    "name": "consent_agree",
    "description": "I agree to take part.",
    "annotation_type": "radio",
    "labels": [{"name": "agree", "label": "I agree"}],
}]

POSTSTUDY_PAGE = [{
    "name": "how_was_it",
    "description": "How was the task?",
    "annotation_type": "radio",
    "labels": [{"name": "fine", "label": "Fine"}],
}]


@pytest.fixture(scope="module")
def phase_server():
    schemes = [{
        "annotation_type": "radio",
        "name": "sentiment",
        "description": "Rate the sentiment",
        "labels": ["pos", "neg"],
    }]
    with TestConfigManager("audit25_phase_progress", schemes,
                           num_instances=2, phases=PHASES) as cfg:
        surveys = os.path.join(cfg.task_dir, "surveys")
        os.makedirs(surveys, exist_ok=True)
        for name, page in (("consent.json", CONSENT_PAGE),
                           ("poststudy.json", POSTSTUDY_PAGE)):
            with open(os.path.join(surveys, name), "w") as handle:
                json.dump(page, handle)

        server = FlaskTestServer(port=9048, config_file=cfg.config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        yield server
        server.stop()


def _counter(html):
    match = re.search(r'id="progress-counter"[^>]*>([^<]*)<', html)
    return match.group(1).strip() if match else None


def _instance_chip(html):
    match = re.search(r'id="instance-number"[^>]*>([^<]*)<', html)
    return match.group(1).strip() if match else None


def _finish_the_study(server, email):
    session = requests.Session()
    session.post(f"{server.base_url}/register", data={"email": email, "pass": "pw"})
    session.post(f"{server.base_url}/auth", data={"email": email, "pass": "pw"})
    first = session.get(f"{server.base_url}/annotate")

    # Clear the consent page, then answer both items.
    session.post(f"{server.base_url}/updateinstance",
                 json={"instance_id": None,
                       "annotations": {"consent_agree": "agree"}})
    session.post(f"{server.base_url}/annotate", data={"src": "next_instance"})
    last = None
    for instance_id in ("1", "2"):
        session.post(f"{server.base_url}/updateinstance",
                     json={"instance_id": instance_id,
                           "annotations": {"sentiment:::pos": "true"}})
        last = session.post(f"{server.base_url}/annotate",
                            data={"src": "next_instance"})
    return first.text, last.text


class TestPhasePageProgressCounter:

    def test_the_first_phase_page_counts_nothing_done_yet(self, phase_server):
        consent, _ = _finish_the_study(phase_server, "before@lab.org")
        assert _counter(consent) == "0/2"

    def test_the_trailing_phase_page_counts_the_finished_items(
            self, phase_server):
        """The assertion is 2/2, not "a counter is present".

        The old context hardcoded 0, so any test that only checked the counter
        rendered passed while it read "0/2" on a completed study.
        """
        _, poststudy = _finish_the_study(phase_server, "after@lab.org")
        assert _counter(poststudy) == "2/2"

    def test_no_phase_page_claims_to_be_an_instance(self, phase_server):
        """A consent or post-study page is not instance #1.

        The template renders the chip only when `instance_index` is defined,
        and the phase context defined it as 0.
        """
        consent, poststudy = _finish_the_study(phase_server, "chip@lab.org")
        assert _instance_chip(consent) is None
        assert _instance_chip(poststudy) is None

    def test_the_annotation_page_still_shows_its_instance(self, phase_server):
        """The chip belongs on the page that has an instance."""
        session = requests.Session()
        session.post(f"{phase_server.base_url}/register",
                     data={"email": "chip2@lab.org", "pass": "pw"})
        session.post(f"{phase_server.base_url}/auth",
                     data={"email": "chip2@lab.org", "pass": "pw"})
        session.get(f"{phase_server.base_url}/annotate")
        session.post(f"{phase_server.base_url}/updateinstance",
                     json={"instance_id": None,
                           "annotations": {"consent_agree": "agree"}})
        page = session.post(f"{phase_server.base_url}/annotate",
                            data={"src": "next_instance"})
        assert _instance_chip(page.text) == "#1"
        assert _counter(page.text) == "0/2"
