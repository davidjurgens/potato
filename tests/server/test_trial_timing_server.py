"""
Timed trials over HTTP: the annotation page carries the trial config and no
Previous button, a real timeout advances an item with no answer, a timeout
claimed before the deadline does not, and a participant whose last item
times out still finishes the task.
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

DEADLINE_MS = 400


@pytest.fixture(scope="module")
def tt_server(request):
    test_dir = create_test_directory("trial_timing_server")
    data_file = create_test_data_file(test_dir, [
        {"id": "w1", "text": "garden"}, {"id": "w2", "text": "blorf"}])
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "decision", "annotation_type": "radio",
                             "labels": ["word", "nonword"], "description": "Word?",
                             "label_requirement": {"required": True}}],
        data_files=[data_file],
        assignment_strategy="fixed_order",
        additional_config={"trial_timing": {
            "enabled": True, "fixation_ms": 100, "trial_duration_ms": DEADLINE_MS,
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


def _save(s, base, iid, trial, annotations=None):
    return s.post(f"{base}/updateinstance", json={
        "instance_id": iid, "annotations": annotations or {}, "span_annotations": [],
        "trial": trial}, timeout=5)


def _next(s, base, iid):
    return s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": iid},
                  allow_redirects=True, timeout=5)


def test_page_has_trial_config_and_no_previous(tt_server):
    s = _login(tt_server.base_url, "tt_page")
    html = s.get(f"{tt_server.base_url}/annotate", timeout=5).text
    assert "window.potatoTrialTiming" in html
    assert "trial-timing.js" in html
    assert 'id="prev-btn"' not in html
    assert "potato-trial-pending" in html


def test_timeout_advances_and_last_item_finishes(tt_server):
    base = tt_server.base_url
    s = _login(base, "tt_timeout")
    seen = []
    for _ in range(2):
        html = s.get(f"{base}/annotate", timeout=5).text
        iid = _current_id(html)
        assert iid and iid not in seen
        seen.append(iid)
        time.sleep(DEADLINE_MS / 1000 + 0.1)
        r = _save(s, base, iid, {"outcome": "timeout", "onset_epoch_ms": time.time() * 1000})
        assert r.status_code == 200, r.text
        _next(s, base, iid)
    final = s.get(f"{base}/", timeout=5)
    assert "potatoTrialTiming" not in final.text, "participant stuck on a timed-out item"
    from potato.user_state_management import get_user_state_manager
    us = get_user_state_manager().get_user_state("tt_timeout")
    assert set(us.instance_id_to_trial) == set(seen)
    assert all(r["outcome"] == "timeout" and not r["flags"]
               for r in us.instance_id_to_trial.values())


def test_forged_early_timeout_does_not_skip(tt_server):
    base = tt_server.base_url
    s = _login(base, "tt_forged")
    iid = _current_id(s.get(f"{base}/annotate", timeout=5).text)
    r = _save(s, base, iid, {"outcome": "timeout", "onset_epoch_ms": 1})
    assert r.status_code == 200
    _next(s, base, iid)
    again = _current_id(s.get(f"{base}/annotate", timeout=5).text)
    assert again == iid, "an instant timeout let the participant skip the item"
    from potato.user_state_management import get_user_state_manager
    rec = get_user_state_manager().get_user_state("tt_forged").instance_id_to_trial[iid]
    assert "timeout_too_early" in rec["flags"]


def test_response_record_and_label_stored(tt_server):
    base = tt_server.base_url
    s = _login(base, "tt_response")
    iid = _current_id(s.get(f"{base}/annotate", timeout=5).text)
    time.sleep(0.2)
    r = _save(s, base, iid, {"outcome": "response", "key": "f", "label": "word",
                             "rt_ms": 150.5, "onset_epoch_ms": 5},
              annotations={"decision:::word": "word"})
    assert r.status_code == 200
    from potato.user_state_management import get_user_state_manager
    us = get_user_state_manager().get_user_state("tt_response")
    rec = us.instance_id_to_trial[iid]
    assert rec["rt_ms"] == 150.5 and rec["label"] == "word" and rec["flags"] == []
    assert us.instance_id_to_behavioral_data[iid].trial["rt_ms"] == 150.5
