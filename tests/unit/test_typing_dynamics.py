"""
Unit tests for potato.typing_dynamics.

The core assertion here is not that individual numbers are right in isolation,
but that the features actually *separate* the three writing behaviours the
feature exists to distinguish: natural composition, copy-typing, and pasting.
A summarizer whose numbers are all plausible but which cannot tell those apart
would be useless, and would pass a weaker test suite.
"""

import math
import random

import pytest

from potato.typing_dynamics import (
    DEFAULT_PAUSE_THRESHOLDS_MS,
    INPUT_TYPES,
    KEY_CLASSES,
    LEGITIMATE_PASTE_SOURCES,
    TypingEvent,
    TypingSummary,
    merge_summaries,
    pack_events,
    pack_events_b64,
    summarize,
    unpack_events,
    unpack_events_b64,
)


# ---------------------------------------------------------------------------
# Synthetic trace builders
# ---------------------------------------------------------------------------


def natural_trace(n=400, seed=11):
    """Human composition: log-normal intervals, thinking pauses, revisions."""
    rng = random.Random(seed)
    ev, t, pos = [], 0, 0
    for i in range(n):
        t += int(rng.lognormvariate(4.9, 0.55))
        if i % 40 == 0:
            t += rng.randint(1500, 6000)
        if i % 60 == 59:
            for _ in range(3):
                t += rng.randint(80, 200)
                pos -= 1
                ev.append(TypingEvent(t, "deleteContentBackward", "bksp", pos, -1))
        cls = "space" if i % 6 == 5 else ("punct" if i % 47 == 46 else "letter")
        ev.append(TypingEvent(t, "insertText", cls, pos, 1))
        pos += 1
    return ev


def transcription_trace(n=400, seed=3):
    """Copy typing: near-metronomic, no pauses, no revision."""
    rng = random.Random(seed)
    ev, t, pos = [], 0, 0
    for i in range(n):
        t += int(rng.gauss(115, 10))
        cls = "space" if i % 6 == 5 else "letter"
        ev.append(TypingEvent(t, "insertText", cls, pos, 1))
        pos += 1
    return ev


def paste_trace(source="external", paste_chars=287, blur_ms=16400):
    """Away from the tab, back, paste, then a few characters of tidying."""
    ev = [
        TypingEvent(0, "focus", "unknown", 0, 0),
        TypingEvent(300, "blur", "unknown", 0, 0, {"blur_ms": blur_ms}),
        TypingEvent(blur_ms + 400, "insertFromPaste", "unknown", 0, paste_chars,
                    {"paste_source": source}),
    ]
    t = blur_ms + 1000
    for i in range(5):
        t += 180
        ev.append(TypingEvent(t, "insertText", "letter", paste_chars + i, 1))
    return ev


# ---------------------------------------------------------------------------
# Discrimination — the tests that actually matter
# ---------------------------------------------------------------------------


class TestBehaviouralDiscrimination:
    """The features must separate composed / transcribed / pasted text."""

    def test_transcription_has_far_lower_rhythm_variance(self):
        natural = summarize(natural_trace())
        transcribed = summarize(transcription_trace())
        # Crossley et al. (2024): transcription shows lower process variance.
        assert transcribed.iki_log_cv < natural.iki_log_cv / 2, (
            f"transcription CV {transcribed.iki_log_cv:.4f} should be far below "
            f"natural CV {natural.iki_log_cv:.4f}"
        )

    def test_natural_composition_pauses_and_revises(self):
        natural = summarize(natural_trace())
        transcribed = summarize(transcription_trace())
        assert natural.pause_counts["2000"] > 0
        assert transcribed.pause_counts["2000"] == 0
        assert natural.revision_ratio > 0
        assert transcribed.revision_ratio == 0

    def test_natural_composition_produces_multiple_bursts(self):
        natural = summarize(natural_trace())
        transcribed = summarize(transcription_trace())
        assert natural.bursts > transcribed.bursts

    def test_paste_dominates_the_character_budget(self):
        s = summarize(paste_trace(), final_chars=292)
        assert s.pasted_fraction > 0.9
        assert s.paste_events == 1
        assert s.largest_paste_chars == 287

    def test_paste_produces_keystroke_character_mismatch(self):
        """Asher et al.'s signal: keystrokes far too few for the text length."""
        s = summarize(paste_trace(), final_chars=292)
        assert s.keystrokes == 5
        assert s.chars_inserted == 292
        assert s.silent_insert_ratio > 0.9
        assert s.chars_per_keystroke > 50

    def test_typed_text_has_no_silent_insertion(self):
        s = summarize(natural_trace())
        assert s.silent_insert_chars == 0
        assert s.silent_insert_ratio == 0.0
        assert s.external_insert_ratio == 0.0

    def test_time_away_is_attributed_to_the_following_insertion(self):
        s = summarize(paste_trace(blur_ms=16400), final_chars=292)
        assert s.max_blur_before_insert_ms == 16400
        assert s.blur_events == 1


class TestPasteSourceAttribution:
    """Quoting the passage must not read the same as importing from off-screen."""

    @pytest.mark.parametrize("source", sorted(LEGITIMATE_PASTE_SOURCES))
    def test_legitimate_sources_excluded_from_external_ratio(self, source):
        s = summarize(paste_trace(source=source), final_chars=292)
        # It is still a silent insertion...
        assert s.silent_insert_ratio > 0.9
        # ...but not an externally-sourced one.
        assert s.external_insert_chars == 0
        assert s.external_insert_ratio == 0.0

    @pytest.mark.parametrize("source", ["external", "unknown", "ai_suggestion"])
    def test_non_legitimate_sources_counted_as_external(self, source):
        s = summarize(paste_trace(source=source), final_chars=292)
        assert s.external_insert_chars == 287
        assert s.external_insert_ratio > 0.9

    def test_paste_chars_tracked_per_source(self):
        events = (paste_trace(source="external", paste_chars=100)
                  + [TypingEvent(60000, "insertFromPaste", "unknown", 100, 50,
                                 {"paste_source": "instance_text"})])
        s = summarize(events, final_chars=155)
        assert s.paste_chars_by_source == {"external": 100, "instance_text": 50}
        assert s.external_insert_chars == 100

    def test_drop_counts_as_external(self):
        events = [
            TypingEvent(0, "focus", "unknown", 0, 0),
            TypingEvent(500, "insertFromDrop", "unknown", 0, 120),
        ]
        s = summarize(events, final_chars=120)
        assert s.drop_events == 1
        assert s.external_insert_chars == 120


class TestRhythmStatistics:
    def test_paste_events_do_not_enter_the_iki_distribution(self):
        """A paste is one event covering hundreds of characters. Treating it as
        an inter-key interval would fabricate a rhythm nobody produced."""
        typed = summarize(transcription_trace(n=100))
        with_paste = summarize(
            transcription_trace(n=100)
            + [TypingEvent(999999, "insertFromPaste", "unknown", 100, 500,
                           {"paste_source": "external"})],
            final_chars=600,
        )
        assert with_paste.iki_median_ms == pytest.approx(typed.iki_median_ms, rel=0.01)

    def test_very_long_gaps_excluded_from_rhythm(self):
        """A coffee break must not dominate the rhythm statistics."""
        events = [TypingEvent(i * 120, "insertText", "letter", i, 1) for i in range(50)]
        events.append(TypingEvent(50 * 120 + 600_000, "insertText", "letter", 50, 1))
        s = summarize(events)
        assert s.iki_median_ms == pytest.approx(120, abs=5)
        assert s.iki_p90_ms < 1000

    def test_percentiles_are_ordered(self):
        s = summarize(natural_trace())
        assert s.iki_p10_ms <= s.iki_p25_ms <= s.iki_median_ms
        assert s.iki_median_ms <= s.iki_p75_ms <= s.iki_p90_ms

    def test_pause_counts_are_monotonically_decreasing(self):
        s = summarize(natural_trace())
        counts = [s.pause_counts[str(t)] for t in DEFAULT_PAUSE_THRESHOLDS_MS]
        assert counts == sorted(counts, reverse=True)

    def test_custom_pause_thresholds_are_honoured(self):
        s = summarize(natural_trace(), pause_thresholds_ms=[250, 3000])
        assert set(s.pause_counts) == {"250", "3000"}


class TestRevisionTracking:
    def test_editing_behind_the_caret_counts_as_non_terminal(self):
        events = [TypingEvent(i * 100, "insertText", "letter", i, 1) for i in range(20)]
        # Go back into the middle of the text and insert.
        events.append(TypingEvent(3000, "insertText", "letter", 5, 1))
        s = summarize(events)
        assert s.non_terminal_edits == 1

    def test_appending_is_not_a_revision(self):
        s = summarize([TypingEvent(i * 100, "insertText", "letter", i, 1)
                       for i in range(20)])
        assert s.non_terminal_edits == 0

    def test_caret_jumps_counted(self):
        events = [TypingEvent(i * 100, "insertText", "letter", i, 1) for i in range(10)]
        events.append(TypingEvent(2000, "keydown", "nav", 2, 0))
        s = summarize(events)
        assert s.caret_jumps >= 1

    def test_undo_recorded(self):
        events = [TypingEvent(0, "insertText", "letter", 0, 1),
                  TypingEvent(500, "historyUndo", "unknown", 1, -1)]
        s = summarize(events)
        assert s.undo_events == 1


class TestIntegritySignals:
    def test_untrusted_events_counted(self):
        events = [TypingEvent(i * 20, "insertText", "letter", i, 1, {"is_trusted": False})
                  for i in range(50)]
        assert summarize(events).untrusted_events == 50

    def test_trusted_events_not_counted(self):
        events = [TypingEvent(i * 120, "insertText", "letter", i, 1) for i in range(50)]
        assert summarize(events).untrusted_events == 0

    def test_composition_events_counted(self):
        events = [TypingEvent(i * 150, "insertCompositionText", "unknown", i, 1,
                              {"composing": True}) for i in range(10)]
        assert summarize(events).composition_events == 10

    def test_virtual_keyboard_flag_carried_through(self):
        assert summarize(natural_trace(), virtual_keyboard=True).virtual_keyboard is True
        assert summarize(natural_trace()).virtual_keyboard is False


class TestEdgeCases:
    def test_empty_stream_yields_zero_summary(self):
        s = summarize([])
        assert s.keystrokes == 0
        assert s.final_chars == 0
        assert s.iki_median_ms == 0.0
        assert s.pause_counts == {str(t): 0 for t in DEFAULT_PAUSE_THRESHOLDS_MS}

    def test_single_event_does_not_divide_by_zero(self):
        s = summarize([TypingEvent(0, "insertText", "letter", 0, 1)])
        assert s.keystrokes == 1
        assert s.iki_log_cv == 0.0

    def test_events_sorted_defensively(self):
        """The client batches, so a late flush can arrive out of order."""
        ordered = [TypingEvent(i * 100, "insertText", "letter", i, 1) for i in range(10)]
        shuffled = list(reversed(ordered))
        assert summarize(shuffled).iki_median_ms == summarize(ordered).iki_median_ms

    def test_explicit_final_chars_wins_over_derived_length(self):
        """Matters when the annotator returns to a field with a saved draft."""
        events = [TypingEvent(i * 100, "insertText", "letter", i, 1) for i in range(10)]
        assert summarize(events).final_chars == 10
        assert summarize(events, final_chars=250).final_chars == 250

    def test_pasted_fraction_clamped_to_one(self):
        """Deleting after pasting can otherwise push the ratio above 1."""
        s = summarize(paste_trace(paste_chars=500), final_chars=100)
        assert s.pasted_fraction == 1.0

    def test_unknown_vocabulary_coerced_not_raised(self):
        e = TypingEvent.from_dict({
            "t_ms": 5, "input_type": "someFutureType",
            "key_class": "quantum", "pos": 0, "delta": 1,
        })
        assert e.input_type == "other"
        assert e.key_class == "unknown"


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------


class TestPacking:
    def test_roundtrip_preserves_every_field(self):
        original = natural_trace(200)
        restored = unpack_events(pack_events(original))
        assert len(restored) == len(original)
        for a, b in zip(original, restored):
            assert (a.t_ms, a.pos, a.delta, a.input_type, a.key_class) == \
                   (b.t_ms, b.pos, b.delta, b.input_type, b.key_class)

    def test_roundtrip_preserves_sparse_metadata(self):
        original = paste_trace()
        restored = unpack_events(pack_events(original))
        pastes = [e for e in restored if e.input_type == "insertFromPaste"]
        assert pastes[0].meta["paste_source"] == "external"
        blurs = [e for e in restored if e.input_type == "blur"]
        assert blurs[0].meta["blur_ms"] == 16400

    def test_base64_roundtrip(self):
        original = natural_trace(50)
        assert len(unpack_events_b64(pack_events_b64(original))) == len(original)

    def test_empty_roundtrip(self):
        assert pack_events([]) == b""
        assert unpack_events(b"") == []
        assert unpack_events(None) == []
        assert unpack_events_b64(None) == []

    def test_packing_stays_under_three_bytes_per_event(self):
        """Volume is the reason this feature stores streams in SQLite instead of
        user_state.json; if packing regressed, that calculus would change."""
        events = natural_trace(3000)
        blob = pack_events(events)
        assert len(blob) / len(events) < 3.0, (
            f"{len(blob) / len(events):.2f} bytes/event is larger than expected"
        )

    def test_unknown_pack_version_rejected(self):
        import json
        import zlib
        bad = zlib.compress(json.dumps({"v": 999, "n": 0}).encode())
        with pytest.raises(ValueError, match="version"):
            unpack_events(bad)

    def test_vocabularies_are_append_only(self):
        """Codes are persisted inside packed blobs, so reordering these lists
        would silently reinterpret every stored stream."""
        assert KEY_CLASSES[0] == "unknown"
        assert KEY_CLASSES[:6] == ["unknown", "letter", "digit", "punct", "space", "enter"]
        assert INPUT_TYPES[0] == "other"
        assert INPUT_TYPES[1] == "insertText"


# ---------------------------------------------------------------------------
# Serialization and merging
# ---------------------------------------------------------------------------


class TestSummarySerialization:
    def test_roundtrip(self):
        s = summarize(natural_trace(), schema_name="notes", label_name="body")
        restored = TypingSummary.from_dict(s.to_dict())
        assert restored.to_dict() == s.to_dict()

    def test_missing_fields_get_defaults(self):
        """Summaries written before a feature was added must still load."""
        restored = TypingSummary.from_dict({"keystrokes": 5})
        assert restored.keystrokes == 5
        assert restored.iki_log_cv == 0.0
        assert restored.paste_sources == {}

    def test_no_shared_mutable_state_between_instances(self):
        a = TypingSummary.from_dict({})
        b = TypingSummary.from_dict({})
        a.paste_sources["external"] = 1
        assert b.paste_sources == {}


class TestMergeSummaries:
    def test_counts_add(self):
        a = summarize(natural_trace(100, seed=1))
        b = summarize(natural_trace(100, seed=2))
        merged = merge_summaries([a, b])
        assert merged.keystrokes == a.keystrokes + b.keystrokes
        assert merged.chars_typed == a.chars_typed + b.chars_typed

    def test_maxima_take_the_max(self):
        a = summarize(paste_trace(blur_ms=5000), final_chars=292)
        b = summarize(paste_trace(blur_ms=20000), final_chars=292)
        assert merge_summaries([a, b]).max_blur_before_insert_ms == 20000

    def test_final_chars_from_the_last_session(self):
        a = summarize(natural_trace(50), final_chars=50)
        b = summarize(natural_trace(50), final_chars=120)
        assert merge_summaries([a, b]).final_chars == 120

    def test_paste_sources_combined(self):
        a = summarize(paste_trace(source="external"), final_chars=292)
        b = summarize(paste_trace(source="instance_text"), final_chars=292)
        merged = merge_summaries([a, b])
        assert merged.paste_sources == {"external": 1, "instance_text": 1}
        assert merged.external_insert_chars == 287

    def test_ratios_recomputed_not_averaged(self):
        a = summarize(natural_trace(100))
        b = summarize(paste_trace(), final_chars=292)
        merged = merge_summaries([a, b])
        assert merged.silent_insert_ratio == pytest.approx(
            merged.silent_insert_chars / merged.chars_inserted)

    def test_single_and_empty_inputs(self):
        one = summarize(natural_trace(20))
        assert merge_summaries([one]) is one
        assert merge_summaries([]) is None
        assert merge_summaries([None]) is None
