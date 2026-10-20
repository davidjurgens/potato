"""
/admin/api/throughput on a running server: events posted through
/api/track_interactions, answers through /updateinstance, rates read back.
"""

import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "throughput-admin"
SCHEME = {"annotation_type": "radio", "name": "s", "description": "S", "labels": ["a", "b"]}


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("throughput_server")
    data_file = create_test_data_file(test_dir, [{"id": f"item_{n}", "text": f"t{n}"} for n in (1, 2, 3)])
    config_file = create_test_config(test_dir, [SCHEME], data_files=[data_file],
                                     additional_config={"admin_api_key": ADMIN_KEY})
    srv = FlaskTestServer(config_file=config_file, debug=False)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def test_rates_from_tracked_events(server):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": "ann", "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": "ann", "pass": "pw"})
    s.get(f"{server.base_url}/annotate")
    t0 = time.time() - 600
    for iid, gap in (("item_1", 40), ("item_2", 80)):
        r = s.post(f"{server.base_url}/api/track_interactions", json={"instance_id": iid, "events": [
            {"event_type": "click", "target": "label:a", "timestamp": t0},
            {"event_type": "click", "target": "label:b", "timestamp": t0 + gap}]})
        assert r.status_code == 200, r.text
        saved = s.post(f"{server.base_url}/updateinstance",
                       json={"instance_id": iid, "annotations": {"s:a": "a"}})
        assert saved.status_code == 200, saved.text

    data = requests.get(f"{server.base_url}/admin/api/throughput",
                        headers={"X-API-Key": ADMIN_KEY}).json()
    [ann] = data["annotators"]
    # 2 items in 120 s of active time -> 60 per hour; median of 40 and 80 s.
    assert (ann["annotator"], ann["items"], ann["items_timed"]) == ("ann", 2, 2)
    assert (ann["items_per_active_hour"], ann["median_active_seconds"]) == (60.0, 60.0)
    assert data["review_enabled"] is False
    # Both items fall in the 30-60 s and 60-120 s bins of the distribution.
    dist = ann["time_distribution"]
    assert {b["from"]: b["count"] for b in dist["bins"] if b["count"]} == {30: 1, 60: 1}
    assert requests.get(f"{server.base_url}/admin/api/throughput").status_code == 403
