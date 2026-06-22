"""Tests for the solo-mode prompt preview — the data behind the annotate
screen's "Prompt the LLM sees" panel.

The contract: get_prompt_preview() runs the *same* _build_full_prompt the
labeling thread uses, so the displayed prompt is byte-for-byte what the
model is given (no drift), it carries the live ## Codebook block, and the
reported codebook revision tracks edits.
"""

import pytest

from potato.solo_mode.manager import SoloModeManager, clear_solo_mode_manager
from potato.solo_mode.config import parse_solo_mode_config
from potato.codebook import (
    create_code, update_code_fields, current_revision, clear_change_listeners,
)
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import (
    clear_db_cache, clear_migrations, register_migration,
)


SCHEMES = [{"name": "theme", "annotation_type": "radio",
            "codebook": True, "labels": ["access barriers", "cost concerns"]}]


@pytest.fixture(autouse=True)
def _isolated():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    clear_change_listeners()
    clear_solo_mode_manager()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()
    clear_solo_mode_manager()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _manager(td):
    solo_config = parse_solo_mode_config(
        {"solo_mode": {"enabled": True, "labeling_models": []},
         "annotation_schemes": SCHEMES})
    app_config = {"task_dir": td, "annotation_task_name": "P",
                  "annotation_schemes": SCHEMES}
    mgr = SoloModeManager(solo_config, app_config)
    mgr.llm_labeling_thread.prompt_getter = lambda: "Pick the dominant theme."
    return mgr


def _preview(mgr, text="The clinic is two bus transfers away.", iid="i1"):
    from unittest.mock import patch
    with patch.object(mgr, "_get_instance_text", return_value=text):
        return mgr.get_prompt_preview(iid)


class TestPromptPreview:
    def test_includes_base_prompt_and_text(self, td):
        mgr = _manager(td)
        prev = _preview(mgr, text="HELLO WORLD TEXT")
        assert prev is not None
        assert "Pick the dominant theme." in prev["full_prompt"]
        assert "HELLO WORLD TEXT" in prev["full_prompt"]

    def test_codebook_block_injected_when_rich(self, td):
        mgr = _manager(td)
        create_code(td, project="P", name="access barriers",
                    created_by="config",
                    details={"definition": "Cannot physically reach care."})
        prev = _preview(mgr)
        assert "## Codebook" in prev["codebook_section"]
        assert "Cannot physically reach care." in prev["codebook_section"]
        # The section is actually folded into the prompt the model sees.
        assert prev["codebook_section"] in prev["full_prompt"]

    def test_no_block_when_no_rich_fields(self, td):
        mgr = _manager(td)
        # A plain code with no structured fields renders no block.
        create_code(td, project="P", name="cost concerns", created_by="config")
        prev = _preview(mgr)
        assert prev["codebook_section"] == ""
        # Prompt still assembles fine without a codebook block.
        assert "Pick the dominant theme." in prev["full_prompt"]

    def test_revision_matches_and_advances_on_edit(self, td):
        mgr = _manager(td)
        code = create_code(
            td, project="P", name="access barriers", created_by="config",
            details={"definition": "First definition."})
        prev1 = _preview(mgr)
        assert prev1["codebook_revision"] == current_revision(td, "P")
        assert "First definition." in prev1["full_prompt"]

        # Edit the code: the next preview must reflect the new text AND a
        # higher codebook revision — this is the "codebook drives the
        # prompt" behaviour the UI surfaces.
        update_code_fields(
            td, code["id"], details={"definition": "Second definition."},
            project="P", actor="tester")
        prev2 = _preview(mgr)
        assert "Second definition." in prev2["full_prompt"]
        assert "First definition." not in prev2["full_prompt"]
        assert prev2["codebook_revision"] > prev1["codebook_revision"]

    def test_missing_text_returns_none(self, td):
        mgr = _manager(td)
        from unittest.mock import patch
        with patch.object(mgr, "_get_instance_text", return_value=""):
            assert mgr.get_prompt_preview("nope") is None


def _fake_endpoint(label, confidence=80):
    """An endpoint whose .query() returns a fixed label dict."""
    from unittest.mock import MagicMock
    ep = MagicMock()
    resp = MagicMock()
    resp.model_dump.return_value = {
        "label": label, "confidence": confidence, "reasoning": "because"}
    ep.query.return_value = resp
    ep.model = "fake-model"
    return ep


class TestOnDemandSuggestion:
    def test_labels_on_demand_when_missing(self, td):
        mgr = _manager(td)
        from unittest.mock import patch
        with patch.object(mgr, "_get_instance_text", return_value="some text"), \
             patch.object(mgr.llm_labeling_thread, "_get_endpoint",
                          return_value=_fake_endpoint("access barriers")):
            sugg = mgr.get_or_create_llm_suggestion("i1")
        assert sugg is not None
        assert sugg["label"] == "access barriers"
        # Cached as a prediction so the annotate route renders it next time.
        assert mgr.get_llm_prediction_for_instance("i1")["label"] == "access barriers"

    def test_returns_existing_without_relabeling(self, td):
        mgr = _manager(td)
        from unittest.mock import patch
        with patch.object(mgr, "_get_instance_text", return_value="t"), \
             patch.object(mgr.llm_labeling_thread, "_get_endpoint",
                          return_value=_fake_endpoint("cost concerns")) as ep_getter:
            mgr.get_or_create_llm_suggestion("i2")          # first: labels
            ep_getter.reset_mock()
            again = mgr.get_or_create_llm_suggestion("i2")  # second: cached
            ep_getter.assert_not_called()
        assert again["label"] == "cost concerns"

    def test_no_endpoint_returns_none(self, td):
        mgr = _manager(td)
        from unittest.mock import patch
        with patch.object(mgr, "_get_instance_text", return_value="t"), \
             patch.object(mgr.llm_labeling_thread, "_get_endpoint",
                          return_value=None):
            assert mgr.get_or_create_llm_suggestion("i3") is None
