"""Regression tests for QA-found bugs (2026-06).

Covers:
- F-016: dynamic_labels 500 — label humanization must not corrupt Jinja
  expressions (``{{instance_obj...}}`` -> ``{{instance Obj...}}``).
- F-018: page-template-gated frontend JS silently disabled — the bare
  ``config['site_file']`` filename must resolve to the generated template's
  real path so asset detection can read it regardless of the process CWD.
"""
import os
import tempfile

import pytest


class TestHumanizeLabelPreservesJinja:
    """F-016: humanize_label must leave template expressions untouched."""

    def test_jinja_print_expression_preserved(self):
        from potato.server_utils.schemas.identifier_utils import humanize_label
        expr = "{{instance_obj.labels[0]}}"
        # Must NOT become "{{instance Obj.labels[0]}}" (which breaks Jinja compile)
        assert humanize_label(expr) == expr

    def test_jinja_statement_expression_preserved(self):
        from potato.server_utils.schemas.identifier_utils import humanize_label
        expr = "{% if x %}A{% endif %}"
        assert humanize_label(expr) == expr

    def test_normal_label_still_humanized(self):
        from potato.server_utils.schemas.identifier_utils import humanize_label
        assert humanize_label("agent_a_better") == "Agent A Better"

    def test_display_label_text_preserves_jinja(self):
        from potato.server_utils.schemas.identifier_utils import display_label_text
        expr = "{{instance_obj.labels[1]}}"
        assert display_label_text(expr, {"humanize_labels": True}) == expr


class TestResolveGeneratedTemplatePath:
    """F-018: bare site_file resolves to <site_dir>/generated/<file>."""

    def test_bare_filename_resolves_to_generated_dir(self, monkeypatch):
        import potato.flask_server as fs
        with tempfile.TemporaryDirectory() as site_dir:
            gen = os.path.join(site_dir, "generated")
            os.makedirs(gen)
            fname = "My-Task-base_template_v2.html"
            full = os.path.join(gen, fname)
            with open(full, "w") as f:
                f.write("<div class=\"annotation-form triage\"></div>")

            monkeypatch.setitem(fs.config, "site_dir", site_dir)
            # From a *different* CWD (as the chdir'd server would be), the bare
            # name must still resolve to the real generated file.
            resolved = fs._resolve_generated_template_path(fname)
            assert resolved == full
            assert os.path.exists(resolved)

    def test_detection_finds_marker_after_resolution(self, monkeypatch):
        import potato.flask_server as fs
        with tempfile.TemporaryDirectory() as site_dir:
            gen = os.path.join(site_dir, "generated")
            os.makedirs(gen)
            fname = "Triage-Task-base_template_v2.html"
            with open(os.path.join(gen, fname), "w") as f:
                f.write('<form class="annotation-form triage"></form>'
                        '<div class="triage-container"></div>')
            monkeypatch.setitem(fs.config, "site_dir", site_dir)

            # Run detection from an unrelated CWD to mimic the server chdir.
            cwd = os.getcwd()
            try:
                os.chdir(tempfile.gettempdir())
                assets = fs._detect_frontend_assets_for_page(fname, "")
            finally:
                os.chdir(cwd)
            assert assets.get("triage") is True

    def test_absolute_existing_path_passthrough(self, monkeypatch):
        import potato.flask_server as fs
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf.write(b"x")
            path = tf.name
        try:
            assert fs._resolve_generated_template_path(path) == path
        finally:
            os.unlink(path)
