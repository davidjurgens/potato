"""type: jspsych phases: normalization, validation, vendored files, the store."""

import copy
import os

import pytest

from potato.jspsych import store
from potato.jspsych.phase import (
    content_security_policy,
    register_jspsych_page,
    validate_jspsych_entry,
)
from potato.jspsych.vendored import CORE, PLUGINS, core_static_path, plugin_static_path
from potato.server_utils.config_module import (
    ConfigSecurityError,
    ConfigValidationError,
    _normalize_jspsych_phases,
)
from tests.helpers.test_utils import create_test_directory

STATIC = os.path.join(os.path.dirname(__file__), "..", "..", "potato", "static")


def _cfg(order, **entries):
    phases = {"order": order}
    phases.update(entries)
    return {"phases": phases}


class TestNormalize:
    def test_slot_inferred_from_position(self):
        cfg = _cfg(["pre", "annotation", "post"],
                   pre={"type": "jspsych", "timeline": "a.js"},
                   post={"type": "jspsych", "timeline": "b.js"})
        _normalize_jspsych_phases(cfg)
        assert cfg["phases"]["pre"]["type"] == "prestudy"
        assert cfg["phases"]["post"]["type"] == "poststudy"
        assert cfg["phases"]["pre"]["_kind"] == "jspsych"

    def test_explicit_slot(self):
        cfg = _cfg(["t", "annotation"], t={"type": "jspsych", "timeline": "a.js",
                                           "slot": "poststudy"})
        _normalize_jspsych_phases(cfg)
        assert cfg["phases"]["t"]["type"] == "poststudy"

    def test_bad_slot(self):
        cfg = _cfg(["t"], t={"type": "jspsych", "timeline": "a.js", "slot": "training"})
        with pytest.raises(ConfigValidationError):
            _normalize_jspsych_phases(cfg)

    def test_list_format(self):
        cfg = {"phases": [{"name": "t", "type": "jspsych", "timeline": "a.js"}]}
        _normalize_jspsych_phases(cfg)
        assert cfg["phases"][0]["type"] == "prestudy"

    def test_other_phases_untouched(self):
        cfg = _cfg(["c"], c={"type": "consent", "file": "c.json"})
        before = copy.deepcopy(cfg)
        _normalize_jspsych_phases(cfg)
        assert cfg == before


class TestValidate:
    BASE = {"type": "prestudy", "_kind": "jspsych", "timeline": "t.js"}

    def test_minimal_ok(self):
        validate_jspsych_entry("t", dict(self.BASE))

    @pytest.mark.parametrize("extra,match", [
        ({"timeline": ""}, "timeline"),
        ({"plugins": ["webgazer-calibrate"]}, "does not ship"),
        ({"plugins": "html-keyboard-response"}, "list"),
        ({"save": "always"}, "save"),
        ({"max_data_mb": 0}, "max_data_mb"),
        ({"max_data_mb": True}, "max_data_mb"),
        ({"allow_rerun": "yes"}, "allow_rerun"),
        ({"csp": {"extra_sources": ["http://cdn.example"]}}, "https"),
        ({"csp": {"extra_sources": ["https://x.org; script-src *"]}}, "https"),
        ({"csp": {"script_src": []}}, "extra_sources"),
        ({"csp": {"extra_sources": ["https://*"]}}, "wildcard"),
        ({"csp": {"extra_sources": ["https://a.com,http://b.com"]}}, "wildcard"),
        ({"timline": "x.js"}, "unknown key"),
    ])
    def test_refused(self, extra, match):
        entry = dict(self.BASE)
        entry.update(extra)
        with pytest.raises(ConfigValidationError, match=match):
            validate_jspsych_entry("t", entry)


class TestRegister:
    def _task(self, name):
        task_dir = create_test_directory(name)
        os.makedirs(os.path.join(task_dir, "tasks", "stim"), exist_ok=True)
        with open(os.path.join(task_dir, "tasks", "t.js"), "w") as f:
            f.write("window.potatoTimeline = [];")
        return task_dir

    def test_resolves_inside_task_dir(self):
        task_dir = self._task("jspsych_register_ok")
        config = {"task_dir": task_dir}
        entry = {"type": "prestudy", "_kind": "jspsych", "timeline": "tasks/t.js",
                 "assets_dir": "tasks/stim"}
        register_jspsych_page(config, "t", entry, lambda p: os.path.join(task_dir, p))
        spec = config["_jspsych_pages"]["t"]
        assert spec["timeline"].endswith(os.path.join("tasks", "t.js"))
        assert spec["max_bytes"] == 10 * 1024 * 1024

    def test_missing_file(self):
        task_dir = self._task("jspsych_register_missing")
        entry = {"type": "prestudy", "_kind": "jspsych", "timeline": "tasks/none.js"}
        with pytest.raises(ConfigValidationError, match="not found"):
            register_jspsych_page({"task_dir": task_dir}, "t", entry,
                                  lambda p: os.path.join(task_dir, p))

    def test_unresolvable_path_is_a_config_error(self):
        """Audit 94, J8: a raw FileNotFoundError traceback before."""
        task_dir = self._task("jspsych_register_unresolvable")
        entry = {"type": "prestudy", "_kind": "jspsych", "timeline": "tasks/gone.js"}

        def resolve(p):
            raise FileNotFoundError(p)
        with pytest.raises(ConfigValidationError, match="not found"):
            register_jspsych_page({"task_dir": task_dir}, "t", entry, resolve)

    def test_path_outside_task_dir(self):
        task_dir = self._task("jspsych_register_escape")
        outside = os.path.abspath(os.path.join(task_dir, "..", "..", "..", "conftest.py"))
        entry = {"type": "prestudy", "_kind": "jspsych", "timeline": outside}
        with pytest.raises((ConfigSecurityError, ConfigValidationError)):
            register_jspsych_page({"task_dir": task_dir}, "t", entry, lambda p: p)


class TestVendored:
    def test_every_shipped_file_exists(self):
        for fname in CORE:
            assert os.path.isfile(os.path.join(STATIC, core_static_path(fname))), fname
        for name in PLUGINS:
            path = os.path.join(STATIC, plugin_static_path(name))
            assert os.path.isfile(path), name

    def test_plugin_defines_its_global(self):
        for name, (_v, global_name, _sha) in PLUGINS.items():
            with open(os.path.join(STATIC, plugin_static_path(name)), encoding="utf-8") as f:
                head = f.read(200)
            assert f"var {global_name}=" in head, name


class TestCsp:
    def test_default_is_self_only(self):
        csp = content_security_policy({})
        assert "script-src 'self';" in csp and "connect-src 'self';" in csp
        assert "unsafe-eval" not in csp

    def test_extra_sources_never_reach_connect_src(self):
        csp = content_security_policy({"extra_sources": ["https://fonts.example"]})
        assert "script-src 'self' https://fonts.example" in csp
        assert "connect-src 'self';" in csp


class TestStore:
    def test_round_trip(self):
        task_dir = create_test_directory("jspsych_store")
        store.start_run(task_dir, project="p", user_id="u", phase="prestudy", page="t",
                        run_id="r1", attempt=1, conditions={"f": "a"})
        store.save_trials(task_dir, "r1", [{"rt": 300}], complete=False)
        assert store.get_run(task_dir, "r1")["status"] == "partial"
        store.save_trials(task_dir, "r1", [{"rt": 300}, {"rt": 410}], complete=True,
                          interaction=[{"event": "blur", "trial": 1, "time": 5}])
        run = store.get_run(task_dir, "r1")
        assert run["status"] == "complete" and run["n_trials"] == 2
        assert run["trials"][1]["rt"] == 410
        assert run["conditions"] == {"f": "a"}
        assert run["interaction"][0]["event"] == "blur"
        listed = store.list_runs(task_dir, "p")
        assert [r["run_id"] for r in listed] == ["r1"] and "trials" not in listed[0]
