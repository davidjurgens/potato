"""
Server tests for `type: jspsych` phase pages.

The page renders with its config block and a strict CSP, the timeline is
served byte-for-byte (a `{{` in author JS survives), the finish route refuses
anything but a same-origin JSON call for the participant's current run, the
task cannot be skipped by posting the phase form, a finished run advances the
participant and is idempotent, and the export carries the trials.
"""

import csv
import json
import os
import re

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

TIMELINE = """// {{ not a template }}
window.potatoTimeline = function (jsPsych, potato) {
  return [{type: jsPsychHtmlKeyboardResponse, stimulus: 'press a key'}];
};
"""

HEADERS = {"X-Potato-Navigation": "1"}


@pytest.fixture(scope="module")
def js_server(request):
    test_dir = create_test_directory("jspsych_phase_server")
    data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hello"}])
    tasks = os.path.join(test_dir, "tasks")
    os.makedirs(os.path.join(tasks, "stimuli"))
    with open(os.path.join(tasks, "stroop.js"), "w") as f:
        f.write(TIMELINE)
    with open(os.path.join(tasks, "stimuli", "red.txt"), "w") as f:
        f.write("RED")
    with open(os.path.join(test_dir, "secret.txt"), "w") as f:
        f.write("do not serve")
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "rating", "annotation_type": "radio",
                             "labels": ["good", "bad"], "description": "Rate."}],
        data_files=[data_file],
        phases={
            "order": ["stroop", "annotation"],
            "stroop": {"type": "jspsych", "timeline": os.path.join(tasks, "stroop.js"),
                       "plugins": ["html-keyboard-response"],
                       "assets_dir": os.path.join(tasks, "stimuli"),
                       "max_data_mb": 1},
        },
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def _login(base_url, username):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"action": "signup", "email": username, "pass": "pass"}, timeout=5)
    s.post(f"{base_url}/auth", data={"action": "login", "email": username, "pass": "pass"}, timeout=5)
    return s


def _page(s, base):
    r = s.get(f"{base}/", timeout=5)
    m = re.search(r'<script type="application/json" id="potato-runtime-config">(.*?)</script>',
                  r.text, re.S)
    return r, (json.loads(m.group(1)) if m else None)


def _finish(s, base, cfg, trials=None, **overrides):
    body = {"page": cfg["page"], "run_id": cfg["run_id"],
            "trials": trials if trials is not None else
            [{"trial_type": "html-keyboard-response", "trial_index": 0, "rt": 512,
              "response": "f", "stimulus": "press a key"}],
            "interaction": [{"event": "blur", "trial": 0, "time": 100}]}
    body.update(overrides)
    return s.post(f"{base}{cfg['endpoints']['finish']}", json=body, headers=HEADERS, timeout=5)


def test_page_renders_with_config_and_csp(js_server):
    s = _login(js_server.base_url, "js_render")
    r, cfg = _page(s, js_server.base_url)
    assert cfg is not None, "jsPsych config block missing"
    assert cfg["page"] == "stroop" and cfg["participant"] == "js_render"
    csp = r.headers.get("Content-Security-Policy", "")
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp
    assert "plugin-html-keyboard-response.js" in r.text
    assert "runtime-bridge.js" in r.text and "runtime-boot-jspsych.js" in r.text


def test_timeline_served_raw(js_server):
    s = _login(js_server.base_url, "js_timeline")
    _page(s, js_server.base_url)
    r = s.get(f"{js_server.base_url}/runtime/stroop/study", timeout=5)
    assert r.status_code == 200
    assert r.text == TIMELINE
    assert r.headers["Content-Type"].startswith("text/javascript")


def test_timeline_needs_a_session(js_server):
    r = requests.get(f"{js_server.base_url}/runtime/stroop/study", timeout=5)
    assert r.status_code == 404


def test_assets_served_and_traversal_refused(js_server):
    s = _login(js_server.base_url, "js_assets")
    _page(s, js_server.base_url)
    ok = s.get(f"{js_server.base_url}/runtime/stroop/assets/red.txt", timeout=5)
    assert ok.status_code == 200 and ok.text == "RED"
    for bad in ("../../secret.txt", "..%2F..%2Fsecret.txt", "../stroop.js"):
        r = s.get(f"{js_server.base_url}/runtime/stroop/assets/{bad}", timeout=5)
        assert r.status_code == 404, bad


def test_finish_refusals(js_server):
    s = _login(js_server.base_url, "js_refuse")
    _, cfg = _page(s, js_server.base_url)
    url = f"{js_server.base_url}{cfg['endpoints']['finish']}"
    body = {"page": "stroop", "run_id": cfg["run_id"], "trials": []}
    assert s.post(url, json=body, timeout=5).status_code == 400            # no header
    assert s.post(url, data="x", headers=HEADERS, timeout=5).status_code == 415
    assert _finish(s, js_server.base_url, cfg, page="other").status_code == 409
    assert _finish(s, js_server.base_url, cfg, run_id="stale").status_code == 409
    assert _finish(s, js_server.base_url, cfg, trials="nope").status_code == 400
    big = [{"x": "y" * 1000}] * 1200
    assert _finish(s, js_server.base_url, cfg, trials=big).status_code == 413
    assert requests.post(url, json=body, headers=HEADERS, timeout=5).status_code == 401


def test_task_cannot_be_skipped(js_server):
    s = _login(js_server.base_url, "js_skip")
    _page(s, js_server.base_url)
    s.post(f"{js_server.base_url}/annotate", json={"action": "next_instance"}, timeout=5)
    s.post(f"{js_server.base_url}/prestudy", data={}, timeout=5)
    _, cfg = _page(s, js_server.base_url)
    assert cfg is not None, "participant left the jsPsych page without finishing"


def test_finish_advances_and_is_idempotent(js_server):
    s = _login(js_server.base_url, "js_finish")
    _, cfg = _page(s, js_server.base_url)
    r = _finish(s, js_server.base_url, cfg)
    assert r.status_code == 200 and r.json()["redirect"]
    again = _finish(s, js_server.base_url, cfg)
    assert again.status_code == 200 and again.json().get("duplicate")
    html = s.get(f"{js_server.base_url}/", timeout=5).text
    assert "potato-runtime-config" not in html
    assert 'data-schema-name="rating"' in html


def test_reload_before_any_data_keeps_the_run(js_server):
    s = _login(js_server.base_url, "js_reload_empty")
    _, first = _page(s, js_server.base_url)
    _, second = _page(s, js_server.base_url)
    assert first["attempt"] == 1
    assert second["run_id"] == first["run_id"] and second["attempt"] == 1


def test_reload_after_data_starts_a_new_attempt(js_server):
    s = _login(js_server.base_url, "js_reload")
    _, first = _page(s, js_server.base_url)
    r = s.post(f"{js_server.base_url}{first['endpoints']['trial']}",
               json={"page": "stroop", "run_id": first["run_id"], "seq": 0,
                     "trial": {"trial_index": 0}}, headers=HEADERS, timeout=5)
    assert r.status_code == 200
    _, second = _page(s, js_server.base_url)
    assert second["attempt"] == first["attempt"] + 1
    assert second["run_id"] != first["run_id"]
    # The superseded run can no longer finish.
    assert _finish(s, js_server.base_url, first).status_code == 409


def test_incremental_trial_route(js_server):
    s = _login(js_server.base_url, "js_incr")
    _, cfg = _page(s, js_server.base_url)
    url = f"{js_server.base_url}{cfg['endpoints']['trial']}"
    for i in range(3):
        r = s.post(url, json={"page": "stroop", "run_id": cfg["run_id"], "seq": i,
                              "trial": {"trial_index": i}}, headers=HEADERS, timeout=5)
        assert r.status_code == 200 and r.json()["stored"] == i + 1


def test_export_contains_trials(js_server):
    s = _login(js_server.base_url, "js_export")
    _, cfg = _page(s, js_server.base_url)
    assert _finish(s, js_server.base_url, cfg).status_code == 200

    from potato.export.jspsych_exporter import JsPsychExporter
    from potato.export.base import ExportContext
    with open(js_server.config) as f:
        config = yaml.safe_load(f)
    from potato.server_utils.config_module import normalize_config_before_validation
    config = normalize_config_before_validation(config, os.path.dirname(js_server.config))
    from potato.flask_server import config as live_config
    config["task_dir"] = live_config.get("task_dir")
    out = os.path.join(os.path.dirname(js_server.config), "jspsych_export")
    ctx = ExportContext(config=config, annotations=[], items={}, schemas=[],
                        output_dir=out)
    ok, why = JsPsychExporter().can_export(ctx)
    assert ok, why
    result = JsPsychExporter().export(ctx, out)
    assert result.success, result.errors
    with open(os.path.join(out, "jspsych_trials.csv")) as f:
        rows = [r for r in csv.DictReader(f) if r["user_id"] == "js_export"]
    assert rows and rows[0]["rt"] == "512" and rows[0]["response"] == "f"
    with open(os.path.join(out, "jspsych_runs.csv")) as f:
        runs = [r for r in csv.DictReader(f) if r["user_id"] == "js_export"]
    assert runs[-1]["status"] == "complete"


def test_chunked_body_cannot_bypass_the_limit(js_server):
    """Audit 94, J3: a chunked request has no Content-Length."""
    s = _login(js_server.base_url, "js_chunked")
    _, cfg = _page(s, js_server.base_url)
    payload = json.dumps({"page": "stroop", "run_id": cfg["run_id"],
                          "trials": [{"x": "y" * 1000}] * 1500}).encode()

    def gen():
        for i in range(0, len(payload), 65536):
            yield payload[i:i + 65536]
    r = s.post(f"{js_server.base_url}{cfg['endpoints']['finish']}", data=gen(),
               headers={**HEADERS, "Content-Type": "application/json"}, timeout=10)
    assert r.status_code == 413


def test_trial_seq_bounded(js_server):
    """Audit 94, J4."""
    s = _login(js_server.base_url, "js_seq")
    _, cfg = _page(s, js_server.base_url)
    url = f"{js_server.base_url}{cfg['endpoints']['trial']}"
    for seq in (5000000, True):
        r = s.post(url, json={"page": "stroop", "run_id": cfg["run_id"], "seq": seq,
                              "trial": {"x": 1}}, headers=HEADERS, timeout=5)
        assert r.status_code == 400, seq


def test_late_trial_post_does_not_downgrade_a_finished_run(js_server):
    """Audit 94, J1."""
    from potato.runtimes import store
    s = _login(js_server.base_url, "js_race")
    _, cfg = _page(s, js_server.base_url)
    assert _finish(s, js_server.base_url, cfg).status_code == 200
    with open(js_server.config) as f:
        task_dir = os.path.dirname(js_server.config)
    from potato.flask_server import config as live_config
    task_dir = live_config.get("task_dir") or task_dir
    store.save_trials(task_dir, cfg["run_id"], [{"late": True}], complete=False)
    run = store.get_run(task_dir, cfg["run_id"])
    assert run["status"] == "complete" and run["n_trials"] == 1 and "late" not in run["trials"][0]


def test_refused_post_does_not_orphan_the_open_tab(js_server):
    """Audit 94, J2: the 400 re-render started a new run."""
    s = _login(js_server.base_url, "js_orphan")
    _, cfg = _page(s, js_server.base_url)
    r = s.post(f"{js_server.base_url}{cfg['endpoints']['trial']}",
               json={"page": "stroop", "run_id": cfg["run_id"], "seq": 0,
                     "trial": {"trial_index": 0}}, headers=HEADERS, timeout=5)
    assert r.status_code == 200
    s.post(f"{js_server.base_url}/prestudy", data={}, timeout=5)
    assert _finish(s, js_server.base_url, cfg).status_code == 200


def test_old_jspsych_urls_say_where_they_moved(js_server):
    """Audit 96 R4."""
    base = js_server.base_url
    r = requests.get(f"{base}/jspsych/stroop/timeline", timeout=5)
    assert r.status_code == 410 and r.json()["moved_to"] == "/runtime/stroop/study"
    r = requests.post(f"{base}/api/jspsych/finish", json={}, timeout=5)
    assert r.status_code == 410 and r.json()["moved_to"] == "/api/runtime/finish"
    for path in ("/jspsych/stroop", "/jspsych/stroop/"):
        r = requests.get(f"{base}{path}", timeout=5, allow_redirects=False)
        assert r.status_code == 410 and r.json()["moved_to"] == "/runtime/stroop/study", path
