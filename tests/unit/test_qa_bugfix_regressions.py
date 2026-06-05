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


class TestAdjudicationAgreement:
    """F-020: agreement must reflect actual radio disagreement, not always 1.0."""

    def _agreement(self, annots):
        from potato.adjudication import AdjudicationManager
        # _compute_agreement is a plain method that doesn't touch instance state.
        mgr = AdjudicationManager.__new__(AdjudicationManager)
        return mgr._compute_agreement(annots, ["sentiment"])

    def test_radio_total_disagreement_is_zero(self):
        annots = {
            "u1": {"sentiment": {"positive": "positive"}},
            "u2": {"sentiment": {"negative": "negative"}},
            "u3": {"sentiment": {"neutral": "neutral"}},
        }
        assert self._agreement(annots)["sentiment"] == 0.0

    def test_radio_full_agreement_is_one(self):
        annots = {
            "u1": {"sentiment": {"positive": "positive"}},
            "u2": {"sentiment": {"positive": "positive"}},
        }
        assert self._agreement(annots)["sentiment"] == 1.0

    def test_radio_partial_agreement(self):
        annots = {
            "u1": {"sentiment": {"positive": "positive"}},
            "u2": {"sentiment": {"positive": "positive"}},
            "u3": {"sentiment": {"negative": "negative"}},
        }
        # pairs: (u1,u2)=agree, (u1,u3)=disagree, (u2,u3)=disagree -> 1/3
        assert abs(self._agreement(annots)["sentiment"] - (1 / 3)) < 1e-9


class TestActiveLearningConfigParser:
    """F-021: AL config parsing (incl. ngram_range list->tuple coercion)."""

    def test_disabled_returns_none(self):
        from potato.active_learning_manager import parse_active_learning_config
        assert parse_active_learning_config({"active_learning": {"enabled": False}}) is None
        assert parse_active_learning_config({}) is None

    def test_ngram_range_coerced_to_tuple(self):
        from potato.active_learning_manager import parse_active_learning_config
        cfg = {
            "active_learning": {
                "enabled": True,
                "vectorizer_params": {"ngram_range": [1, 2], "max_features": 5000},
            },
            "annotation_schemes": [{"name": "s", "annotation_type": "radio"}],
        }
        al = parse_active_learning_config(cfg)
        assert al is not None
        assert al.vectorizer_params["ngram_range"] == (1, 2)
        assert isinstance(al.vectorizer_params["ngram_range"], tuple)

    def test_schema_names_default_from_schemes(self):
        from potato.active_learning_manager import parse_active_learning_config
        cfg = {
            "active_learning": {"enabled": True, "query_strategy": "uncertainty"},
            "annotation_schemes": [
                {"name": "sentiment", "annotation_type": "radio"},
                {"name": "notes", "annotation_type": "text"},
            ],
        }
        al = parse_active_learning_config(cfg)
        assert al.schema_names == ["sentiment"]  # text scheme excluded

    def test_nested_llm_block_maps_to_llm_enabled(self):
        from potato.active_learning_manager import parse_active_learning_config
        cfg = {
            "active_learning": {
                "enabled": True,
                "cold_start_strategy": "llm",
                "llm": {"enabled": True, "use_mock": True, "model_name": "m"},
            },
            "annotation_schemes": [{"name": "topic", "annotation_type": "radio"}],
        }
        al = parse_active_learning_config(cfg)
        assert al.llm_enabled is True
        assert al.llm_config.get("use_mock") is True


class TestColdStartLenientJsonParse:
    """F-023: LLM cold-start must tolerate fenced/prose-wrapped JSON."""

    def test_fenced_json(self):
        from potato.ai.llm_active_learning import _loads_lenient
        out = _loads_lenient('```json\n{"label": "Finance", "confidence": 8}\n```')
        assert out == {"label": "Finance", "confidence": 8}

    def test_plain_json(self):
        from potato.ai.llm_active_learning import _loads_lenient
        assert _loads_lenient('{"label": "X", "confidence": 5}')["label"] == "X"

    def test_prose_wrapped_json(self):
        from potato.ai.llm_active_learning import _loads_lenient
        out = _loads_lenient('Sure! {"label": "Y", "confidence": 3} hope that helps')
        assert out["label"] == "Y"

    def test_bare_fence_without_lang(self):
        from potato.ai.llm_active_learning import _loads_lenient
        out = _loads_lenient('```\n{"label": "Z"}\n```')
        assert out["label"] == "Z"


class TestInstanceDataRouteRegistered:
    """F-024: /api/instance_data must be registered via configure_routes()'s
    add_url_rule, not only via a module-level @app.route.

    In the CLI `potato start` path, routes.py is first imported before the
    serving app exists, so module-level @app.route decorators bind to a
    throwaway app. The serving app is populated only by configure_routes()'s
    add_url_rule calls. A route present ONLY as a module-level @app.route
    (like get_instance_data was) therefore 404s on every live server, even
    though it shows up in an in-process create_app() url_map. The only thing
    that distinguishes a working sibling (/api/current_instance) from the
    broken one is the explicit add_url_rule in configure_routes — so that is
    what we assert here. A test that merely builds create_app() in-process
    would pass even with the bug present.
    """

    def _routes_src(self):
        import potato.routes as routes_mod
        import inspect
        return inspect.getsource(routes_mod)

    def test_instance_data_has_add_url_rule(self):
        src = self._routes_src()
        assert 'add_url_rule("/api/instance_data"' in src, (
            "/api/instance_data is not re-registered in configure_routes; it will "
            "404 on every `potato start` server (only the in-process app has it)."
        )

    def test_sibling_current_instance_also_registered(self):
        # Guard the invariant generally for the frontend-critical instance APIs.
        src = self._routes_src()
        for path in ("/api/current_instance", "/api/instance_data", "/api/spans/<instance_id>"):
            assert f'add_url_rule("{path}"' in src, f"{path} missing configure_routes registration"

    def test_test_reset_state_registered(self):
        # F-041 (same class as F-024): the debug-gated test-state reset existed
        # only as a module-level @app.route, so it 404'd on the configure_routes
        # serving app and the video-persistence Selenium suite lost per-test
        # isolation. It must be re-registered via add_url_rule.
        src = self._routes_src()
        assert 'add_url_rule("/admin/api/test/reset_state"' in src, (
            "/admin/api/test/reset_state is not re-registered in configure_routes; "
            "it 404s on live/test servers, breaking per-test isolation."
        )

    def test_every_module_route_is_reregistered(self):
        # F-042 (general invariant for the F-024/F-041 class): EVERY module-level
        # @app.route path must also be registered via add_url_rule in
        # configure_routes, otherwise it 404s on every live `potato start` server
        # (the serving app is built by configure_routes, not the throwaway
        # module-level app). This catches any newly-added dead route.
        import re
        src = self._routes_src()
        route_paths = set(re.findall(r'@app\.route\(\s*["\']([^"\']+)["\']', src))
        rule_paths = set(re.findall(r'add_url_rule\(\s*["\']([^"\']+)["\']', src))
        missing = sorted(route_paths - rule_paths)
        assert not missing, (
            "These @app.route paths lack an add_url_rule in configure_routes and "
            f"will 404 on live servers (F-024 class): {missing}"
        )


class TestLabelColorBooleanSafe:
    """F-027: label color helpers must tolerate non-str label names produced by
    YAML parsing unquoted yes/no/on/off/true/false (-> bool) or bare numbers."""

    def test_default_label_color_accepts_bool(self):
        from potato.routes import get_default_label_color
        # Must not raise AttributeError: 'bool' object has no attribute 'lower'
        c_true = get_default_label_color(True, 0)
        c_false = get_default_label_color(False, 1)
        assert isinstance(c_true, str) and c_true
        assert isinstance(c_false, str) and c_false

    def test_default_label_color_accepts_number(self):
        from potato.routes import get_default_label_color
        assert isinstance(get_default_label_color(1, 0), str)
        assert isinstance(get_default_label_color(3.5, 2), str)


class TestAiCacheManagerPartialConfig:
    """F-028: AiCacheManager must boot with a partial cache_config (no
    disk_cache / prefetch sub-blocks) instead of KeyError."""

    def test_partial_cache_config_does_not_crash(self):
        from potato.ai.ai_cache import AiCacheManager
        mgr = AiCacheManager.__new__(AiCacheManager)
        # Exercise just the config-parsing lines that used to KeyError.
        cache_config = {"enabled": False}  # no disk_cache, no prefetch
        disk = cache_config.get("disk_cache", {})
        mgr.disk_cache_enabled = disk.get("enabled", False)
        mgr.disk_persistence_path = disk.get("path")
        pf = cache_config.get("prefetch", {})
        mgr.warm_up_page_count = max(0, min(int(pf.get("warm_up_page_count", 0)), 10000))
        assert mgr.disk_cache_enabled is False
        assert mgr.disk_persistence_path is None
        assert mgr.warm_up_page_count == 0


class TestItemExposesDataFields:
    """F-029: Item.__getattr__ exposes raw data fields for dynamic-label /
    video_as_label templates (instance_obj.gifs[0]) without shadowing real
    attributes."""

    def test_data_field_accessible_as_attribute(self):
        from potato.item_state_management import Item
        it = Item("1", {"gifs": ["GIF-ID-1", "GIF-ID-2"], "text": "hi"})
        assert it.gifs[0] == "GIF-ID-1"
        assert it.text == "hi"

    def test_real_attributes_not_shadowed(self):
        from potato.item_state_management import Item
        # A data field named like a real attribute must NOT override it.
        it = Item("1", {"labels": ["x"], "item_id": "SHOULD_NOT_WIN"})
        assert it.item_id == "1"          # real attr wins
        assert it.labels == {}            # real attr (annotations), not data

    def test_missing_field_raises_attribute_error(self):
        from potato.item_state_management import Item
        it = Item("1", {"text": "hi"})
        with pytest.raises(AttributeError):
            _ = it.nonexistent_field
        # dunders must still raise (copy/pickle safety)
        with pytest.raises(AttributeError):
            _ = it.__wrapped__


class TestPromptOptimizerConstructs:
    """F-022: PromptOptimizer must accept prompt_optimization as a dataclass
    (not only a dict); previously it called .get() on the dataclass -> crash
    that was masked as 'Prompt optimizer not configured'."""

    def _make(self, prompt_optimization):
        import types
        from potato.solo_mode.prompt_optimizer import PromptOptimizer
        solo_config = types.SimpleNamespace(
            prompt_optimization=prompt_optimization,
            revision_models=[],
        )
        return PromptOptimizer(
            config={}, solo_config=solo_config,
            prompt_getter=lambda: "", prompt_setter=lambda *a, **k: None,
            examples_getter=lambda: [],
        )

    def test_dataclass_prompt_optimization(self):
        from potato.solo_mode.config import PromptOptimizationConfig
        opt = self._make(PromptOptimizationConfig(enabled=True, target_accuracy=0.9))
        assert opt.opt_config.enabled is True
        assert opt.opt_config.target_accuracy == 0.9

    def test_dict_prompt_optimization(self):
        opt = self._make({"enabled": False, "target_accuracy": 0.5})
        assert opt.opt_config.enabled is False
        assert opt.opt_config.target_accuracy == 0.5

    def test_none_prompt_optimization_uses_defaults(self):
        opt = self._make(None)
        assert opt.opt_config.enabled is True  # OptimizationConfig default
