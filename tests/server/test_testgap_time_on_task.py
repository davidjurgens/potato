"""
Time on task reaches the admin dashboard from the events the browser sends.

`BehavioralData.total_time_ms` was only ever set by `finalize_session()`, which
nothing called, so every instance stored 0. The dashboard showed 0h worked and
0 annotations per hour, behavioural analytics counted every instance as a
0-second answer, and the suspicion score -- built on the server's own request
handling time -- put every annotator at "High". This drives the real routes: a
login, the events `interaction_tracker.js` posts, a save, and the admin APIs.
"""

import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (create_test_config, create_test_data_file,
                                      create_test_directory)

ADMIN_KEY = "time_on_task_admin_key"


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("testgap_time_on_task")
    data_file = create_test_data_file(
        test_dir, [{"id": f"tot_{i}", "text": f"Item {i}."} for i in range(4)],
        "tot.jsonl")
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "sentiment", "annotation_type": "radio",
                             "labels": ["positive", "negative"],
                             "description": "Sentiment"}],
        data_files=[data_file],
        assignment_strategy="fixed_order",
        admin_api_key=ADMIN_KEY,
    )
    srv = FlaskTestServer(config=config_file)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()


def _login(base, user):
    s = requests.Session()
    s.post(f"{base}/register", data={"email": user, "pass": "pw"}, timeout=5)
    s.post(f"{base}/auth", data={"email": user, "pass": "pw"}, timeout=5)
    s.get(f"{base}/annotate", timeout=5)
    return s


def _events(instance_id, start_ms, offsets_s):
    names = ["instance_load"] + ["label:positive"] * (len(offsets_s) - 1)
    kinds = ["navigation"] + ["click"] * (len(offsets_s) - 1)
    return [{"event_type": k, "target": n, "instance_id": instance_id,
             "timestamp": (start_ms + o * 1000) / 1000.0,
             "client_timestamp": start_ms + o * 1000}
            for k, n, o in zip(kinds, names, offsets_s)]


def test_time_on_an_item_reaches_the_dashboard(server):
    base = server.base_url
    s = _login(base, "tot_worker")
    start = int(time.time() * 1000)
    # Three items, eight seconds each, saved as the page saves them.
    for n in range(3):
        iid = f"tot_{n}"
        r = s.post(f"{base}/api/track_interactions", json={
            "instance_id": iid,
            "events": _events(iid, start + n * 10_000, [0, 3, 8])}, timeout=5)
        assert r.status_code == 200, r.text
        s.post(f"{base}/updateinstance", json={
            "instance_id": iid, "annotations": {"sentiment:::positive": "positive"}},
            timeout=5)
        time.sleep(1.1)  # the next item starts a second after this one

    headers = {"X-API-Key": ADMIN_KEY}
    annotators = requests.get(f"{base}/admin/api/annotators", headers=headers,
                              timeout=10).json()["annotators"]
    me = next(a for a in annotators if a["user_id"] == "tot_worker")
    assert me["total_seconds"] == pytest.approx(24, abs=0.5)
    # Items one second apart: under the 2 s burst threshold, over 0.5 s fast.
    assert me["suspicious_level"] != "Not enough data"
    assert me["fast_actions_count"] == 0

    behaviour = requests.get(f"{base}/admin/api/behavioral_analytics",
                             headers=headers, timeout=10).json()
    stats = next(u for u in behaviour["users"] if u["user_id"] == "tot_worker")
    assert stats["avg_time_sec"] == pytest.approx(8, abs=0.1)
    assert stats["fast_annotation_rate"] == 0.0


def test_a_worker_with_one_item_is_not_scored(server):
    base = server.base_url
    s = _login(base, "tot_single")
    s.post(f"{base}/updateinstance", json={
        "instance_id": "tot_0", "annotations": {"sentiment:::negative": "negative"}},
        timeout=5)
    annotators = requests.get(f"{base}/admin/api/annotators",
                              headers={"X-API-Key": ADMIN_KEY}, timeout=10).json()
    me = next(a for a in annotators["annotators"] if a["user_id"] == "tot_single")
    assert me["suspicious_score"] is None
    assert me["suspicious_level"] == "Not enough data"


def test_a_finished_annotator_and_their_history_survive_a_restart(server):
    """The move to DONE was saved only for crowd studies, and the annotation
    history was never saved, so a restart put a finished annotator back in
    the annotation phase with an empty history."""
    import json
    import os
    from potato.user_state_management import InMemoryUserState

    base = server.base_url
    s = _login(base, "tot_finisher")
    for n in range(4):
        s.post(f"{base}/updateinstance", json={
            "instance_id": f"tot_{n}",
            "annotations": {"sentiment:::positive": "positive"}}, timeout=5)
        s.post(f"{base}/annotate", data={"action": "next_instance"}, timeout=5)
    s.get(f"{base}/done", timeout=5)

    import yaml
    with open(server.config) as fh:
        cfg = yaml.safe_load(fh)
    out_dir = cfg["output_annotation_dir"]
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(os.path.dirname(server.config), out_dir)
    user_dir = os.path.join(out_dir, "tot_finisher")
    with open(os.path.join(user_dir, "user_state.json")) as fh:
        saved = json.load(fh)
    reloaded = InMemoryUserState.load(user_dir)
    assert str(reloaded.get_phase()) == "done", saved.get("current_phase_and_page")
    assert len(reloaded.get_annotation_history()) >= 4
