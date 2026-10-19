"""
Plugins (potato/plugins.py): annotation and display types from installed
packages.

The plugin here is really installed: tests/data/plugins/installed holds a package
and its .dist-info, and importlib.metadata finds the entry points there once
the folder is on sys.path. Nothing about discovery is mocked.
"""

import os
import sys

import pytest

from potato import plugins
from potato.server_utils.config_module import ConfigValidationError, validate_yaml_structure
from potato.server_utils.displays import display_registry
from potato.server_utils.schemas.registry import schema_registry

SITE = os.path.join(os.path.dirname(__file__), "..", "data", "plugins", "installed")


@pytest.fixture(autouse=True)
def installed_plugin():
    sys.path.insert(0, os.path.abspath(SITE))
    yield
    for name in list(plugins.loaded()):
        plugins.unload(name)
    sys.path.remove(os.path.abspath(SITE))
    for module in [m for m in sys.modules if m.startswith("potato_test_plugin")]:
        del sys.modules[module]


def config(**extra):
    base = {
        "item_properties": {"id_key": "id", "text_key": "text"},
        "task_dir": ".", "output_annotation_dir": "out", "annotation_task_name": "t",
        "data_files": ["data.jsonl"],
        "annotation_schemes": [{"annotation_type": "radio", "name": "r",
                                "description": "d", "labels": ["a", "b"]}],
    }
    base.update(extra)
    return base


STARS = {"annotation_type": "test_stars", "name": "quality", "description": "How good?",
         "max_stars": 4}


class TestDiscovery:
    def test_installed_plugins_are_found_without_importing_them(self):
        found = plugins.discover()
        assert {"testplugin", "collides", "explodes", "as_module"} <= set(found)
        assert "potato_test_plugin" not in sys.modules

    def test_loading_registers_types_and_assets(self):
        plugin = plugins.load_plugin("testplugin")
        assert (plugin.package, plugin.version) == ("potato-test-plugin", "1.0")
        assert schema_registry.is_registered("test_stars")
        assert display_registry.get("test_shout") is not None
        html, _keys = schema_registry.generate(STARS)
        assert 'max="4"' in html and "How good?" in html
        assert plugins.plugin_assets(["testplugin"]) == {
            "scripts": ["/plugin-static/testplugin/test.js?v=1.0"],
            "styles": ["/plugin-static/testplugin/test.css?v=1.0"]}
        # A page only carries the plugins its own config lists, even when this
        # process loaded others for another config.
        assert plugins.plugin_assets([]) == {"scripts": [], "styles": []}
        assert plugins.plugin_assets(None) == {"scripts": [], "styles": []}
        assert plugins.load_plugin("testplugin") is plugin  # twice is a no-op

    def test_an_entry_point_may_name_a_module(self):
        assert plugins.load_plugin("as_module").displays == ["test_module_display"]


class TestConfig:
    def test_a_listed_plugin_makes_its_types_valid(self):
        cfg = config(plugins=["testplugin"],
                     annotation_schemes=[STARS],
                     instance_display={"fields": [{"key": "text", "type": "test_shout"}]})
        validate_yaml_structure(cfg)
        assert "testplugin" in plugins.loaded()

    def test_an_installed_plugin_does_not_load_unless_listed(self):
        with pytest.raises(ConfigValidationError, match="annotation_type must be one of"):
            validate_yaml_structure(config(annotation_schemes=[STARS]))
        assert plugins.loaded() == {}

    def test_a_type_from_a_plugin_this_config_does_not_list(self):
        validate_yaml_structure(config(plugins=["testplugin"], annotation_schemes=[STARS]))
        # Same process, a second config that forgot the plugins key.
        with pytest.raises(ConfigValidationError, match="add 'testplugin' to plugins"):
            validate_yaml_structure(config(annotation_schemes=[STARS]))
        display_only = config(instance_display={"fields": [{"key": "text", "type": "test_shout"}]})
        with pytest.raises(ConfigValidationError, match="display type 'test_shout'"):
            validate_yaml_structure(display_only)

    def test_an_unknown_plugin_names_the_installed_ones(self):
        with pytest.raises(ConfigValidationError, match=r"'nope' is not installed.*testplugin"):
            validate_yaml_structure(config(plugins=["nope"]))

    @pytest.mark.parametrize("value, message", [
        ("testplugin", "must be a list"),
        ([""], r"plugins\[0\]"),
        (["testplugin", "testplugin"], "twice"),
    ])
    def test_the_list_is_checked(self, value, message):
        with pytest.raises(ConfigValidationError, match=message):
            validate_yaml_structure(config(plugins=value))


class TestFailures:
    def test_a_taken_name_registers_nothing(self):
        with pytest.raises(plugins.PluginError, match="annotation type 'radio' .built in."):
            plugins.load_plugin("collides")
        assert not schema_registry.is_registered("test_unique_type")
        assert "collides" not in plugins.loaded()

    def test_a_second_plugin_cannot_take_a_plugins_name(self):
        plugins.load_plugin("testplugin")
        api = plugins.PluginAPI("other", "other-pkg", "1", None)
        api.add_display("test_shout", display_registry.get("test_shout"))
        with pytest.raises(plugins.PluginError, match="from plugin 'testplugin'"):
            plugins._commit(api)

    def test_an_error_inside_register_registers_nothing(self):
        with pytest.raises(plugins.PluginError, match="raised while registering: database not configured"):
            plugins.load_plugin("explodes")
        assert not schema_registry.is_registered("test_never_registered")

    @pytest.mark.parametrize("name, message, leftover", [
        ("twice", "registers annotation type 'test_twice' twice", "test_twice_first"),
        ("display_twice", "registers display type 'test_display_twice' twice", None),
    ])
    def test_a_name_registered_twice_by_one_plugin(self, name, message, leftover):
        with pytest.raises(plugins.PluginError, match=message):
            plugins.load_plugin(name)
        assert name not in plugins.loaded()
        if leftover:
            assert not schema_registry.is_registered(leftover)
        assert display_registry.get("test_display_twice") is None

    def test_a_missing_asset_is_named(self):
        with pytest.raises(plugins.PluginError, match="script 'absent.js' is not in"):
            plugins.load_plugin("missing_asset")


class TestPhaseFiles:
    """Survey-phase question files are checked by validate, not only at boot."""

    def _config_with_phase(self, tmp_dir, questions, **extra):
        import json
        with open(os.path.join(tmp_dir, "pre.json"), "w") as handle:
            json.dump(questions, handle)
        return config(phases={"order": ["pre", "annotation"],
                              "pre": {"type": "prestudy", "file": "pre.json"}}, **extra)

    @pytest.fixture
    def tmp_dir(self):
        from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
        folder = create_test_directory("plugins_phase_files")
        yield folder
        cleanup_test_directory(folder)

    def test_a_plugin_type_in_a_phase_file_needs_the_plugin_listed(self, tmp_dir):
        question = dict(STARS)
        cfg = self._config_with_phase(tmp_dir, [question])
        plugins.load_plugin("testplugin")  # loaded for another config in this process
        with pytest.raises(ConfigValidationError, match="from plugin 'testplugin'"):
            validate_yaml_structure(cfg, config_file_dir=tmp_dir)
        validate_yaml_structure(self._config_with_phase(tmp_dir, [question], plugins=["testplugin"]),
                                config_file_dir=tmp_dir)

    def test_an_unknown_type_in_a_phase_file(self, tmp_dir):
        cfg = self._config_with_phase(tmp_dir, [
            {"annotation_type": "radio", "name": "ok", "description": "d", "labels": ["a"]},
            {"annotation_type": "bogus", "name": "age", "description": "Your age"}])
        with pytest.raises(ConfigValidationError, match=r"entry 1 \('age'\): 'bogus' is not"):
            validate_yaml_structure(cfg, config_file_dir=tmp_dir)


class TestMcp:
    def test_listings_name_the_plugin_behind_a_type(self):
        from potato.mcp_server import tools_local
        plugins.load_plugin("testplugin")
        types = {t["name"]: t["plugin"] for t in tools_local.list_annotation_types()}
        assert types["test_stars"] == "testplugin" and types["radio"] is None
        displays = {d["name"]: d["plugin"] for d in tools_local.list_display_types()}
        assert displays["test_shout"] == "testplugin" and displays["text"] is None

    def test_listing_plugins_imports_none_of_them(self):
        from potato.mcp_server import tools_local
        rows = {r["name"]: r for r in tools_local.list_plugins()}
        assert rows["testplugin"]["package"] == "potato-test-plugin"
        assert rows["testplugin"]["loaded"] is False
        assert "annotation_types" not in rows["testplugin"]
        assert "potato_test_plugin" not in sys.modules
        assert plugins.loaded() == {}

    def test_naming_one_plugin_loads_only_that_one(self):
        from potato.mcp_server import tools_local
        [row] = tools_local.list_plugins("testplugin")
        assert row["loaded"] and row["annotation_types"] == ["test_stars"]
        assert set(plugins.loaded()) == {"testplugin"}
        [broken] = tools_local.list_plugins("explodes")
        assert "database not configured" in broken["error"]
        [missing] = tools_local.list_plugins("nope")
        assert "not installed" in missing["error"] and "testplugin" in missing["installed"]


class TestCli:
    def test_list_and_check(self, capsys):
        assert plugins.main([]) == 0
        listing = capsys.readouterr().out
        assert "testplugin" in listing and "potato-test-plugin 1.0" in listing
        assert plugins.main(["testplugin"]) == 0
        report = capsys.readouterr().out
        assert "annotation types: test_stars" in report and "scripts:          test.js" in report
        assert plugins.main(["explodes"]) == 1
        assert "database not configured" in capsys.readouterr().out
        assert plugins.main(["twice"]) == 1
        assert "twice" in capsys.readouterr().out
