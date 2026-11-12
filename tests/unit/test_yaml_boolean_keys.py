"""
`on:` in a config is a key, not a boolean.

YAML 1.1 reads bare `on`, `off`, `yes` and `no` as booleans wherever they
appear -- including as mapping *keys*. So this, which is how Potato's own
examples are written:

    automatic_assignment:
      on: true

parses to `{True: True}`. `config["automatic_assignment"].get("on")` is then
None, automatic assignment is off, and nothing says so.

It also crashes. A dict holding both a `bool` and a `str` key cannot be sorted,
so `jsonify` on `/api/schemas` raises `TypeError: '<' not supported between
instances of 'str' and 'bool'` and the annotation form never loads at all. That
one is worse for being intermittent: `textarea: {on: true}` on its own has one
key and nothing to sort against, so the obvious minimal reproduction passes.

Four shipped, CI-checked example configs had this. Three were quietly running
without the automatic assignment they asked for.

The repair happens at load, with a warning, rather than by rejecting the config:
a file that reads correctly to a human should not have to know about YAML 1.1.
"""

import glob
import os

import pytest
import yaml

from potato.server_utils.config_module import _restore_yaml_boolean_keys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTheRepair:
    def test_a_true_key_becomes_on(self):
        assert _restore_yaml_boolean_keys({True: True}) == {"on": True}

    def test_a_false_key_becomes_off(self):
        assert _restore_yaml_boolean_keys({False: 1}) == {"off": 1}

    def test_it_reaches_nested_dicts(self):
        got = _restore_yaml_boolean_keys({"automatic_assignment": {True: True}})
        assert got == {"automatic_assignment": {"on": True}}

    def test_it_reaches_inside_lists(self):
        got = _restore_yaml_boolean_keys(
            {"annotation_schemes": [{"textarea": {True: True, "rows": 2}}]})
        assert got == {"annotation_schemes": [{"textarea": {"on": True, "rows": 2}}]}

    def test_boolean_values_are_left_alone(self):
        """Only keys are ambiguous. `enabled: true` means what it says."""
        assert _restore_yaml_boolean_keys({"enabled": True}) == {"enabled": True}

    def test_an_explicit_string_key_is_untouched(self):
        assert _restore_yaml_boolean_keys({"on": True}) == {"on": True}

    def test_the_repaired_dict_is_json_sortable(self):
        """The crash was `sorted()` over mixed key types."""
        repaired = _restore_yaml_boolean_keys({"textarea": {True: True, "rows": 2}})
        assert sorted(repaired["textarea"]) == ["on", "rows"]

    def test_it_warns(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="potato.server_utils.config_module"):
            _restore_yaml_boolean_keys({True: 1}, "demo.yaml")
        assert any("YAML" in r.message or "YAML" in r.getMessage()
                   for r in caplog.records), "the repair must be visible in the log"

    def test_the_real_yaml_shape_round_trips(self):
        """Start from YAML text, not a hand-built dict."""
        parsed = yaml.safe_load("automatic_assignment:\n  on: true\n  users: []\n")
        assert True in parsed["automatic_assignment"], "YAML 1.1 changed behaviour"
        repaired = _restore_yaml_boolean_keys(parsed)
        assert repaired["automatic_assignment"]["on"] is True


class TestShippedExamplesDoNotRelyOnTheRepair:
    """The repair is a safety net. The examples people copy should be correct.

    An example carrying a mis-parsed key teaches the mistake: an agent told to
    "start from a working example" copies the broken spelling into a config the
    repair may not cover, and gets a feature that is silently off.
    """

    def test_no_example_config_has_a_non_string_key(self):
        offenders = []
        for path in sorted(glob.glob(os.path.join(REPO_ROOT, "examples", "*", "*", "config.yaml"))):
            try:
                config = yaml.safe_load(open(path, encoding="utf-8")) or {}
            except Exception:
                continue

            def walk(node, where):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if not isinstance(key, str):
                            offenders.append(
                                f"{os.path.relpath(path, REPO_ROOT)}: "
                                f"{where or 'top level'} has key {key!r} "
                                f"({type(key).__name__}) -- quote it")
                        walk(value, f"{where}.{key}" if where else str(key))
                elif isinstance(node, list):
                    for i, item in enumerate(node):
                        walk(item, f"{where}[{i}]")

            walk(config, "")
        assert not offenders, "\n".join(offenders)
