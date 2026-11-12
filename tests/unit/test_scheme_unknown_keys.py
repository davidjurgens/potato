"""
Keys an annotation scheme's type does not declare are reported.

`validate_unknown_keys` stops at `annotation_schemes`, because what a scheme may
carry depends on its `annotation_type`. Before `validate_scheme_keys`, an
invented or misspelled key on a scheme (`totally_made_up: 3` on a radio,
`default_low` on a range_slider, `items_key` on a ranking) loaded silently, did
nothing, and passed `potato validate --strict`. Reported by the potato-skill
agent, whose authoring sessions produce exactly these plausible-but-wrong keys.

The accepted set is the registry's, so these tests also pin the three keys the
registry was missing although code reads them: `ai_support` and
`keybinding_strategy` on every type, `propagation` on video_annotation, and
`option_randomization` on multirate.
"""

import logging
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from potato.server_utils.config_module import validate_scheme_keys
from potato.server_utils.schemas.registry import (
    INTERNAL_SCHEME_FIELDS,
    schema_registry,
)
from potato.validate_cli import validate_config_file

REPO_ROOT = Path(__file__).resolve().parents[2]
LOGGER = "potato.server_utils.config_module"


def warnings_for(caplog, config):
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        validate_scheme_keys(config)
    return [r.getMessage() for r in caplog.records
            if "Unrecognized config key" in r.getMessage()]


def radio(**extra):
    scheme = {"annotation_type": "radio", "name": "s", "description": "d",
              "labels": ["a", "b"]}
    scheme.update(extra)
    return scheme


class TestTheCheck:
    def test_an_invented_key_is_reported(self, caplog):
        [msg] = warnings_for(caplog, {"annotation_schemes": [radio(totally_made_up=3)]})
        assert "annotation_schemes[s].totally_made_up" in msg
        assert "radio" in msg

    def test_a_typo_gets_a_suggestion(self, caplog):
        [msg] = warnings_for(caplog, {"annotation_schemes": [
            {"annotation_type": "radio", "name": "s", "description": "d",
             "lables": ["a"]}]})
        assert "Did you mean" in msg and "'labels'" in msg

    def test_declared_keys_pass(self, caplog):
        assert warnings_for(caplog, {"annotation_schemes": [
            radio(horizontal=True, has_free_response=True)]}) == []

    def test_universal_and_internal_keys_pass(self, caplog):
        scheme = radio(label_requirement={"required": True},
                       display_logic={"show_when": []},
                       ai_support={"confidence_threshold": 0.7},
                       keybinding_strategy="mnemonic")
        for key in INTERNAL_SCHEME_FIELDS:
            scheme[key] = None
        assert warnings_for(caplog, {"annotation_schemes": [scheme]}) == []

    @pytest.mark.parametrize("type_name,key", [
        ("video_annotation", "propagation"),        # routes.py SAM 2 propagation
        ("multirate", "option_randomization"),       # presentation_order.py
        ("likert", "ai_support"),                    # ai_cache.py visual hints
        ("multiselect", "keybinding_strategy"),      # keybinding_allocator.py
    ])
    def test_keys_the_code_reads_are_declared(self, type_name, key):
        assert key in schema_registry.get_accepted_fields(type_name)

    def test_schemes_inside_phases_are_checked(self, caplog):
        config = {"phases": {"order": ["main"], "main": {
            "type": "annotation", "annotation_schemes": [radio(bogus=1)]}}}
        [msg] = warnings_for(caplog, config)
        assert "bogus" in msg

    def test_an_unregistered_type_is_left_to_the_type_check(self, caplog):
        assert warnings_for(caplog, {"annotation_schemes": [
            {"annotation_type": "no_such_type", "name": "s", "anything": 1}]}) == []

    def test_malformed_containers_do_not_crash(self, caplog):
        for config in ({"annotation_schemes": None},
                       {"annotation_schemes": ["not a dict", 3]},
                       {"annotation_schemes": [{"name": "no type"}]}):
            assert warnings_for(caplog, config) == []


class TestStrictValidation:
    def write(self, tmp_path, scheme):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "d.jsonl").write_text('{"id": "1", "text": "hi"}\n')
        config = {
            "annotation_task_name": "probe",
            "task_dir": ".",
            "output_annotation_dir": "out/",
            "data_files": ["data/d.jsonl"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [scheme],
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(config))
        return str(path)

    def test_an_invented_key_fails_strict(self, tmp_path):
        report = validate_config_file(self.write(tmp_path, radio(totally_made_up=3)))
        assert any("totally_made_up" in k for k in report.unknown_keys), report.to_dict()

    def test_a_clean_scheme_has_no_unknown_keys(self, tmp_path):
        report = validate_config_file(self.write(tmp_path, radio()))
        assert report.unknown_keys == [], report.to_dict()


def _tracked(pattern):
    try:
        out = subprocess.check_output(["git", "ls-files", pattern], cwd=REPO_ROOT)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    return [REPO_ROOT / p for p in out.decode().split()]


def _schemes(node):
    if isinstance(node, dict):
        if isinstance(node.get("annotation_type"), str):
            yield node
        for value in node.values():
            yield from _schemes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _schemes(value)


def _undeclared(doc):
    for scheme in _schemes(doc):
        accepted = schema_registry.get_accepted_fields(scheme["annotation_type"])
        if accepted is None:
            continue
        for key in scheme:
            if key not in accepted | INTERNAL_SCHEME_FIELDS:
                yield scheme["annotation_type"], key


class TestShippedConfigsAreClean:
    """What the repo tells people to copy must not carry keys that do nothing."""

    def test_example_configs(self):
        found = []
        for path in _tracked("examples"):
            if path.suffix not in (".yaml", ".yml"):
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            for type_name, key in _undeclared(doc):
                found.append(f"{path.relative_to(REPO_ROOT)}: {type_name}.{key}")
        assert not found, "\n".join(found)

    def test_docs_yaml_snippets(self):
        found = []
        for path in _tracked("docs"):
            if path.suffix != ".md" or "releasenotes" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"```ya?ml\n(.*?)```", text, re.S):
                try:
                    doc = yaml.safe_load(match.group(1))
                except yaml.YAMLError:
                    continue
                line = text[:match.start()].count("\n") + 1
                for type_name, key in _undeclared(doc):
                    found.append(f"{path.relative_to(REPO_ROOT)}:{line}: {type_name}.{key}")
        assert not found, "\n".join(found)


class TestPhaseFiles:
    """
    Schemes in phase page files (`phases.<name>.file`) are checked too.

    Survey and prestudy questions usually live in these files, and they are
    where hand-written schemes are commonest. Found by the potato-skill agent:
    a made-up key in `pre.jsonl` passed --strict as "OK -- no issues found".
    """

    QUESTION = {"annotation_type": "radio", "name": "q1", "description": "d",
                "labels": ["a", "b"], "made_up_phase_key": 1}

    def config(self, filename):
        return {"phases": {"order": ["prestudy"],
                           "prestudy": {"type": "prestudy", "file": filename}}}

    def test_json_jsonl_and_yaml_files(self, tmp_path, caplog):
        import json as _json
        (tmp_path / "pre.json").write_text(_json.dumps([self.QUESTION]))
        (tmp_path / "pre.jsonl").write_text(_json.dumps(self.QUESTION) + "\n")
        (tmp_path / "pre.yaml").write_text(yaml.safe_dump([self.QUESTION]))
        for name in ("pre.json", "pre.jsonl", "pre.yaml"):
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger=LOGGER):
                validate_scheme_keys(self.config(name), str(tmp_path))
            messages = [r.getMessage() for r in caplog.records
                        if "Unrecognized config key" in r.getMessage()]
            assert len(messages) == 1, (name, messages)
            assert f"phases.prestudy ({name})[q1].made_up_phase_key" in messages[0]

    def test_a_glob_and_a_task_dir_relative_path(self, tmp_path, caplog):
        import json as _json
        surveys = tmp_path / "study" / "surveys"
        surveys.mkdir(parents=True)
        (surveys / "a.jsonl").write_text(_json.dumps(self.QUESTION) + "\n")
        (surveys / "b.jsonl").write_text(_json.dumps(dict(self.QUESTION, name="q2")) + "\n")
        config = dict(self.config("surveys/*.jsonl"), task_dir="study")
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            validate_scheme_keys(config, str(tmp_path))
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "[q1].made_up_phase_key" in text and "[q2].made_up_phase_key" in text

    def test_strict_fails_on_a_phase_file_key(self, tmp_path):
        import json as _json
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "d.jsonl").write_text('{"id": "1", "text": "hi"}\n')
        (tmp_path / "pre.jsonl").write_text(_json.dumps(self.QUESTION) + "\n")
        main_scheme = {"annotation_type": "radio", "name": "s", "description": "d",
                       "labels": ["a", "b"]}
        config = {
            "annotation_task_name": "probe", "task_dir": ".", "output_annotation_dir": "out/",
            "data_files": ["data/d.jsonl"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "phases": {"order": ["prestudy", "annotation"],
                       "prestudy": {"type": "prestudy", "file": "pre.jsonl"},
                       "annotation": {"type": "annotation", "annotation_schemes": [main_scheme]}},
        }
        (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))
        report = validate_config_file(str(tmp_path / "config.yaml"))
        assert any("made_up_phase_key" in k for k in report.unknown_keys), report.to_dict()

    def test_a_missing_file_is_left_to_the_path_checks(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            validate_scheme_keys(self.config("nope.jsonl"), str(tmp_path))
        assert not [r for r in caplog.records if "Unrecognized" in r.getMessage()]

    def test_shipped_example_phase_files(self, caplog):
        found = []
        for path in _tracked("examples"):
            if path.name not in ("config.yaml", "config.yml"):
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if not isinstance(doc, dict) or "phases" not in doc:
                continue
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger=LOGGER):
                validate_scheme_keys({"phases": doc["phases"], "task_dir": doc.get("task_dir")},
                                     str(path.parent))
            found += [f"{path.relative_to(REPO_ROOT)}: {r.getMessage()}"
                      for r in caplog.records if "Unrecognized config key" in r.getMessage()]
        assert not found, "\n".join(found)


class TestGridViewConfig:
    from potato.server_utils.config_module import ConfigValidationError as _E

    def base(self, **grid):
        return {"annotation_schemes": [
                    {"annotation_type": "radio", "name": "s", "description": "d", "labels": ["a"]},
                    {"annotation_type": "text", "name": "t", "description": "d"}],
                "grid_view": dict({"enabled": True, "scheme": "s"}, **grid)}

    def test_a_radio_scheme_is_accepted(self):
        from potato.server_utils.config_module import validate_grid_view_config
        validate_grid_view_config(self.base(page_size=12))

    @pytest.mark.parametrize("grid,fragment", [
        ({"scheme": "nope"}, "must name a top-level annotation scheme"),
        ({"scheme": "t"}, "takes a radio, multiselect or triage scheme"),
        ({"page_size": 0}, "from 1 to 200"),
        ({"page_size": "24"}, "from 1 to 200"),
    ])
    def test_mistakes_are_refused(self, grid, fragment):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_grid_view_config)
        with pytest.raises(ConfigValidationError, match=fragment):
            validate_grid_view_config(self.base(**grid))

    def test_disabled_is_not_checked(self):
        from potato.server_utils.config_module import validate_grid_view_config
        validate_grid_view_config(self.base(enabled=False, scheme="nope"))
