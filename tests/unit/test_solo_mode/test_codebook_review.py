"""Integration tests for codebook output-change review in the solo
manager: the synchronous on-demand sweep (run_codebook_review_now, behind
POST /admin/review/run) and the automatic, listener-driven sweep that
fires when a prompt-affecting codebook edit lands."""

import threading
import pytest
from unittest.mock import MagicMock, patch

from potato.solo_mode.manager import (
    SoloModeManager, LLMPrediction, clear_solo_mode_manager,
)
from potato.solo_mode.config import parse_solo_mode_config
from potato.codebook import (
    create_code, update_code_fields, review, clear_change_listeners,
    current_revision, changelog,
)
from potato.codebook import store
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import (
    clear_db_cache, clear_migrations, register_migration,
)


SCHEMES = [{"name": "sentiment", "annotation_type": "radio",
            "codebook": True, "labels": ["positive", "negative", "neutral"]}]


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


def _manager(td, state_dir=None):
    sm = {"enabled": True, "labeling_models": []}
    if state_dir is not None:
        sm["state_dir"] = state_dir
    solo_config = parse_solo_mode_config(
        {"solo_mode": sm, "annotation_schemes": SCHEMES})
    app_config = {"task_dir": td, "annotation_task_name": "P",
                  "annotation_schemes": SCHEMES}
    mgr = SoloModeManager(solo_config, app_config)
    # A bare manager has no prompt version yet; give the labeler a prompt
    # so _label_instance actually queries the (faked) endpoint.
    mgr.llm_labeling_thread.prompt_getter = lambda: "Classify the text."
    return mgr


def _fake_endpoint(label, confidence=80):
    """An endpoint whose .query() returns a fixed label."""
    ep = MagicMock()
    resp = MagicMock()
    resp.model_dump.return_value = {
        "label": label, "confidence": confidence, "reasoning": "x"}
    ep.query.return_value = resp
    ep.model = "fake-model"
    return ep


def _seed_prediction(mgr, iid="i1", label="positive", conf=0.9):
    mgr.set_llm_prediction(iid, "sentiment", LLMPrediction(
        instance_id=iid, schema_name="sentiment", predicted_label=label,
        confidence_score=conf, uncertainty_score=1 - conf,
        prompt_version=1, model_name="m", reasoning="r"))


class TestOnDemandReview:
    def test_flip_creates_flag(self, td):
        mgr = _manager(td)
        _seed_prediction(mgr, "i1", "positive")
        with patch.object(mgr, "_get_instance_text", return_value="some text"):
            summary = mgr.run_codebook_review_now(
                endpoint=_fake_endpoint("negative"))
        assert summary["relabeled"] == 1
        assert summary["flagged"] == 1
        flags = review.list_flags(td, "P")
        assert len(flags) == 1
        assert flags[0]["instance_id"] == "i1"
        assert flags[0]["old_label"] == "positive"
        assert flags[0]["new_label"] == "negative"
        assert flags[0]["severity"] == "high"

    def test_stable_label_no_flag(self, td):
        mgr = _manager(td)
        _seed_prediction(mgr, "i1", "positive")
        with patch.object(mgr, "_get_instance_text", return_value="some text"):
            summary = mgr.run_codebook_review_now(
                endpoint=_fake_endpoint("positive"))
        assert summary["relabeled"] == 1
        assert summary["flagged"] == 0
        assert review.open_count(td, "P") == 0

    def test_no_endpoint_reports_reason(self, td):
        mgr = _manager(td)
        _seed_prediction(mgr, "i1", "positive")
        # No endpoint passed and the lazy thread has none configured.
        with patch.object(mgr.llm_labeling_thread, "_get_endpoint",
                          return_value=None):
            summary = mgr.run_codebook_review_now()
        assert summary["relabeled"] == 0
        assert "reason" in summary

    def test_max_instances_caps_sweep(self, td):
        mgr = _manager(td)
        _seed_prediction(mgr, "i1", "positive")
        _seed_prediction(mgr, "i2", "positive")
        _seed_prediction(mgr, "i3", "positive")
        with patch.object(mgr, "_get_instance_text", return_value="t"):
            summary = mgr.run_codebook_review_now(
                endpoint=_fake_endpoint("negative"), max_instances=2)
        assert summary["relabeled"] == 2


class _SyncThread:
    """Stand-in for threading.Thread that runs the target synchronously on
    start(), so the listener-driven sweep is deterministic in tests."""
    def __init__(self, target=None, args=(), name=None, daemon=None, **kw):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


class TestAutomaticListener:
    def test_edit_definition_triggers_review_and_flags(self, td):
        mgr = _manager(td)
        # First codebook change establishes the review baseline (the
        # listener is already registered by the manager).
        code = create_code(td, project="P", name="positive",
                           created_by="u", details={"definition": "old"})
        _seed_prediction(mgr, "i1", "positive")

        mgr.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))
        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr, "_get_instance_text", return_value="text"):
            # A prompt-affecting edit fires the listener -> sync sweep.
            update_code_fields(td, code["id"], project="P",
                               details={"definition": "a new definition"})

        flags = review.list_flags(td, "P")
        assert len(flags) == 1
        assert flags[0]["instance_id"] == "i1"
        assert flags[0]["old_label"] == "positive"
        assert flags[0]["new_label"] == "negative"
        # The flag is tied back to the originating change.
        assert flags[0]["change_id"]

    def test_unrelated_edit_does_not_flag(self, td):
        mgr = _manager(td)
        create_code(td, project="P", name="positive", created_by="u")
        other = create_code(td, project="P", name="neutral",
                            created_by="u", details={"definition": "d"})
        _seed_prediction(mgr, "i1", "positive")  # labeled 'positive'

        mgr.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))
        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr, "_get_instance_text", return_value="text"):
            # Editing 'neutral' must not touch the 'positive' instance.
            update_code_fields(td, other["id"], project="P",
                               details={"definition": "changed"})

        assert review.open_count(td, "P") == 0

    def test_recolor_does_not_trigger_sweep(self, td):
        from potato.codebook import recolor_code
        mgr = _manager(td)
        code = create_code(td, project="P", name="positive", created_by="u")
        _seed_prediction(mgr, "i1", "positive")

        # If a sweep ran it would raise (endpoint asserts not-called).
        mgr.llm_labeling_thread._get_endpoint = MagicMock(
            side_effect=AssertionError("recolor must not sweep"))
        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr, "_get_instance_text", return_value="text"):
            recolor_code(td, code["id"], color="#fff", project="P")

        assert review.open_count(td, "P") == 0


class TestReviewRevisionPersistence:
    """The codebook re-review bookmark (_last_review_revision) must survive
    a restart so the listener resumes from where it left off rather than
    re-reviewing already-processed changes."""

    def test_revision_survives_save_load_round_trip(self, td, tmp_path):
        sd = str(tmp_path / "state")
        mgr = _manager(td, state_dir=sd)
        mgr._last_review_revision = 7
        mgr._save_state()

        mgr2 = _manager(td, state_dir=sd)
        assert mgr2._last_review_revision is None  # not yet loaded
        assert mgr2.load_state() is True
        assert mgr2._last_review_revision == 7

    def test_none_bookmark_survives_round_trip(self, td, tmp_path):
        # A manager that has not yet observed any change keeps None (rather
        # than silently resetting to 0) across a save/load.
        sd = str(tmp_path / "state")
        mgr = _manager(td, state_dir=sd)
        assert mgr._last_review_revision is None
        mgr._save_state()

        mgr2 = _manager(td, state_dir=sd)
        assert mgr2.load_state() is True
        assert mgr2._last_review_revision is None

    def test_sweep_after_reload_does_not_reflag_processed_change(
            self, td, tmp_path):
        sd = str(tmp_path / "state")
        mgr = _manager(td, state_dir=sd)
        code = create_code(td, project="P", name="positive", created_by="u",
                           details={"definition": "old"})
        _seed_prediction(mgr, "i1", "positive")
        mgr.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))

        # A prompt-affecting edit is processed; one flag is created and the
        # bookmark advances to the current changelog revision.
        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr, "_get_instance_text", return_value="text"):
            update_code_fields(td, code["id"], project="P",
                               details={"definition": "a new definition"})
        assert review.open_count(td, "P") == 1
        assert mgr._last_review_revision == current_revision(td, "P")
        mgr._save_state()

        # Simulate a restart: a fresh manager rehydrated from saved state.
        clear_change_listeners()
        mgr2 = _manager(td, state_dir=sd)
        assert mgr2.load_state() is True
        # Resumed from the persisted revision, not 0/None.
        assert mgr2._last_review_revision == current_revision(td, "P")
        mgr2.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))

        # The listener fires but no NEW change has landed since the
        # bookmark, so the already-processed edit is not re-reviewed.
        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr2, "_get_instance_text", return_value="text"):
            mgr2._on_codebook_change(td, "P")
        assert review.open_count(td, "P") == 1

    def test_genuinely_new_change_after_reload_is_reviewed(self, td, tmp_path):
        # The flip side of resume: a NEW edit after reload must still be
        # picked up (the bookmark didn't reset to current and swallow it).
        sd = str(tmp_path / "state")
        mgr = _manager(td, state_dir=sd)
        code = create_code(td, project="P", name="positive", created_by="u",
                           details={"definition": "old"})
        _seed_prediction(mgr, "i1", "positive")
        mgr.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))
        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr, "_get_instance_text", return_value="text"):
            update_code_fields(td, code["id"], project="P",
                               details={"definition": "def two"})
        assert review.open_count(td, "P") == 1
        mgr._save_state()

        clear_change_listeners()
        mgr2 = _manager(td, state_dir=sd)
        mgr2.load_state()
        mgr2.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))

        # A genuinely new prompt-affecting edit arrives -> it has a distinct
        # change_id, so it flags again (not deduped against the prior open
        # flag, which came from a different change).
        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr2, "_get_instance_text", return_value="text"):
            update_code_fields(td, code["id"], project="P",
                               details={"definition": "def three"})
        assert review.open_count(td, "P") == 2


class TestFlagDeduplication:
    """An instance must not accumulate multiple OPEN flags for the same
    underlying change. De-dup key: (instance_id, schema_name, change_id),
    open flags only."""

    def test_rerun_sweep_does_not_duplicate_open_flag(self, td):
        mgr = _manager(td)
        _seed_prediction(mgr, "i1", "positive")
        with patch.object(mgr, "_get_instance_text", return_value="some text"):
            s1 = mgr.run_codebook_review_now(
                endpoint=_fake_endpoint("negative"))
            s2 = mgr.run_codebook_review_now(
                endpoint=_fake_endpoint("negative"))
        assert s1["flagged"] == 1
        # Second sweep finds the open flag and skips the re-label entirely.
        assert s2["relabeled"] == 0
        assert s2["flagged"] == 0
        assert s2["deduped"] == 1
        assert review.open_count(td, "P") == 1

    def test_reflags_after_resolve(self, td):
        mgr = _manager(td)
        _seed_prediction(mgr, "i1", "positive")
        with patch.object(mgr, "_get_instance_text", return_value="some text"):
            mgr.run_codebook_review_now(endpoint=_fake_endpoint("negative"))
        flags = review.list_flags(td, "P")
        assert len(flags) == 1
        assert review.resolve_flag(
            td, flags[0]["id"], status="reviewed", reviewed_by="u")

        # With the prior flag resolved, a subsequent sweep flags again.
        with patch.object(mgr, "_get_instance_text", return_value="some text"):
            s = mgr.run_codebook_review_now(
                endpoint=_fake_endpoint("negative"))
        assert s["relabeled"] == 1
        assert s["flagged"] == 1
        assert review.open_count(td, "P") == 1

    def test_listener_double_fire_same_change_dedupes(self, td):
        mgr = _manager(td)
        code = create_code(td, project="P", name="positive", created_by="u",
                           details={"definition": "old"})
        _seed_prediction(mgr, "i1", "positive")
        mgr.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))

        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr, "_get_instance_text", return_value="text"):
            update_code_fields(td, code["id"], project="P",
                               details={"definition": "new def"})
            assert review.open_count(td, "P") == 1
            # Replay the SAME change set through the sweep directly: the
            # affected map carries the same change_id, so no second flag.
            cb_changes = {"positive": review.list_flags(td, "P")[0]["change_id"]}
            mgr._sweep_codebook_review(td, "P", affected=cb_changes)
        assert review.open_count(td, "P") == 1

    def test_has_open_flag_null_safe_key(self, td):
        # Direct check of the de-dup predicate with NULL change_id/schema.
        assert review.has_open_flag(td, "P", "i1") is False
        review.record_flag(
            td, project="P", instance_id="i1", schema_name="sentiment",
            old_label="positive", new_label="negative")
        assert review.has_open_flag(
            td, "P", "i1", schema_name="sentiment") is True
        # A different change_id is a different key.
        assert review.has_open_flag(
            td, "P", "i1", schema_name="sentiment", change_id="c9") is False


class TestStructuredFieldReview:
    """The new structured fields (exclusion_rules / *_examples) thread
    through the existing changelog -> scoped-sweep path automatically, and
    the migration-churn guard keeps a legacy code's first save quiet."""

    def test_edit_exclusion_rules_triggers_review_and_flags(self, td):
        mgr = _manager(td)
        code = create_code(td, project="P", name="positive", created_by="u")
        _seed_prediction(mgr, "i1", "positive")
        mgr.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))

        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr, "_get_instance_text", return_value="text"):
            update_code_fields(td, code["id"], project="P", details={
                "exclusion_rules": ["the text merely mentions the word riot"]})

        flags = review.list_flags(td, "P")
        assert len(flags) == 1
        assert flags[0]["instance_id"] == "i1"
        assert flags[0]["change_id"]
        # op=edit_exclusion_rules logged with a resolvable code_id.
        hist = [h for h in changelog.code_history(td, "P", code["id"])
                if h["op"] == "edit_exclusion_rules"]
        assert len(hist) == 1
        assert hist[0]["code_id"] == code["id"]

    def test_legacy_resave_unchanged_then_real_change(self, td):
        # Refinement A, end to end: a freshly-migrated legacy code saved
        # back unchanged must NOT flag; a genuine edit afterwards must.
        mgr = _manager(td)
        code = create_code(td, project="P", name="positive", created_by="u")
        # Simulate pre-0006 data: only the singular columns are populated.
        conn = store._db(td)
        conn.execute(
            "UPDATE codes SET positive_example=?, positive_example_why=? "
            "WHERE id=?", ("a crowd smashed windows", "violence", code["id"]))
        conn.commit()
        _seed_prediction(mgr, "i1", "positive")
        mgr.llm_labeling_thread._get_endpoint = MagicMock(
            return_value=_fake_endpoint("negative"))

        with patch("potato.solo_mode.manager.threading.Thread", _SyncThread), \
             patch.object(mgr, "_get_instance_text", return_value="text"):
            # Save the SAME effective value back: no edit row, no sweep,
            # no flag (compares against the lazy-upgraded current value).
            update_code_fields(td, code["id"], project="P", details={
                "positive_examples": [{"text": "a crowd smashed windows",
                                       "why": "violence"}]})
            assert review.open_count(td, "P") == 0
            assert not [h for h in changelog.code_history(td, "P", code["id"])
                        if h["op"] == "edit_positive_examples"]

            # A genuine change -> exactly one edit row + a flag.
            update_code_fields(td, code["id"], project="P", details={
                "positive_examples": [{"text": "a crowd smashed windows",
                                       "why": "serious property destruction"}]})

        flags = review.list_flags(td, "P")
        assert len(flags) == 1
        assert flags[0]["instance_id"] == "i1"
        assert flags[0]["change_id"]
        hist = [h for h in changelog.code_history(td, "P", code["id"])
                if h["op"] == "edit_positive_examples"]
        assert len(hist) == 1
        assert hist[0]["code_id"] == code["id"]
