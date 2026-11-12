"""
Unit tests for potato/authenticity.py and its config block.

The properties that carry the most weight:

- ``sanitize_snapshot`` drops unknown keys. The privacy claim -- no copied or
  pasted text is ever stored -- holds on the server only if nothing outside the
  known numeric vocabulary survives, whatever a modified client sends.
- ``record_view`` replaces a view's snapshot rather than adding to it, so a
  retried or duplicated post cannot inflate the counts that fire flags.
- Each flag fires on its own evidence and the review/suspect split is the one
  documented, so a single copy or a single tab switch never reads as "suspect".
"""

import pytest

from potato import authenticity as au
from potato.server_utils.config_module import (
    ConfigValidationError,
    DEFAULT_AUTHENTICITY_DISCLOSURE,
    get_authenticity_client_config,
    get_interaction_tracking_client_config,
    validate_authenticity_config,
)


def summary(**fields):
    return au.merge_snapshots([au.sanitize_snapshot(dict(
        {"elapsed_ms": 60000, "large_screen": True}, **fields))])


def flags(**fields):
    return au.evaluate(summary(**fields))


class TestSanitize:
    def test_drops_unknown_keys_including_text(self):
        out = au.sanitize_snapshot({
            "item_copy_events": 2,
            "pasted_text": "the answer from a chatbot",
            "clipboard": {"text": "x"},
        })
        assert out == {"item_copy_events": 2}

    def test_clamps_and_coerces(self):
        out = au.sanitize_snapshot({
            "hidden_ms": -50, "blur_ms": 1e15, "paste_events": 3.7,
            "min_window_ratio": 9, "webdriver": "yes",
        })
        assert out["hidden_ms"] == 0
        assert out["blur_ms"] == au._MAX_VALUE
        assert out["paste_events"] == 3
        assert out["min_window_ratio"] == 2.0
        assert "webdriver" not in out        # only real booleans are kept

    def test_rejects_bools_and_nan_as_counts(self):
        out = au.sanitize_snapshot({"paste_events": True, "hidden_ms": float("nan")})
        assert out == {}

    def test_non_dict_is_empty(self):
        assert au.sanitize_snapshot(["x"]) == {}

    def test_view_id_validation(self):
        assert au.valid_view_id("abc_123-XYZ")
        assert not au.valid_view_id("")
        assert not au.valid_view_id("a" * 65)
        assert not au.valid_view_id("../etc")
        assert not au.valid_view_id(42)


class TestMerge:
    def test_sums_maxes_mins_and_bools(self):
        merged = au.merge_snapshots([
            {"hidden_events": 1, "hidden_ms": 2000, "max_away_ms": 2000,
             "min_window_ratio": 0.9, "touch_input": False},
            {"hidden_events": 2, "hidden_ms": 5000, "blur_ms": 1000,
             "max_away_ms": 4000, "min_window_ratio": 0.5, "touch_input": True},
        ])
        assert merged["hidden_events"] == 3
        assert merged["away_ms"] == 8000
        assert merged["away_events"] == 3
        assert merged["max_away_ms"] == 4000
        assert merged["min_window_ratio"] == 0.5
        assert merged["touch_input"] is True
        assert merged["views"] == 2

    def test_empty(self):
        merged = au.merge_snapshots([])
        assert merged["views"] == 0
        assert "min_window_ratio" not in merged


class TestRecordView:
    def test_same_view_replaces_rather_than_adds(self):
        record = {}
        for _ in range(3):
            record = au.record_view(record, "v1", {"item_copy_events": 1}, now=100.0)
        assert record["summary"]["item_copy_events"] == 1
        assert record["summary"]["views"] == 1

    def test_views_accumulate(self):
        record = au.record_view({}, "v1", {"hidden_events": 1}, now=100.0)
        record = au.record_view(record, "v2", {"hidden_events": 2}, now=105.0)
        assert record["summary"]["hidden_events"] == 3

    def test_server_span(self):
        record = au.record_view({}, "v1", {"elapsed_ms": 1}, now=100.0)
        record = au.record_view(record, "v1", {"elapsed_ms": 2}, now=112.5)
        assert record["summary"]["server_span_ms"] == 12500
        assert record["views"]["v1"]["first_seen"] == 100.0

    def test_view_cap(self):
        record = {}
        for i in range(au.MAX_VIEWS_PER_ITEM + 5):
            record = au.record_view(record, f"v{i}", {"hidden_events": 1}, now=1.0)
        assert len(record["views"]) == au.MAX_VIEWS_PER_ITEM
        # An existing view can still be updated at the cap.
        record = au.record_view(record, "v0", {"hidden_events": 4}, now=2.0)
        assert record["views"]["v0"]["snapshot"]["hidden_events"] == 4

    def test_detection_off_has_no_verdict(self):
        record = au.record_view({}, "v1", {"webdriver": True}, now=1.0,
                                detection=False)
        assert "verdict" not in record

    def test_stamps_phase_and_page(self):
        record = au.record_view({}, "v1", {}, now=1.0, phase="training", page="p1")
        assert record["views"]["v1"]["phase"] == "training"


class TestEvaluate:
    def test_quiet_item_is_ok(self):
        v = flags(pointer_moves=200, mouse_clicks=4)
        assert v.level == "ok"
        assert v.flags == []

    def test_automation_webdriver(self):
        v = flags(webdriver=True)
        assert v.flag_names == ["automation"]
        assert v.level == "suspect"

    def test_untrusted_events_are_review_not_automation(self):
        # Extensions can synthesize key and mouse events, so a few untrusted
        # events are synthetic_input (review); only webdriver is automation
        # (potato-skill audit 93, G3).
        assert flags(untrusted_events=2).flag_names == []
        v = flags(untrusted_events=3)
        assert v.flag_names == ["synthetic_input"]
        assert v.level == "review"

    def test_synthetic_input_threshold_is_configurable(self):
        v = au.evaluate(summary(untrusted_events=1),
                        thresholds={"synthetic_input.min_events": 1})
        assert v.flag_names == ["synthetic_input"]

    def test_webdriver_stays_suspect(self):
        v = flags(webdriver=True)
        assert v.flag_names == ["automation"]
        assert v.level == "suspect"

    def test_paste_field_alone_is_not_copy_then_paste(self):
        # G5: max_paste_words_after_item_copy without an item copy is one
        # client number, and the explanation would claim a copy that never was.
        v = flags(max_paste_words_after_item_copy=40, max_external_paste_words=40,
                  external_paste_events=1)
        assert "copy_then_paste" not in v.flag_names
        assert "external_paste" in v.flag_names

    def test_copy_then_paste_is_suspect_and_supersedes_lesser_flags(self):
        v = flags(item_copy_events=1, item_copy_chars=300,
                  external_paste_events=1, max_external_paste_words=40,
                  max_paste_words_after_item_copy=40,
                  max_away_after_item_copy_ms=30000)
        assert v.flag_names == ["copy_then_paste"]
        assert v.level == "suspect"

    def test_copy_then_away(self):
        v = flags(item_copy_events=1, item_copy_chars=300,
                  max_away_after_item_copy_ms=25000, hidden_events=1,
                  hidden_ms=25000, copy_away_pairs=[[3000, 25000, 300]])
        assert "copy_then_away" in v.flag_names
        assert "item_copied" not in v.flag_names
        assert v.level == "suspect"
        ev = v.flags[0].evidence
        assert (ev["gap_after_copy_ms"], ev["away_ms"], ev["copy_chars"]) == (3000, 25000, 300)

    def test_copy_then_away_needs_all_three_in_one_absence(self):
        # G2: a short copy, or an absence long after the copy, is not the
        # copy-ask-return workflow; and a long copy must not borrow an
        # unrelated absence's duration.
        base = dict(item_copy_events=2, item_copy_chars=320,
                    max_away_after_item_copy_ms=300000)
        word_lookup = [[2000, 30000, 9]]          # 9 chars: a looked-up word
        phone_call = [[300000, 300000, 300]]      # left 5 min after copying
        unrelated = [[1000, 2000, 300], [300000, 30000, 20]]
        for pairs in (word_lookup, phone_call, unrelated):
            v = flags(copy_away_pairs=pairs, **base)
            assert "copy_then_away" not in v.flag_names, pairs
        assert "copy_then_away" in flags(
            copy_away_pairs=unrelated + [[5000, 15000, 120]], **base).flag_names

    def test_copy_then_away_needs_an_item_copy(self):
        assert "copy_then_away" not in flags(
            copy_away_pairs=[[1000, 30000, 300]]).flag_names

    def test_copy_then_away_window_is_configurable(self):
        v = au.evaluate(summary(item_copy_events=1, item_copy_chars=300,
                                copy_away_pairs=[[90000, 30000, 300]]),
                        thresholds={"copy_then_away.max_gap_ms": 120000})
        assert "copy_then_away" in v.flag_names

    def test_short_away_after_copy_is_only_item_copied(self):
        v = flags(item_copy_events=1, item_copy_chars=300,
                  max_away_after_item_copy_ms=2000)
        assert v.flag_names == ["item_copied"]
        assert v.level == "review"

    def test_short_copy_is_not_flagged(self):
        assert flags(item_copy_events=1, item_copy_chars=8).flags == []

    def test_external_paste_without_copy_is_review(self):
        v = flags(external_paste_events=1, max_external_paste_words=25)
        assert v.flag_names == ["external_paste"]
        assert v.level == "review"

    def test_short_external_paste_not_flagged(self):
        assert flags(external_paste_events=1, max_external_paste_words=3).flags == []

    def test_one_tab_switch_is_not_flagged(self):
        assert flags(hidden_events=1, hidden_ms=4000).flags == []

    def test_many_switches(self):
        v = flags(hidden_events=2, blur_events=1, hidden_ms=6000, blur_ms=2000)
        assert v.flag_names == ["away_from_task"]
        assert v.level == "review"

    def test_long_away_needs_majority_of_time(self):
        # 70s away out of 100s elapsed -> flagged.
        assert "away_from_task" in flags(
            elapsed_ms=100000, hidden_events=1, hidden_ms=70000).flag_names
        # 70s away out of 10 min -> not.
        assert flags(elapsed_ms=600000, hidden_events=1,
                     hidden_ms=70000).flags == []

    def test_linked_away_does_not_count(self):
        assert flags(linked_away_events=5, linked_away_ms=200000).flags == []

    def test_split_screen(self):
        assert flags(min_window_ratio=0.5).flag_names == ["split_screen"]
        assert flags(min_window_ratio=0.8).flags == []

    def test_split_screen_ignored_on_small_or_touch_screens(self):
        assert flags(min_window_ratio=0.5, large_screen=False).flags == []
        assert flags(min_window_ratio=0.5, touch_input=True).flags == []

    def test_pointer_teleport(self):
        v = flags(mouse_clicks=10, teleport_clicks=4)
        assert v.flag_names == ["pointer_teleport"]
        assert v.level == "review"
        assert flags(mouse_clicks=10, teleport_clicks=2).flags == []

    def test_threshold_override(self):
        assert flags(hidden_events=2).flags == []
        v = au.evaluate(summary(hidden_events=2),
                        thresholds={"away_from_task.min_events": 2})
        assert v.flag_names == ["away_from_task"]

    def test_every_flag_carries_evidence(self):
        v = flags(webdriver=True, item_copy_events=1, item_copy_chars=300,
                  max_paste_words_after_item_copy=40, hidden_events=5,
                  min_window_ratio=0.4, mouse_clicks=10, teleport_clicks=5)
        assert len(v.flags) >= 5
        for f in v.flags:
            assert f.evidence and f.explanation


class TestConfig:
    def test_defaults_off(self):
        cfg = get_authenticity_client_config({})
        assert cfg["enabled"] is False
        assert cfg["disclosure_text"] == ""

    def test_enabled_discloses_by_default(self):
        cfg = get_authenticity_client_config({"authenticity": {"enabled": True}})
        assert cfg["enabled"] is True
        assert cfg["disclosure_text"] == DEFAULT_AUTHENTICITY_DISCLOSURE

    def test_client_config_withholds_thresholds(self):
        cfg = get_authenticity_client_config({"authenticity": {
            "enabled": True,
            "detection": {"thresholds": {"away_from_task.min_events": 9}}}})
        assert "detection" not in cfg
        assert "thresholds" not in str(cfg)

    def test_disclosure_opt_out_and_custom_text(self):
        off = get_authenticity_client_config({"authenticity": {
            "enabled": True, "disclose_to_annotators": False}})
        assert off["disclosure_text"] == ""
        custom = get_authenticity_client_config({"authenticity": {
            "enabled": True, "disclosure_text": "  Hinweis  "}})
        assert custom["disclosure_text"] == "Hinweis"

    def test_interaction_tracking_defaults(self):
        cfg = get_interaction_tracking_client_config({})
        assert cfg == {"enabled": True, "disclosure_text": ""}

    def test_interaction_tracking_disclosure_opt_in(self):
        cfg = get_interaction_tracking_client_config(
            {"interaction_tracking": {"disclose_to_annotators": True}})
        assert cfg["disclosure_text"]

    def test_interaction_tracking_off_has_no_notice(self):
        cfg = get_interaction_tracking_client_config(
            {"interaction_tracking": {"enabled": False,
                                      "disclose_to_annotators": True}})
        assert cfg == {"enabled": False, "disclosure_text": ""}

    @pytest.mark.parametrize("block", [
        "yes",
        {"enabled": "true"},
        {"min_away_ms": 0},
        {"flush_interval_ms": True},
        {"disclosure_text": "   "},
        {"detection": []},
        {"detection": {"thresholds": {"not_a_threshold": 1}}},
        {"detection": {"thresholds": {"split_screen.max_window_ratio": "low"}}},
    ])
    def test_invalid_blocks(self, block):
        with pytest.raises(ConfigValidationError):
            validate_authenticity_config({"authenticity": block})

    def test_invalid_interaction_tracking(self):
        with pytest.raises(ConfigValidationError):
            validate_authenticity_config({"interaction_tracking": {"enabled": 1}})

    def test_valid_block(self):
        validate_authenticity_config({
            "authenticity": {
                "enabled": True, "min_away_ms": 2000, "track_pointer": False,
                "detection": {"thresholds": {"away_from_task.min_events": 5}}},
            "interaction_tracking": {"enabled": False},
        })

    def test_keys_registered(self):
        from potato.server_utils.config_module import validate_unknown_keys
        import logging
        # Must not warn about any of the new keys.
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger = logging.getLogger("potato.server_utils.config_module")
        logger.addHandler(handler)
        try:
            validate_unknown_keys({
                "authenticity": {"enabled": True, "track_pointer": True,
                                 "min_away_ms": 1000, "flush_interval_ms": 1,
                                 "disclose_to_annotators": True,
                                 "disclosure_text": "x", "detection": {}},
                "interaction_tracking": {"enabled": True},
                "export_include_authenticity": True,
                "export_include_typing_dynamics": True,
            })
        finally:
            logger.removeHandler(handler)
        joined = " ".join(str(r.getMessage()) for r in records)
        assert "authenticity" not in joined
        assert "interaction_tracking" not in joined
        assert "export_include" not in joined


class TestPersistThrottle:
    """Ordinary posts reach disk at most once per PERSIST_INTERVAL_S; urgent ones always."""

    def _throttle(self):
        from potato.authenticity import PersistThrottle
        return PersistThrottle()

    def test_first_post_is_written(self):
        assert self._throttle().should_persist("u", now=100.0, urgent=False)

    def test_ordinary_posts_inside_the_interval_wait(self):
        from potato.authenticity import PERSIST_INTERVAL_S
        t = self._throttle()
        t.should_persist("u", now=100.0, urgent=False)
        assert not t.should_persist("u", now=110.0, urgent=False)
        assert not t.should_persist("u", now=100.0 + PERSIST_INTERVAL_S - 1, urgent=False)
        assert t.should_persist("u", now=100.0 + PERSIST_INTERVAL_S, urgent=False)

    def test_urgent_posts_are_always_written_and_restart_the_interval(self):
        t = self._throttle()
        t.should_persist("u", now=100.0, urgent=False)
        assert t.should_persist("u", now=100.5, urgent=True)
        assert t.should_persist("u", now=100.6, urgent=True)
        assert not t.should_persist("u", now=130.0, urgent=False)

    def test_annotators_are_independent(self):
        t = self._throttle()
        t.should_persist("a", now=100.0, urgent=False)
        assert t.should_persist("b", now=101.0, urgent=False)

    def test_clear_forgets_last_writes(self):
        from potato import authenticity
        authenticity.persist_throttle.should_persist("u", now=100.0, urgent=False)
        authenticity.clear_persist_throttle()
        assert authenticity.persist_throttle.should_persist("u", now=101.0, urgent=False)
        authenticity.clear_persist_throttle()


class TestFlagNames:
    def test_reads_verdict_flag_names(self):
        from potato.authenticity import flag_names
        assert flag_names({"verdict": {"flag_names": ["item_copied"]}}) == ["item_copied"]
        assert flag_names({}) == []
        assert flag_names(None) == []


class TestCopyAwayPairs:
    def test_sanitize_keeps_well_formed_triples_only(self):
        out = au.sanitize_snapshot({"copy_away_pairs": [
            [1, 2, 3], [1, 2], "x", [1, "a", 3], [-5, 2e12, True], [4, 5, 6]]})
        assert out["copy_away_pairs"] == [[1, 2, 3], [4, 5, 6]]

    def test_sanitize_caps_per_view(self):
        out = au.sanitize_snapshot({"copy_away_pairs": [[1, 2, 3]] * 100})
        assert len(out["copy_away_pairs"]) == au.MAX_PAIRS_PER_VIEW

    def test_merge_concatenates_views_longest_absence_first(self):
        merged = au.merge_snapshots([
            {"copy_away_pairs": [[1, 5000, 50]]},
            {"copy_away_pairs": [[2, 9000, 60]]}])
        assert merged["copy_away_pairs"] == [[2, 9000, 60], [1, 5000, 50]]


class TestShutdownFlush:
    def test_flush_writes_only_users_with_held_posts(self):
        t = au.persist_throttle
        au.clear_persist_throttle()
        t.should_persist("held", now=100.0, urgent=False)
        t.should_persist("held", now=110.0, urgent=False)      # held in memory
        t.should_persist("written", now=100.0, urgent=False)
        saved = []
        assert au.flush_pending(saved.append) == 1
        assert saved == ["held"]
        assert au.flush_pending(saved.append) == 0             # cleared
        au.clear_persist_throttle()

    def test_a_later_write_clears_the_hold(self):
        au.clear_persist_throttle()
        t = au.persist_throttle
        t.should_persist("u", now=100.0, urgent=False)
        t.should_persist("u", now=110.0, urgent=False)
        t.should_persist("u", now=111.0, urgent=True)
        assert au.flush_pending(lambda _u: None) == 0
        au.clear_persist_throttle()

    def test_flush_survives_a_failing_save(self):
        au.clear_persist_throttle()
        t = au.persist_throttle
        for u in ("a", "b"):
            t.should_persist(u, now=100.0, urgent=False)
            t.should_persist(u, now=110.0, urgent=False)

        def save(u):
            if u == "a":
                raise OSError("disk full")
        assert au.flush_pending(save) == 1
        au.clear_persist_throttle()


class TestShutdownFlushOnSigterm:
    def test_sigterm_writes_held_posts(self):
        """A held post reaches disk when the process is stopped with SIGTERM (G6)."""
        import os
        import subprocess
        import sys
        from tests.helpers.test_utils import create_test_directory
        out_dir = create_test_directory("authenticity_sigterm")
        marker = os.path.join(out_dir, "saved.txt")
        if os.path.exists(marker):
            os.remove(marker)
        script = (
            "import os, signal, time\n"
            "from potato import authenticity as au\n"
            f"marker = {marker!r}\n"
            "def save(u):\n"
            "    open(marker, 'a').write(u + '\\n')\n"
            "au.install_shutdown_flush(save)\n"
            "au.persist_throttle.should_persist('alice', now=100.0, urgent=False)\n"
            "au.persist_throttle.should_persist('alice', now=110.0, urgent=False)\n"
            "os.kill(os.getpid(), signal.SIGTERM)\n"
            "time.sleep(5)\n"
        )
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        proc = subprocess.run([sys.executable, "-c", script], cwd=repo,
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 128 + 15, proc.stderr
        assert open(marker).read().split() == ["alice"]   # once, not twice
