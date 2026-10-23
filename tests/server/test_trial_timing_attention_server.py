"""
Audit 94, T4: a timed trial that runs out on an attention check is not graded.

A participant who only times out, through several attention checks with
warn 1 / block 2, must not be warned or blocked, on either the save path
(/updateinstance) or the skip path (next_instance).
"""

import json
import os
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

DEADLINE_MS = 300


@pytest.fixture(scope="module")
def attn_server(request):
    d = create_test_directory("trial_timing_attention_server")
    create_test_data_file(d, [{"id": f"w{i}", "text": f"word{i}"} for i in range(6)])
    with open(os.path.join(d, "attn.json"), "w") as f:
        json.dump([{"id": f"attn_{k}", "text": "Press F",
                    "expected_answer": {"decision": "word"}} for k in range(1, 4)], f)
    config_file = create_test_config(
        d,
        annotation_schemes=[{"name": "decision", "annotation_type": "radio",
                             "labels": ["word", "nonword"], "description": "Word?",
                             "label_requirement": {"required": True}}],
        data_files=["test_data.jsonl"],
        assignment_strategy="fixed_order",
        additional_config={
            "attention_checks": {"enabled": True, "items_file": "attn.json", "frequency": 1,
                                 "failure_handling": {"warn_threshold": 1, "block_threshold": 2}},
            "trial_timing": {"enabled": True, "trial_duration_ms": DEADLINE_MS,
                             "response": {"schema": "decision",
                                          "keys": {"f": "word", "j": "nonword"}}}},
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def test_timeouts_on_attention_checks_are_not_graded(attn_server):
    from potato.quality_control import get_quality_control_manager
    from potato.user_state_management import get_user_state_manager
    base = attn_server.base_url
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": "slow", "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": "slow", "pass": "p"}, timeout=5)
    qc = get_quality_control_manager()
    state = get_user_state_manager().get_user_state("slow")
    checks_seen = 0
    for _ in range(8):
        s.get(f"{base}/annotate", timeout=5)
        cur = state.get_current_instance()
        if cur is None:
            break
        iid = cur.get_id()
        checks_seen += int(qc.is_attention_check(iid))
        time.sleep(DEADLINE_MS / 1000 + 0.1)
        r = s.post(f"{base}/updateinstance", json={
            "instance_id": iid, "annotations": {}, "span_annotations": [],
            "trial": {"outcome": "timeout", "onset_epoch_ms": time.time() * 1000}}, timeout=5)
        assert r.json().get("status") != "blocked"
        s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": iid}, timeout=5)
    assert checks_seen >= 2, "precondition: the run passed through attention checks"
    assert not qc.is_user_blocked("slow")
    assert qc.get_attention_check_stats("slow").get("failed", 0) == 0
