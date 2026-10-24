"""
Self-paced reading over HTTP: the timed page carries the item's regions, a
sentence with no question is finished by a `completed` record (progress moves
on without an answer), and the CSV export writes one row per region.
"""

import csv
import json
import os
import re
import shutil
import time
from pathlib import Path

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "advanced" / "self-paced-reading"


@pytest.fixture(scope="module")
def spr_server(request):
    d = create_test_directory("trial_presentation_server")
    shutil.copytree(EXAMPLE / "data", os.path.join(d, "data"))
    shutil.copy(EXAMPLE / "config.yaml", os.path.join(d, "config.yaml"))
    server = FlaskTestServer(config=os.path.join(d, "config.yaml"))
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    server.test_dir = d
    return server


def _login(base, name):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
    return s


def _trial_config(html):
    m = re.search(r"window\.potatoTrialTiming\s*=\s*(\{.*?\});", html, re.S)
    return json.loads(m.group(1)) if m else None


def _current(html):
    m = re.search(r'id="instance_id"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else None


def test_reading_flow_and_regions_export(spr_server):
    base = spr_server.base_url
    s = _login(base, "spr_reader")
    html = s.get(f"{base}/annotate", timeout=5).text
    cfg = _trial_config(html)
    assert cfg and cfg["presentation"]["regions"][:2] == ["The horse", "raced"]
    assert cfg["presentation"]["ask"] is True        # gp1 has a question

    # gp1: read, then answer the question
    s.post(f"{base}/updateinstance", timeout=5, json={
        "instance_id": "gp1", "annotations": {"comprehension:::Yes": "Yes"}, "span_annotations": [],
        "trial": {"outcome": "response", "key": "f", "label": "Yes", "rt_ms": 640,
                  "onset_epoch_ms": time.time() * 1000,
                  "regions": [{"index": i, "text": t, "rt_ms": 30 + i}
                              for i, t in enumerate(cfg["presentation"]["regions"])]}})
    s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": "gp1"}, timeout=5)
    html = s.get(f"{base}/annotate", timeout=5).text
    assert _current(html) == "gp2"
    cfg2 = _trial_config(html)
    assert cfg2["presentation"]["ask"] is False       # no question for gp2

    # gp2: read only; the required question is excused by `completed`
    r = s.post(f"{base}/updateinstance", timeout=5, json={
        "instance_id": "gp2", "annotations": {}, "span_annotations": [],
        "trial": {"outcome": "completed", "onset_epoch_ms": time.time() * 1000,
                  "regions": [{"index": i, "text": t, "rt_ms": 25}
                              for i, t in enumerate(cfg2["presentation"]["regions"])]}})
    assert r.status_code == 200
    s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": "gp2"}, timeout=5)
    assert _current(s.get(f"{base}/annotate", timeout=5).text) == "gp3"

    from potato.user_state_management import get_user_state_manager
    rec = get_user_state_manager().get_user_state("spr_reader").instance_id_to_trial["gp2"]
    assert rec["outcome"] == "completed" and rec["flags"] == [] and len(rec["regions"]) == 6

    from potato.export.cli import build_export_context
    from potato.export.tabular_exporter import CSVExporter
    out = os.path.join(spr_server.test_dir, "export")
    context = build_export_context(os.path.join(spr_server.test_dir, "config.yaml"))
    assert CSVExporter().export(context, out).success
    with open(os.path.join(out, "regions.csv")) as f:
        rows = [r for r in csv.DictReader(f) if r["user_id"] == "spr_reader"]
    gp2 = [r for r in rows if r["instance_id"] == "gp2"]
    assert [r["text"] for r in gp2][1] == "that was raced" and gp2[0]["trial_outcome"] == "completed"
    assert {r["instance_id"] for r in rows} == {"gp1", "gp2"}
