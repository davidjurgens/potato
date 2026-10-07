"""
A real restart: start `potato start` as its own process, annotate, stop it,
start it again on the same output directory, and look.

No earlier test started a server twice on one output directory, so anything
held only in memory looked persistent.
"""

import json
import os
import signal
import subprocess
import sys
import time

import pytest
import requests

from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = 9820
BASE = f"http://127.0.0.1:{PORT}"

CONFIG = """
annotation_task_name: Restart test
task_dir: .
output_annotation_dir: annotation_output
data_files: [data/items.jsonl]
item_properties: {id_key: id, text_key: text}
user_config: {allow_all_users: true, users: []}
require_password: false
assignment_strategy: fixed_order
admin_api_key: restartkey
trace_ingestion: {enabled: true, api_key: tracekey}
annotation_schemes:
- {annotation_type: radio, name: ok, description: pick, labels: [good, bad]}
"""


def _start(task_dir):
    log = open(os.path.join(task_dir, "server.log"), "a")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(REPO, "potato", "flask_server.py"), "start",
         "config.yaml", "-p", str(PORT), "--host", "127.0.0.1"],
        cwd=task_dir, env=dict(os.environ, PYTHONPATH=REPO), stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            requests.get(BASE + "/", timeout=1)
            return proc
        except requests.RequestException:
            time.sleep(0.5)
    proc.kill()
    pytest.fail("server did not start; see " + os.path.join(task_dir, "server.log"))


def _stop(proc):
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _login(name):
    s = requests.Session()
    s.post(BASE + "/register", data={"email": name, "pass": "pw"}, timeout=5)
    s.post(BASE + "/auth", data={"email": name, "pass": "pw"}, timeout=5)
    s.get(BASE + "/annotate", timeout=5)
    return s


def _state(task_dir, user):
    with open(os.path.join(task_dir, "annotation_output", user, "user_state.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def task_dir():
    d = create_test_directory("tg2_restart")
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    with open(os.path.join(d, "data", "items.jsonl"), "w") as f:
        f.write(json.dumps({"id": "s0", "text": "static item"}) + "\n")
    with open(os.path.join(d, "config.yaml"), "w") as f:
        f.write(CONFIG)
    return d


def test_ingested_traces_are_still_there_after_a_restart(task_dir):
    proc = _start(task_dir)
    try:
        for tid in ("t1", "t2"):
            r = requests.post(BASE + "/api/traces/webhook", headers={"X-API-Key": "tracekey"},
                              json={"id": tid, "task_description": f"trace {tid}",
                                    "steps": [{"action": "x", "observation": "y"}]})
            assert r.status_code < 300, r.text
        s = _login("u1")
        for _ in range(3):
            iid = s.get(BASE + "/api/current_instance").json()["instance_id"]
            s.post(BASE + "/updateinstance",
                   json={"instance_id": iid, "annotations": {"ok:good": "good"}})
            s.post(BASE + "/annotate", data={"action": "next_instance"})
        before = _state(task_dir, "u1")["instance_id_ordering"]
        assert len(before) == 3, before
    finally:
        _stop(proc)

    proc = _start(task_dir)
    try:
        s = _login("u1")
        s.post(BASE + "/updateinstance", json={"instance_id": "s0", "annotations": {"ok:bad": "bad"}})
        after = _state(task_dir, "u1")["instance_id_ordering"]
        assert after == before
        assert set(_state(task_dir, "u1")["instance_id_to_label_to_value"]) == set(before)
    finally:
        _stop(proc)
