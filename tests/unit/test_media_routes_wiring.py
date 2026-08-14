"""
Wiring guards for the media proxy.

Two bugs here were invisible to every unit test and only appeared against a
live server, so they get explicit guards:

1. **Re-importing the routes module inside a handler.** ``from potato.routes
   import config`` looks harmless, but under ``python potato/flask_server.py``
   that module is already loaded under a *different* name, so the import
   re-executes it and its module-level ``@app.route`` decorators fire again
   against the running app. Every media request died with "View function
   mapping is overwriting an existing endpoint function: home". Config is now
   passed in at registration instead.

2. **A relative cache root.** Flask's ``send_file`` resolves a relative path
   against ``app.root_path``, not the process cwd, so every transcode was
   written to one place and looked for in another — a 500 on a file that had
   just been created successfully.

Plus invariant 4: a route that exists only as a decorator 404s under
``potato start``.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from potato.media import routes as media_routes
from potato.media.cache import MediaCache


class TestNoRuntimeReimport:
    def test_handlers_do_not_import_the_routes_module(self):
        """
        The import that broke every media request. It must not come back: the
        symptom (an unrelated endpoint collision) points nowhere near the
        cause.
        """
        source = Path("potato/media/routes.py").read_text()
        # Statements only: the module documents this hazard in a comment, and a
        # naive substring check matches its own warning.
        offenders = [line.strip() for line in source.splitlines()
                     if line.strip().startswith(("from potato.routes import",
                                                 "import potato.routes"))]
        assert not offenders, (
            f"{offenders} re-executes potato.routes under a second module name "
            f"and re-registers every @app.route against the live app. Pass "
            f"config in via register_media_routes instead.")

    def test_register_takes_the_config_explicitly(self):
        signature = inspect.signature(media_routes.register_media_routes)
        assert "config" in signature.parameters, (
            "config must be handed in, not fetched at request time")

    def test_registration_stores_the_same_object_not_a_copy(self):
        """
        A copy would go stale: config is mutated after routes are wired, and
        the proxy has to see the same media_directory serve_media does.
        """
        class FakeApp:
            def __init__(self):
                self.rules = []

            def add_url_rule(self, rule, endpoint, view, **kwargs):
                self.rules.append(rule)

        config = {"task_dir": "."}
        media_routes.register_media_routes(FakeApp(), config)
        config["media_directory"] = "elsewhere"
        assert media_routes._config() is config


class TestRoutesAreRegistered:
    def test_both_routes_are_added(self):
        """Invariant 4: a decorator alone 404s under `potato start`."""
        class FakeApp:
            def __init__(self):
                self.rules = {}

            def add_url_rule(self, rule, endpoint, view, **kwargs):
                self.rules[rule] = endpoint

        app = FakeApp()
        media_routes.register_media_routes(app, {})
        assert "/media/proxy/<path:filepath>" in app.rules
        assert "/media/info/<path:filepath>" in app.rules
        assert "/media/pointcloud/<path:filepath>" in app.rules

    def test_configure_routes_wires_the_media_proxy(self):
        """The registration must actually be called, not merely exist."""
        source = Path("potato/routes.py").read_text()
        assert "register_media_routes(app, config)" in source


class TestCacheRootIsAbsolute:
    def test_a_relative_root_becomes_absolute(self, tmp_path, monkeypatch):
        """
        Flask resolves a relative send_file path against app.root_path, so a
        relative cache root serves 500s for files that exist.
        """
        monkeypatch.chdir(tmp_path)
        cache = MediaCache("out")
        assert cache.root.is_absolute()

    def test_entry_paths_are_absolute_too(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cache = MediaCache("out")
        target = cache.path_for(Path("a.tif"), ".webp")
        assert target.is_absolute()


class TestPathTraversal:
    def test_the_guard_matches_serve_media(self, tmp_path):
        """
        This route hands a user-supplied path to a decoder, so it must not be
        the one place the traversal check is weaker than serve_media's.
        """
        media = tmp_path / "media"
        media.mkdir()
        (media / "ok.tif").write_bytes(b"x")
        config = {"task_dir": str(tmp_path), "media_directory": "media"}

        _dir, resolved = media_routes._resolve_media_path(config, "ok.tif")
        assert resolved is not None

        for attack in ("../config.yaml", "../../etc/passwd",
                       "sub/../../config.yaml"):
            _dir, resolved = media_routes._resolve_media_path(config, attack)
            assert resolved is None, f"{attack} was not blocked"

    def test_an_absolute_path_cannot_escape(self, tmp_path):
        config = {"task_dir": str(tmp_path), "media_directory": "media"}
        (tmp_path / "media").mkdir()
        _dir, resolved = media_routes._resolve_media_path(config, "/etc/passwd")
        assert resolved is None


class TestQueryParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("1200", 1200.0), ("1200.5", 1200.5), ("", None),
        (None, None), ("abc", None),
    ])
    def test_a_bad_window_value_is_ignored_not_fatal(self, raw, expected):
        """A malformed slider value should fall back to the default window."""
        assert media_routes._float_arg({"window_min": raw}, "window_min") == expected
