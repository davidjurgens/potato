"""
Server tests for D4 reviewer routing + kanban.

Boots a Flask server with review_workflow enabled (routing rule sends
error traces straight to in_review/alice), then exercises: startup
auto-enroll, the admin board API + kanban page, move/assign endpoints
(incl. audit + validation), the reviewer my-queue endpoint, and the
admin gate. Uses debug mode, which grants the admin-dashboard RBAC tier.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory, create_test_config, create_test_data_file,
)

PORT = 9725


def _review_config(test_dir):
    data_file = create_test_data_file(test_dir, [
        {"id": "ok-1", "text": "trace that succeeded", "status": "ok"},
        {"id": "err-1", "text": "trace that failed", "status": "error"},
        {"id": "ok-2", "text": "another fine trace", "status": "ok"},
    ])
    return create_test_config(
        test_dir,
        [{
            "annotation_type": "radio",
            "name": "verdict",
            "description": "verdict",
            "labels": ["good", "bad"],
        }],
        data_files=[data_file],
        additional_config={
            "item_properties": {"id_key": "id", "text_key": "text"},
            "review_workflow": {
                "enabled": True,
                "reviewers": ["alice", "bob"],
                "routing": [
                    {"when": [{"field": "status", "equals": "error"}],
                     "state": "in_review", "assign_to": "alice",
                     "priority": 10},
                ],
            },
        },
    )


class TestReviewWorkflowAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("review_workflow_api")
        cfg = _review_config(test_dir)
        server = FlaskTestServer(port=PORT, debug=True, config_file=cfg)
        if not server.start():
            pytest.fail("Failed to start server")
        yield server
        server.stop()

    def _session(self, server, name):
        s = requests.Session()
        s.post(f"{server.base_url}/register",
               data={"email": name, "pass": "x", "action": "signup"})
        s.post(f"{server.base_url}/auth",
               data={"email": name, "pass": "x", "action": "login"})
        return s

    def _board(self, s, server):
        r = s.get(f"{server.base_url}/admin/api/review/board")
        assert r.status_code == 200, r.text
        return r.json()["board"]

    def test_startup_enroll_and_routing(self, flask_server):
        s = self._session(flask_server, "rw_admin")
        b = self._board(s, flask_server)
        pending = {i["instance_id"] for i in b["pending"]}
        in_review = {x["instance_id"]: x for x in b["in_review"]}
        assert pending == {"ok-1", "ok-2"}
        assert set(in_review) == {"err-1"}
        assert in_review["err-1"]["assignee"] == "alice"
        assert in_review["err-1"]["priority"] == 10
        assert "failed" in in_review["err-1"]["preview"]

    def test_board_page_renders(self, flask_server):
        s = self._session(flask_server, "rw_admin2")
        r = s.get(f"{flask_server.base_url}/admin/review")
        assert r.status_code == 200
        assert "Review Board" in r.text

    def test_move_and_assign(self, flask_server):
        s = self._session(flask_server, "rw_admin3")
        r = s.post(f"{flask_server.base_url}/admin/api/review/move",
                   json={"instance_id": "ok-1", "state": "in_review"})
        assert r.status_code == 200, r.text
        assert r.json()["item"]["state"] == "in_review"

        r = s.post(f"{flask_server.base_url}/admin/api/review/assign",
                   json={"instance_id": "ok-1", "assignee": "bob",
                         "priority": 3})
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        assert item["assignee"] == "bob" and item["priority"] == 3

        # Reviewer queue reflects it (bob is a plain logged-in user)
        bob = self._session(flask_server, "bob")
        r = bob.get(f"{flask_server.base_url}/api/review/my_queue")
        assert r.status_code == 200, r.text
        ids = [i["instance_id"] for i in r.json()["queue"]]
        assert "ok-1" in ids

    def test_move_validation(self, flask_server):
        s = self._session(flask_server, "rw_admin4")
        r = s.post(f"{flask_server.base_url}/admin/api/review/move",
                   json={"instance_id": "ok-2", "state": "nonsense"})
        assert r.status_code == 400
        r = s.post(f"{flask_server.base_url}/admin/api/review/move",
                   json={"instance_id": "ghost", "state": "done"})
        assert r.status_code == 404

    def test_my_queue_requires_login(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/api/review/my_queue")
        assert r.status_code == 401
