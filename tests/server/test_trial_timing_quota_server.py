"""
Audit 94, T1 and T2, over HTTP.

T1: a deadline set only through item_overrides is the deadline the server
checks; an honest timeout under it lets the participant move on.
T2: a participant who lets every trial run out does not use up the items:
with max_annotations_per_item 1, a second participant still gets them.
"""

import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)


@pytest.fixture(scope="module")
def quota_server(request):
    test_dir = create_test_directory("trial_timing_quota_server")
    data_file = create_test_data_file(test_dir, [
        {"id": f"w{i}", "text": f"word{i}", "dl": 300} for i in range(3)])
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "decision", "annotation_type": "radio",
                             "labels": ["word", "nonword"], "description": "Word?",
                             "label_requirement": {"required": True}}],
        data_files=[data_file],
        assignment_strategy="fixed_order",
        max_annotations_per_item=1,
        additional_config={"trial_timing": {
            "enabled": True,
            "item_overrides": {"trial_duration_ms": "dl"},
            "response": {"schema": "decision", "keys": {"f": "word", "j": "nonword"}}}},
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def _login(base, name):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "pass"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "pass"}, timeout=5)
    return s


def _current_id(html):
    import re
    m = re.search(r'id="instance_id"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else None


def test_item_override_deadline_and_quota(quota_server):
    base = quota_server.base_url
    first = _login(base, "times_out")
    seen = []
    for _ in range(3):
        iid = _current_id(first.get(f"{base}/annotate", timeout=5).text)
        assert iid and iid not in seen, "stuck on a timed-out item (T1)"
        seen.append(iid)
        time.sleep(0.45)
        r = first.post(f"{base}/updateinstance", json={
            "instance_id": iid, "annotations": {}, "span_annotations": [],
            "trial": {"outcome": "timeout", "onset_epoch_ms": time.time() * 1000}}, timeout=5)
        assert r.status_code == 200
        first.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": iid},
                   timeout=5)
    from potato.user_state_management import get_user_state_manager
    us = get_user_state_manager().get_user_state("times_out")
    assert all(not r["flags"] for r in us.instance_id_to_trial.values()), \
        [r["flags"] for r in us.instance_id_to_trial.values()]

    second = _login(base, "gets_items")
    html = second.get(f"{base}/annotate", timeout=5).text
    assert _current_id(html) in seen, "timeouts used up the items (T2)"
