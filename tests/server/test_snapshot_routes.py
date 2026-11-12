"""
/admin/api/snapshots on a running server: create, the unchanged reply, a new
snapshot after an annotation is saved, listing, and the admin guard.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "snapshot-admin-key"
SCHEME = {"annotation_type": "radio", "name": "sentiment", "description": "Sentiment?",
          "labels": ["positive", "negative"]}


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("snapshot_routes")
    data_file = create_test_data_file(test_dir, [
        {"id": f"item_{n}", "text": f"Text {n}"} for n in range(1, 4)])
    port = find_free_port(preferred_port=9897)
    config_file = create_test_config(test_dir, [SCHEME], data_files=[data_file], port=port,
                                     additional_config={"admin_api_key": ADMIN_KEY})
    srv = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not srv.start():
        pytest.fail("Failed to start server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def _admin(server, method, **kwargs):
    return requests.request(method, f"{server.base_url}/admin/api/snapshots",
                            headers={"X-API-Key": ADMIN_KEY}, **kwargs)


def test_snapshots_follow_the_annotations(server):
    first = _admin(server, "POST", json={"note": "before", "tag": "pilot"})
    assert first.status_code == 201, first.text
    first_id = first.json()["snapshot"]["id"]
    assert first.json()["snapshot"]["counts"]["items"] == 3

    same = _admin(server, "POST", json={"note": "again"})
    assert same.status_code == 200
    assert same.json() == {"unchanged": True, "snapshot": same.json()["snapshot"]}
    assert same.json()["snapshot"]["id"] == first_id

    session = requests.Session()
    session.post(f"{server.base_url}/register", data={"email": "ann", "pass": "pw"})
    session.post(f"{server.base_url}/auth", data={"email": "ann", "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    saved = session.post(f"{server.base_url}/updateinstance", json={
        "instance_id": "item_1", "annotations": {"sentiment:positive": "true"}})
    assert saved.status_code == 200, saved.text

    second = _admin(server, "POST", json={"note": "after one answer"})
    assert second.status_code == 201, second.text
    assert second.json()["snapshot"]["counts"]["annotations"] == 1
    assert second.json()["snapshot"]["previous"] == first_id

    listed = _admin(server, "GET").json()["snapshots"]
    assert [s["note"] for s in listed] == ["after one answer", "before"]
    assert listed[1]["tags"] == ["pilot"]
    assert "bundle_contents" not in listed[0]


def test_a_bad_tag_is_a_400(server):
    r = _admin(server, "POST", json={"tag": "has spaces", "force": True})
    assert r.status_code == 400
    assert "Tag" in r.json()["error"]


def test_snapshots_need_an_admin(server):
    assert requests.get(f"{server.base_url}/admin/api/snapshots").status_code == 403
    assert requests.post(f"{server.base_url}/admin/api/snapshots", json={}).status_code == 403
