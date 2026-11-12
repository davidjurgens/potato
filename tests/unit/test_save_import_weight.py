"""A plain autosave should not initialize the disabled active-learning stack."""

import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


SAVE_IN_FRESH_PROCESS = textwrap.dedent(r'''
    import json
    import os
    from pathlib import Path
    import sys
    import time
    import types
    import uuid

    # The parent test helpers enable a path-validation bypass. This process
    # exercises the ordinary WSGI factory with its real task directory.
    os.environ.pop("POTATO_SKIP_CONFIG_PATH_VALIDATION", None)

    from tests.helpers.test_utils import TestConfigManager
    from potato.flask_server import create_app, config

    mode = sys.argv[1]
    schemes = [{"name": "choice", "annotation_type": "radio",
                "description": "Choose", "labels": ["yes", "no"]}]
    extra = {} if mode == "absent" else {"active_learning": {"enabled": False}}
    with TestConfigManager("save_import_" + uuid.uuid4().hex[:8], schemes,
                           additional_config=extra) as cfg:
        app = create_app(cfg.config_path)
        app.config["TESTING"] = True
        client = app.test_client()
        registered = client.post("/register", data={
            "email": "save_import_test", "pass": "synthetic-password",
        }, follow_redirects=True)
        assert registered.status_code == 200
        before = [name for name in ("potato.active_learning_manager", "sklearn")
                  if name in sys.modules]
        calls = []
        if mode in ("enabled", "failing_trigger"):
            # Exercise the enabled route without starting a training worker.
            config["active_learning"] = {"enabled": True}
            def trigger():
                calls.append("triggered")
                if mode == "failing_trigger":
                    raise RuntimeError("synthetic training trigger failure")
            manager = types.SimpleNamespace(
                config=types.SimpleNamespace(enabled=True),
                check_and_trigger_training=trigger)
            module = types.ModuleType("potato.active_learning_manager")
            module.get_active_learning_manager = lambda: manager
            sys.modules[module.__name__] = module
        start = time.perf_counter()
        response = client.post("/updateinstance", json={
            "instance_id": "1", "annotations": {"choice:::yes": "yes"},
        })
        elapsed = time.perf_counter() - start
        stored = json.loads((Path(cfg.test_dir) / "output" / "save_import_test"
                             / "user_state.json").read_text())
        print("SAVE_RESULT " + json.dumps({
            "status": response.status_code,
            "labels_saved": len(stored["instance_id_to_label_to_value"]["1"]),
            "before": before,
            "after": [name for name in ("potato.active_learning_manager", "sklearn")
                      if name in sys.modules],
            "trigger_calls": len(calls), "elapsed_seconds": elapsed,
        }))
''')


@pytest.mark.timeout(120)
@pytest.mark.parametrize("mode", ["absent", "disabled", "enabled", "failing_trigger"])
def test_annotation_save_only_triggers_enabled_active_learning(mode):
    result = subprocess.run(
        [sys.executable, "-c", SAVE_IN_FRESH_PROCESS, mode],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    record = next(line for line in result.stdout.splitlines()
                  if line.startswith("SAVE_RESULT "))
    info = json.loads(record.removeprefix("SAVE_RESULT "))
    assert info["status"] == 200
    assert info["labels_saved"] == 1
    assert info["before"] == []
    if mode in ("absent", "disabled"):
        assert info["after"] == [], info
        assert info["trigger_calls"] == 0
    else:
        assert info["trigger_calls"] == 1
