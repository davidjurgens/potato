"""A save before the first assignment must name an item that exists.

The assignment guard on /updateinstance only runs once a user has
assignments, so a fresh session could save to any id: a save to "None" was
stored and was the only row in the jsonl export (found by potato-skill).
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import TestConfigManager


@pytest.fixture(scope="module")
def server():
    schemes = [{"annotation_type": "radio", "name": "s", "description": "Pick one",
                "labels": ["a", "b"]}]
    with TestConfigManager("updateinstance_unknown_id", schemes, num_instances=3) as cfg:
        srv = FlaskTestServer(port=find_free_port(preferred_port=9655),
                              config_file=cfg.config_path)
        if not srv.start():
            pytest.fail("Failed to start Flask test server")
        yield srv
        srv.stop()


def _fresh_session(base_url, name):
    s = requests.Session()
    user = {"email": name, "pass": "pass"}
    s.post(f"{base_url}/register", data=user, timeout=5)
    s.post(f"{base_url}/auth", data=user, timeout=5)
    s.headers.update({"Origin": base_url})
    return s


def test_an_unknown_id_is_refused_before_any_assignment(server):
    from potato.user_state_management import get_user_state_manager
    s = _fresh_session(server.base_url, "fresh_unknown")
    # Under the engine strategy a person holds nothing until a request is
    # claimed; here login assigns items, so take them back (the server runs
    # in this process).
    user = get_user_state_manager().get_user_state("fresh_unknown")
    user.assigned_instance_ids = set()
    user.instance_id_ordering = []
    r = s.post(f"{server.base_url}/updateinstance",
               json={"instance_id": "None", "annotations": {"s:a": "true"}}, timeout=5)
    assert r.status_code == 404, r.text
    stored = s.get(f"{server.base_url}/get_annotations",
                   params={"instance_id": "None"}, timeout=5)
    if stored.ok:
        assert not stored.json().get("label_annotations")


def test_a_real_id_still_saves_after_assignment(server):
    s = _fresh_session(server.base_url, "fresh_real")
    s.get(f"{server.base_url}/annotate", timeout=5)
    r = s.post(f"{server.base_url}/updateinstance",
               json={"instance_id": "1", "annotations": {"s:a": "true"}}, timeout=5)
    assert r.status_code == 200
