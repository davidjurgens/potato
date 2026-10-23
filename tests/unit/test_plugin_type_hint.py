"""Audit 95, P1: using a plugin's type without listing the plugin gave the
built-in type list and never named the plugin to add."""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError, validate_single_annotation_scheme)


def _check(type_name):
    with pytest.raises(ConfigValidationError) as err:
        validate_single_annotation_scheme(
            {"annotation_type": type_name, "name": "p", "description": "d"}, "s[0]")
    return str(err.value)


def test_installed_plugin_named(monkeypatch):
    from potato import plugins
    monkeypatch.setattr(plugins, "discover", lambda: {"counter": object()})
    assert "add `plugins: [counter]`" in _check("counter")
    assert "installed plugins: counter" in _check("tally")


def test_no_plugins_no_hint(monkeypatch):
    from potato import plugins
    monkeypatch.setattr(plugins, "discover", lambda: {})
    assert "plugins" not in _check("tally").split("must be one of")[0]
    assert "installed plugins" not in _check("tally")
