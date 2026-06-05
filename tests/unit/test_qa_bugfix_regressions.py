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
