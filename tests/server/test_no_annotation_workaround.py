"""The workaround the validator recommends for a study with nothing to annotate
has to reach the done page.

validate_annotation_phase_present refuses a config without an annotation
phase and tells the author to add one item. A pure_display scheme on that item
is a dead end: nothing is saved, so the item never completes and Next returns
the same page forever. A one-option radio the participant clicks does complete.
"""

import json
from pathlib import Path

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory)


def _start(name, schemes):
    test_dir = create_test_directory(name)
    data_file = create_test_data_file(test_dir, [{"id": "end", "text": "Thank you."}])
    (Path(test_dir) / "prestudy.json").write_text(json.dumps([{
        "name": "age", "annotation_type": "radio", "labels": ["Under 30", "30 or over"],
        "description": "Your age?"}]))
    config_file = create_test_config(
        test_dir, schemes, data_files=[data_file], require_password=False,
        annotation_task_name=name,
        phases={"order": ["prestudy", "annotation"],
                "prestudy": {"type": "prestudy", "file": "prestudy.json"}})
    server = FlaskTestServer(config_file=config_file, debug=False)
    if not server.start():
        pytest.fail("server did not start")
    return server, test_dir


def _walk(server, username, answer_item):
    s = requests.Session()
    creds = {"email": username, "pass": "pw"}
    s.post(f"{server.base_url}/register", data=creds)
    s.post(f"{server.base_url}/auth", data=creds)
    assert "Your age?" in s.get(f"{server.base_url}/").text
    s.post(f"{server.base_url}/annotate", data={"age:::Under 30": "true"})
    assert "Thank you." in s.get(f"{server.base_url}/annotate").text
    if answer_item:
        r = s.post(f"{server.base_url}/updateinstance", json={
            "instance_id": "end", "span_annotations": [],
            "annotations": {"finish:::Finish": "Finish"}})
        assert r.status_code == 200
    for _ in range(3):
        s.post(f"{server.base_url}/annotate", json={"action": "next_instance"})
    s.get(f"{server.base_url}/")
    from potato.user_state_management import get_user_state_manager
    return get_user_state_manager().get_user_state(username).get_phase().name


class TestTheRecommendedWorkaroundFinishes:

    @pytest.fixture(scope="class")
    def server(self):
        srv, test_dir = _start("no_annotation_radio", [{
            "annotation_type": "radio", "name": "finish",
            "description": "Click Finish to end the study.", "labels": ["Finish"],
            "label_requirement": {"required": True}}])
        yield srv
        srv.stop()
        cleanup_test_directory(test_dir)

    def test_a_one_option_radio_reaches_done(self, server):
        assert _walk(server, "radio_user", answer_item=True) == "DONE"


class TestPureDisplayIsADeadEnd:
    """Why the message no longer recommends pure_display."""

    @pytest.fixture(scope="class")
    def server(self):
        srv, test_dir = _start("no_annotation_display", [{
            "annotation_type": "pure_display", "name": "thanks",
            "description": "Thanks"}])
        yield srv
        srv.stop()
        cleanup_test_directory(test_dir)

    def test_pure_display_never_completes(self, server):
        assert _walk(server, "display_user", answer_item=False) == "ANNOTATION"
