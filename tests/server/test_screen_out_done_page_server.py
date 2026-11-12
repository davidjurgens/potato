"""
A participant screened out on a crowd platform is not told they completed the
task.

With a provider configured, the done page said "You have completed the
annotation task and your responses are saved." to screen-outs too, with only
the code different, and the `exit_when` message was never shown.
"""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory)

MESSAGE = "This study is only open to adults."


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("screen_out_done_page")
    data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hello"}])
    screener = os.path.join(test_dir, "screener.json")
    with open(screener, "w") as f:
        json.dump([{"name": "age", "annotation_type": "number", "description": "Age?",
                    "label_requirement": {"required": True}}], f)
    config_file = create_test_config(
        test_dir,
        [{"name": "rating", "annotation_type": "radio", "labels": ["good", "bad"],
          "description": "Rate."}],
        data_files=[data_file],
        require_password=False,
        additional_config={
            "login": {"type": "url_direct", "url_argument": "pid"},
            "crowdsourcing": {"provider": "generic", "generic": {
                "id_param": "pid",
                "completion": {"code": "DONE-OK", "screened_out_code": "SCREEN-OUT"}}}},
        phases={"order": ["screener", "annotation"],
                "screener": {"type": "prestudy", "file": screener,
                             "exit_when": {"show_when": [
                                 {"schema": "age", "operator": "lt", "value": 18}],
                                 "message": MESSAGE}}},
    )
    srv = FlaskTestServer(port=9877, config_file=config_file)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def test_a_screened_out_participant_sees_why_and_the_screen_out_code(server):
    s = requests.Session()
    s.get(f"{server.base_url}/", params={"pid": "minor1"})
    s.post(f"{server.base_url}/updateinstance", json={
        "instance_id": "__phase_page__", "annotations": {"age:::age": "15"},
        "span_annotations": []})
    s.post(f"{server.base_url}/annotate", json={"action": "next_instance"})
    page = s.get(f"{server.base_url}/done").text
    assert "SCREEN-OUT" in page and "DONE-OK" not in page
    assert MESSAGE in page
    assert "You have completed the annotation task" not in page
