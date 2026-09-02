"""Guards that the deploy path table stays in step with the config validator.

`potato/deploy/paths.py` declares every config key that names a path, so the
bundler can ship a task's files to another machine. `config_module` separately
*validates* a set of path keys. If the validator learns about a new key and the
deploy table does not, deploys silently omit a file and the task breaks on the
remote host with a missing-data error.

The drift guard reads the validator's source and asserts every key it touches is
covered by CONFIG_PATH_KEYS.
"""

import ast
import glob
import inspect
import os

import pytest
import yaml

import potato.server_utils.config_module as config_module
from potato.deploy.paths import (
    CONFIG_PATH_KEYS,
    ConfigPaths,
    collect_config_paths,
    collect_media_paths,
)


# Suffixes that mark a config key as naming a path. The drift guard only
# considers keys matching one of these, so container keys (batch_assignment,
# groups) and ordinary settings (max_attempts, allow_retry) do not have to be
# enumerated in an ever-growing exclusion list.
#
# The gap this leaves: a future path key with none of these suffixes, in the
# style of the existing custom_ds / base_css / header_logo. Those three are
# already declared; a new one would slip past. Accepted, because the alternative
# is a denylist that goes stale in the other direction.
PATH_KEY_SUFFIXES = ("_file", "_files", "_dir", "_directory", "_path", "_paths")

# Path-shaped keys that are structural rather than a path to ship.
NON_PATH_KEYS = {
    "task_dir",      # the base directory, tracked separately on ConfigPaths
    "path",          # the inner field of a {path, encoding} entry
}


def _looks_like_path_key(key: str) -> bool:
    return key.endswith(PATH_KEY_SUFFIXES)


def _declared_leaf_keys() -> set:
    """Last dotted segment of every declared path key."""
    return {pk.key.split(".")[-1].replace("[]", "") for pk in CONFIG_PATH_KEYS}


def _keys_touched_by(func) -> set:
    """String literals used as config lookups inside a function's source."""
    source = inspect.getsource(func)
    tree = ast.parse(ast.unparse(ast.parse(source)))

    found = set()
    for node in ast.walk(tree):
        # config_data.get('x') / group.get('x', ...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add(arg.value)
        # config_data['x']
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                found.add(node.slice.value)
        # 'x' in config_data
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant):
            if isinstance(node.left.value, str) and any(
                isinstance(op, ast.In) for op in node.ops
            ):
                found.add(node.left.value)
    return found


class TestNoDriftFromValidator:
    def test_covers_validate_file_paths(self):
        touched = {k for k in _keys_touched_by(config_module.validate_file_paths)
                   if _looks_like_path_key(k)} - NON_PATH_KEYS
        declared = _declared_leaf_keys()
        missing = {k for k in touched if k not in declared}
        assert not missing, (
            "validate_file_paths reads path keys that potato/deploy/paths.py does "
            f"not declare: {sorted(missing)}. Add them to CONFIG_PATH_KEYS or, if "
            "they are not paths, to NON_PATH_KEYS in this test."
        )

    def test_covers_validate_training_config(self):
        touched = {k for k in _keys_touched_by(config_module.validate_training_config)
                   if _looks_like_path_key(k)} - NON_PATH_KEYS
        declared = _declared_leaf_keys()
        missing = {k for k in touched if k not in declared}
        assert not missing, f"undeclared training path keys: {sorted(missing)}"

    def test_declared_keys_are_well_formed(self):
        for path_key in CONFIG_PATH_KEYS:
            assert path_key.kind in {"file", "dir", "list"}, path_key
            assert path_key.base in {"task_dir", "project"}, path_key
            assert path_key.key, path_key

    def test_no_duplicate_declarations(self):
        keys = [pk.key for pk in CONFIG_PATH_KEYS]
        assert len(keys) == len(set(keys)), "duplicate entries in CONFIG_PATH_KEYS"


class TestCollectConfigPaths:
    def test_resolves_data_files_relative_to_task_dir(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "items.json").write_text("[]")
        config_path = tmp_path / "config.yaml"
        config_path.write_text("x")

        cfg = {"task_dir": ".", "data_files": ["data/items.json"]}
        paths = collect_config_paths(cfg, str(config_path))

        resolved = [p for p in paths.paths if p.config_key == "data_files"]
        assert len(resolved) == 1
        assert resolved[0].exists
        assert resolved[0].inside_task_dir
        assert not paths.missing

    def test_dict_form_data_file(self, tmp_path):
        (tmp_path / "items.csv").write_text("a,b")
        config_path = tmp_path / "config.yaml"
        config_path.write_text("x")

        cfg = {"task_dir": ".",
               "data_files": [{"path": "items.csv", "encoding": "utf-8"}]}
        paths = collect_config_paths(cfg, str(config_path))
        assert [p.raw for p in paths.paths if p.config_key == "data_files"] == ["items.csv"]

    def test_missing_required_file_is_reported(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("x")
        cfg = {"task_dir": ".", "data_files": ["data/gone.json"]}

        paths = collect_config_paths(cfg, str(config_path))
        assert len(paths.missing_required) == 1
        assert paths.missing_required[0].raw == "data/gone.json"

    def test_sentinel_values_are_skipped(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("x")
        cfg = {"task_dir": ".", "header_file": "default",
               "site_dir": "none", "custom_ds": None}

        paths = collect_config_paths(cfg, str(config_path))
        assert [p.config_key for p in paths.paths] == []

    def test_url_header_logo_is_not_a_local_path(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("x")
        cfg = {"task_dir": ".", "header_logo": "https://example.org/logo.png"}

        paths = collect_config_paths(cfg, str(config_path))
        assert len(paths.paths) == 1
        assert paths.paths[0].is_url
        assert not paths.missing

    def test_batch_assignment_group_expansion(self, tmp_path):
        """No example config exercises the `[]` list segment, so cover it here."""
        (tmp_path / "a.json").write_text("[]")
        (tmp_path / "b.json").write_text("[]")
        config_path = tmp_path / "config.yaml"
        config_path.write_text("x")

        cfg = {"task_dir": ".", "batch_assignment": {"groups": [
            {"name": "one", "instances_file": "a.json"},
            {"name": "two", "instances_file": "b.json"},
        ]}}
        paths = collect_config_paths(cfg, str(config_path))
        raws = sorted(p.raw for p in paths.paths)
        assert raws == ["a.json", "b.json"]
        assert all(p.exists for p in paths.paths)

    def test_out_of_tree_path_is_flagged(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "shared.json").write_text("[]")
        project = tmp_path / "project"
        project.mkdir()
        config_path = project / "config.yaml"
        config_path.write_text("x")

        cfg = {"task_dir": ".", "data_files": [str(outside / "shared.json")]}
        paths = collect_config_paths(cfg, str(config_path))
        assert len(paths.outside_task_dir) == 1

    def test_task_dir_resolves_against_config_file_not_cwd(self, tmp_path, monkeypatch):
        """init_config resolves task_dir relative to the config file's directory."""
        project = tmp_path / "project"
        (project / "data").mkdir(parents=True)
        (project / "data" / "items.json").write_text("[]")
        config_path = project / "config.yaml"
        config_path.write_text("x")

        monkeypatch.chdir(tmp_path)  # cwd deliberately != config dir
        cfg = {"task_dir": ".", "data_files": ["data/items.json"]}
        paths = collect_config_paths(cfg, str(config_path))
        assert paths.task_dir == os.path.realpath(str(project)) or paths.task_dir == str(project)
        assert not paths.missing

    def test_surveyflow_lists_are_expanded(self, tmp_path):
        survey = tmp_path / "surveys"
        survey.mkdir()
        (survey / "intro.jsonl").write_text("{}")
        (survey / "end.jsonl").write_text("{}")
        config_path = tmp_path / "config.yaml"
        config_path.write_text("x")

        cfg = {"task_dir": ".", "surveyflow": {
            "pre_annotation": ["surveys/intro.jsonl"],
            "post_annotation": ["surveys/end.jsonl"],
        }}
        paths = collect_config_paths(cfg, str(config_path))
        assert len(paths.paths) == 2
        assert all(p.exists for p in paths.paths)


class TestAgainstRealExamples:
    """The example tree is the broadest corpus of real configs available."""

    @pytest.fixture(scope="class")
    def example_configs(self):
        return sorted(glob.glob("examples/*/*/config.yaml"))

    def test_every_example_yields_at_least_one_path(self, example_configs):
        assert example_configs, "no example configs found"
        empty = []
        for config_path in example_configs:
            cfg = yaml.safe_load(open(config_path))
            if not isinstance(cfg, dict):
                continue
            if len(collect_config_paths(cfg, config_path)) == 0:
                empty.append(config_path)
        assert not empty, f"configs resolving to zero paths: {empty[:5]}"

    def test_no_example_has_a_missing_required_path(self, example_configs):
        """A missing required path here means either a broken example or a
        resolution bug in collect_config_paths. Both are worth failing on."""
        broken = {}
        for config_path in example_configs:
            cfg = yaml.safe_load(open(config_path))
            if not isinstance(cfg, dict):
                continue
            missing = collect_config_paths(cfg, config_path).missing_required
            if missing:
                broken[config_path] = [(m.config_key, m.raw) for m in missing]
        assert not broken, f"examples with unresolvable required paths: {broken}"


class TestCollectMediaPaths:
    def test_finds_media_under_media_directory(self, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        (media / "cat.png").write_bytes(b"\x89PNG")
        items = [{"id": "1", "image": "/media/cat.png"}]
        found = collect_media_paths({}, items, str(tmp_path))
        assert len(found) == 1 and found[0].endswith("cat.png")

    def test_finds_media_relative_to_task_root(self, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "clip.mp3").write_bytes(b"ID3")
        items = [{"id": "1", "audio": "assets/clip.mp3"}]
        found = collect_media_paths({}, items, str(tmp_path))
        assert len(found) == 1

    def test_honors_custom_media_directory(self, tmp_path):
        (tmp_path / "pics").mkdir()
        (tmp_path / "pics" / "a.jpg").write_bytes(b"\xff\xd8")
        items = [{"image": "/media/a.jpg"}]
        found = collect_media_paths({"media_directory": "pics"}, items, str(tmp_path))
        assert len(found) == 1

    def test_urls_and_missing_files_are_skipped(self, tmp_path):
        items = [{"a": "https://example.org/x.png", "b": "media/gone.png"}]
        assert collect_media_paths({}, items, str(tmp_path)) == []

    def test_duplicates_collapse(self, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        (media / "same.png").write_bytes(b"\x89PNG")
        items = [{"a": "/media/same.png"}, {"b": "/media/same.png"}]
        assert len(collect_media_paths({}, items, str(tmp_path))) == 1

    def test_non_media_strings_ignored(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hello")
        items = [{"text": "notes.txt", "label": "positive"}]
        assert collect_media_paths({}, items, str(tmp_path)) == []
