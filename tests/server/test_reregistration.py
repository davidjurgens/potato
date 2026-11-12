"""
Registering again, for an account that exists and for one the roster lost.

An annotator who had annotated and then pressed Register instead of Log in
was told to have their account restored, and the server logged an ERROR that
the roster was out of step. The check looked only for their annotations on
disk, never at whether the account existed. A known account now gets the
ordinary "already exists" answer; the restore message is kept for a username
with annotations and no account.
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

RESTORE = "Ask the study administrator to restore your account"


@pytest.fixture(scope="module")
def server():
    schemes = [{"annotation_type": "radio", "name": "s", "description": "d",
                "labels": ["a", "b"]}]
    with TestConfigManager("reregistration", schemes, num_instances=2,
                           require_password=True) as cfg:
        srv = FlaskTestServer(port=9051, config_file=cfg.config_path,
                              debug=False)
        if not srv.start():
            pytest.fail("Failed to start server")
        with open(cfg.config_path) as handle:
            srv.output_dir = yaml.safe_load(handle)["output_annotation_dir"]
        yield srv
        srv.stop()


def _register(server, user, password="pw"):
    return requests.Session().post(f"{server.base_url}/register",
                                   data={"email": user, "pass": password})


def test_an_annotator_who_registers_again_is_told_to_log_in(server):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": "alice", "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    response = session.post(f"{server.base_url}/updateinstance",
                            json={"instance_id": "1",
                                  "annotations": {"s:::a": "true"}})
    assert response.status_code == 200, response.text
    assert os.path.isfile(os.path.join(server.output_dir, "alice",
                                       "user_state.json"))

    again = _register(server, "alice")
    assert "already exists" in again.text
    assert RESTORE not in again.text
    # Told to log in, so the page has to offer a password field and the
    # task's title; it fell back to the passwordless form and the default.
    assert 'type="password"' in again.text
    assert "Test Task" in again.text
    # Her account still works.
    login = requests.Session()
    login.post(f"{server.base_url}/auth", data={"email": "alice", "pass": "pw"})
    assert login.get(f"{server.base_url}/annotate").status_code == 200


def test_annotations_without_an_account_still_ask_for_a_restore(server):
    """The roster lost bob, but his work is on disk: do not hand it over."""
    directory = os.path.join(server.output_dir, "bob")
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "user_state.json"), "w") as handle:
        json.dump({"user_id": "bob"}, handle)

    response = _register(server, "bob")
    assert RESTORE in response.text
