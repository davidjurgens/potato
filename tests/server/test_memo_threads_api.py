"""
Threads and issues over HTTP: reply, resolve, assign, the issue list, and
the admin's open-issue count.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "memo-threads-admin"
SCHEMES = [{"name": "label", "description": "L", "annotation_type": "radio", "labels": ["a", "b"]}]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("memo_threads_api")
    data_file = create_test_data_file(test_dir, [{"id": "i1", "text": "hello"},
                                                 {"id": "i2", "text": "second"},
                                                 {"id": "i3", "text": "third"}])
    config_file = create_test_config(test_dir, SCHEMES, data_files=[data_file],
                                     require_password=False,
                                     additional_config={"annotation_ui": {"memos": True},
                                                        "admin_api_key": ADMIN_KEY})
    srv = FlaskTestServer(config_file=config_file, debug=False)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def login(server, name):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": name, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": name, "pass": "pw"})
    return s


def test_an_issue_from_raised_to_resolved(server):
    base = f"{server.base_url}/api/memos"
    alice, bob, carol = login(server, "alice"), login(server, "bob"), login(server, "carol")
    issue = alice.post(base, json={"instance_id": "i1", "body": "box misses the mirror",
                                   "visibility": "shared", "issue": True,
                                   "anchor": {"shape": {"schema": "objects", "type": "bbox",
                                                        "label": "car", "coordinates": {
                                                            "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}}}}).json()["memo"]
    assert (issue["status"], issue["anchor"]["shape"]["label"]) == ("open", "car")

    reply = bob.post(f"{base}/{issue['id']}/reply", json={"body": "agreed, redrawing"})
    assert reply.status_code == 201 and reply.json()["memo"]["parent_id"] == issue["id"]

    assert carol.patch(f"{base}/{issue['id']}", json={"status": "resolved"}).status_code == 403
    assert bob.patch(f"{base}/{issue['id']}", json={"assignee": "bob"}).status_code == 403
    assigned = alice.patch(f"{base}/{issue['id']}", json={"assignee": "bob"}).json()["memo"]
    assert assigned["assignee"] == "bob"

    mine = bob.get(f"{base}/issues?status=open&assignee=me").json()["issues"]
    assert [m["id"] for m in mine] == [issue["id"]] and mine[0]["can_resolve"]

    overview = requests.get(f"{server.base_url}/admin/api/overview",
                            headers={"X-API-Key": ADMIN_KEY}).json()["overview"]
    assert (overview["open_issues"], overview["resolved_issues"]) == (1, 0)

    resolved = bob.patch(f"{base}/{issue['id']}", json={"status": "resolved"}).json()["memo"]
    assert (resolved["status"], resolved["resolved_by"]) == ("resolved", "bob")
    assert bob.get(f"{base}/issues?status=open&assignee=me").json()["issues"] == []

    thread = carol.get(f"{base}?instance_id=i1").json()["memos"]
    assert [m["body"] for m in thread] == ["box misses the mirror", "agreed, redrawing"]

    admin = requests.get(f"{server.base_url}/admin/api/memo_issues?status=resolved",
                         headers={"X-API-Key": ADMIN_KEY}).json()
    assert [m["id"] for m in admin["issues"]] == [issue["id"]]
    assert requests.get(f"{server.base_url}/admin/api/memo_issues").status_code == 403


def test_bad_requests_get_a_reason(server):
    base = f"{server.base_url}/api/memos"
    alice = login(server, "alice2")
    plain = alice.post(base, json={"instance_id": "i2", "body": "a plain note"}).json()["memo"]
    r = alice.patch(f"{base}/{plain['id']}", json={"status": "done"})
    assert r.status_code == 400 and "status must be one of" in r.json()["error"]
    r = alice.post(f"{base}/{plain['id']}/reply", json={"body": "  "})
    assert r.status_code == 400
    assert alice.post(f"{base}/nope/reply", json={"body": "x"}).status_code == 404


class RecordingEmitter:
    def __init__(self):
        self.events = []

    def emit(self, event_type, payload):
        self.events.append((event_type, payload["data"]))
        return 1


def test_assigning_an_issue_emits_one_webhook_and_lists_it_with_a_jump(server, monkeypatch):
    """memo.issue_assigned fires when an issue gains a new assignee, with ids
    only; the assignee's issue list says where each item is in their queue."""
    import potato.webhooks as webhooks
    recorder = RecordingEmitter()
    monkeypatch.setattr(webhooks, "get_webhook_emitter", lambda: recorder)
    base = f"{server.base_url}/api/memos"
    alice, dave = login(server, "alice"), login(server, "dave")
    dave.get(f"{server.base_url}/annotate")  # dave gets his queue

    alice.post(base, json={"instance_id": "i1", "body": "plain note", "visibility": "shared"})
    issue = alice.post(base, json={"instance_id": "i2", "body": "secret wording here",
                                   "visibility": "private", "issue": True,
                                   "assignee": "dave"}).json()["memo"]
    alice.patch(f"{base}/{issue['id']}", json={"assignee": "dave"})       # unchanged: no event
    alice.patch(f"{base}/{issue['id']}", json={"assignee": ""})           # cleared: no event
    alice.patch(f"{base}/{issue['id']}", json={"assignee": "dave"})       # assigned again
    assigned = [(e, d) for e, d in recorder.events if e == "memo.issue_assigned"]
    assert [(e, d["assignee"], d["assigned_by"], d["instance_id"]) for e, d in assigned] == [
        ("memo.issue_assigned", "dave", "alice", "i2"),
        ("memo.issue_assigned", "dave", "alice", "i2")]
    assert all("secret" not in str(d) for _e, d in assigned)

    [mine] = dave.get(f"{base}/issues?status=open&assignee=me").json()["issues"]
    assert mine["id"] == issue["id"] and mine["position"] == 1  # i2 is his second item
    # An item that exists but is not in dave's queue gets no jump position.
    login(server, "erin").get(f"{server.base_url}/annotate")
    elsewhere = alice.post(base, json={"instance_id": "i3", "body": "x",
                                       "issue": True, "assignee": "dave"}).json()["memo"]
    listed = {m["id"]: m for m in dave.get(f"{base}/issues?status=open&assignee=me").json()["issues"]}
    assert ("position" in listed[elsewhere["id"]]) == ("i3" in _queue(server, "dave"))

    unknown = alice.post(base, json={"instance_id": "no-such-item", "body": "x"})
    assert unknown.status_code == 400 and "no-such-item" in unknown.json()["error"]


def _queue(server, user):
    from potato.user_state_management import get_user_state_manager
    return list(get_user_state_manager().get_user_state(user).instance_id_ordering)
