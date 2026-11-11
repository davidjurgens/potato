"""``collab.conflict_policy: reject`` over HTTP.

A save that changes something a teammate changed first keeps the teammate's
value and names them. The rest of that save still goes in, so the member's
other edits are not lost; a save whose only change was refused gets a 409.
A save based on the value the page now shows (the per-key base the page sends
after a refusal) goes through.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

SID = "GREEN"


@pytest.fixture(scope="module")
def flask_server():
    test_dir = create_test_directory("collab_reject_api")
    create_test_data_file(test_dir, [{"id": f"r{i}", "text": f"Item {i}."} for i in range(1, 4)])
    schemes = [
        {"annotation_type": "radio", "name": "stance", "description": "Stance?",
         "labels": ["pro", "con"]},
        {"annotation_type": "text", "name": "note", "description": "Note"},
    ]
    config_path = create_test_config(test_dir, schemes, additional_config={
        "collab": {"enabled": True, "conflict_policy": "reject",
                   "teams": [{"id": "green", "members": ["ana", "ben"], "leader": "ana",
                              "items": ["r1", "r2", "r3"]}]}})
    server = FlaskTestServer(port=9095, config_file=config_path)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    yield server
    server.stop()


def login(server, name):
    s = requests.Session()
    user = {"email": name, "pass": "pass"}
    s.post(f"{server.base_url}/register", data=user, timeout=5)
    s.post(f"{server.base_url}/auth", data=user, timeout=5)
    s.headers.update({"Origin": server.base_url})
    return s


def item(server, s, iid):
    return s.get(f"{server.base_url}/collab/api/{SID}/item/{iid}", timeout=10).json()


def save(server, s, iid, annotations, base_rev, stale=None):
    collab = {"sid": SID, "base_rev": base_rev}
    if stale:
        collab["stale"] = stale
    return s.post(f"{server.base_url}/updateinstance", timeout=10, json={
        "instance_id": iid, "annotations": annotations, "collab": collab})


def test_the_refused_value_keeps_the_teammates_and_the_rest_goes_in(flask_server):
    ana, ben = login(flask_server, "ana"), login(flask_server, "ben")
    base = item(flask_server, ana, "r1")["rev"]
    assert save(flask_server, ana, "r1", {"stance:::pro": "pro"}, base).status_code == 200

    # Ben's page still showed no stance; he picked "con" and typed a note.
    r = save(flask_server, ben, "r1", {"stance:::con": "con", "note:::text_box": "hm"}, base)
    assert r.status_code == 200, r.text
    info = r.json()["collab"]
    assert info["rejected"] is True and info["partial"] is True
    assert [c["user"] for c in info["conflicts"]] == ["ana"]
    stored = item(flask_server, ana, "r1")
    assert stored["answer"] == {"L:stance:::pro": "pro", "L:note:::text_box": "hm"}
    # Only ben's note is in his edit; he did not overwrite anyone.
    last = stored["history"][-1]
    assert last["user"] == "ben"
    assert last["overwrote"] == []
    assert len(last["summary"]) == 1 and "note" in last["summary"][0], last["summary"]


def test_a_save_whose_only_change_was_refused_gets_409(flask_server):
    ana, ben = login(flask_server, "ana"), login(flask_server, "ben")
    base = item(flask_server, ana, "r3")["rev"]
    assert save(flask_server, ana, "r3", {"stance:::pro": "pro"}, base).status_code == 200
    r = save(flask_server, ben, "r3", {"stance:::con": "con"}, base)
    assert r.status_code == 409
    body = r.json()
    assert body["collab"]["rejected"] is True
    assert "partial" not in body["collab"]
    assert "ana" in body["message"]
    stored = item(flask_server, ana, "r3")
    assert stored["answer"] == {"L:stance:::pro": "pro"}

    # His page now shows ana's stance (the scheme's base is the current
    # revision); a change he makes after that is his own, and goes in.
    r = save(flask_server, ben, "r3", {"stance:::con": "con"},
             base, stale={"L:stance": stored["rev"]})
    assert r.status_code == 200, r.text
    assert item(flask_server, ana, "r3")["answer"] == {"L:stance:::con": "con"}


def test_saves_to_different_things_are_never_refused(flask_server):
    ana, ben = login(flask_server, "ana"), login(flask_server, "ben")
    base = item(flask_server, ana, "r2")["rev"]
    assert save(flask_server, ana, "r2", {"stance:::con": "con"}, base).status_code == 200
    assert save(flask_server, ben, "r2", {"note:::text_box": "fine"}, base).status_code == 200
