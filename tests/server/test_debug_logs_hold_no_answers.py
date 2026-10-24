"""
Debug logging must not write participants' answers.

The save routes logged the whole request at DEBUG (`Received JSON data`,
`POST form data`, `POST -> PRESTUDY: <form>`), and potato.log keeps DEBUG lines
in debug mode. An answer is participant data, and a sensitive-questions page
(list experiment, randomized response) is designed so that no single answer
is recorded in the clear. The routes now log the keys only.
"""

import logging
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import TestConfigManager

ANSWER = "answer-kept-out-of-logs-4e2b"


@pytest.fixture(scope="module")
def server():
    schemes = [{"annotation_type": "text", "name": "comment", "description": "Comment"}]
    with TestConfigManager("debug_logs_answers", schemes, num_items=2) as cfg:
        srv = FlaskTestServer(port=find_free_port(), config_file=cfg.config_path)
        if not srv.start():
            pytest.fail("Failed to start server")
        yield srv
        srv.stop()


def _session(base):
    s = requests.Session()
    s.post(f"{base}/register", data={"email": "log_answers", "pass": "pw"})
    s.post(f"{base}/auth", data={"email": "log_answers", "pass": "pw"})
    page = s.get(f"{base}/annotate").text
    instance_id = re.search(r'id="instance_id"[^>]*value="([^"]+)"', page).group(1)
    return s, instance_id


def test_saved_answers_are_not_logged(server, caplog):
    base = server.base_url
    s, instance_id = _session(base)
    with caplog.at_level(logging.DEBUG, logger="potato.flask_server"):
        r = s.post(f"{base}/updateinstance",
                   json={"instance_id": instance_id,
                         "annotations": {"comment:::text": ANSWER}})
        assert r.status_code == 200, r.text
        s.post(f"{base}/annotate", data={"instance_id": instance_id, "comment:::text": ANSWER,
                                         "action": "next_instance"})
        # /submit_annotation, with a text answer and a {label: value} answer
        # (potato-skill found four lines there still logging the value).
        for answer in (ANSWER, {"text_box": ANSWER}):
            r = s.post(f"{base}/submit_annotation",
                       json={"instance_id": instance_id, "annotations": {"comment": answer}})
            assert r.status_code == 200, r.text
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "Received JSON keys" in text
    assert ANSWER not in text
