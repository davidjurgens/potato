"""
Unit tests for potato.annotation_telemetry.

The module is pure, so every test here builds a synthetic event stream by hand
and asserts on the derived features. That is the point of keeping it free of
Flask and I/O: a feature added later can be checked against a trace whose
correct answer is known by construction.
"""

import math

import pytest

from potato.annotation_telemetry import (
    ACTIONS,
    DEFAULT_THRESHOLDS,
    SHAPE_KINDS,
    ZOOM_INSPECT_THRESHOLD,
    TelemetryEvent,
    TelemetrySummary,
    TelemetryVerdict,
    calibrate_thresholds,
    evaluate,
    has_substance,
    merge_summaries,
    pack_events,
    pack_events_b64,
    summarize,
    unpack_events,
    unpack_events_b64,
)


def ev(t, action, shape="unknown", value=0, meta=None):
    return TelemetryEvent(t_ms=t, action=action, shape=shape, value=value, meta=meta)


class TestVocabularies:
    def test_unknown_is_index_zero_in_both_vocabularies(self):
        """Code 0 must mean "unknown", or an unrecognised name packs as a real one."""
        assert ACTIONS[0] == "unknown"
        assert SHAPE_KINDS[0] == "unknown"

    def test_no_duplicate_codes(self):
        assert len(set(ACTIONS)) == len(ACTIONS)
        assert len(set(SHAPE_KINDS)) == len(SHAPE_KINDS)


class TestEventRoundTrip:
    def test_pack_unpack_preserves_every_field(self):
        events = [
            ev(0, "tool", meta={"tool": "bbox"}),
            ev(120, "shape_add", "bbox", 4),
            ev(900, "zoom", value=250),
            ev(2400, "shape_add", "polygon", 9),
            ev(3000, "stroke", "mask", 412, meta={"tool": "brush"}),
        ]
        restored = unpack_events(pack_events(events))
        assert len(restored) == len(events)
        for original, back in zip(events, restored):
            assert back.t_ms == original.t_ms
            assert back.action == original.action
            assert back.shape == original.shape
            assert back.value == original.value
            assert back.meta == original.meta

    def test_empty_stream_packs_to_empty_bytes(self):
        assert pack_events([]) == b""
        assert unpack_events(b"") == []
        assert unpack_events(None) == []

    def test_base64_transport_round_trips(self):
        events = [ev(0, "shape_add", "bbox", 4), ev(50, "undo")]
        restored = unpack_events_b64(pack_events_b64(events))
        assert [e.action for e in restored] == ["shape_add", "undo"]

    def test_unsupported_pack_version_raises(self):
        import json
        import zlib

        blob = zlib.compress(json.dumps({"v": 999, "n": 0}).encode())
        with pytest.raises(ValueError, match="pack version"):
            unpack_events(blob)

    def test_unknown_action_from_a_newer_client_degrades_rather_than_raising(self):
        """Losing one event's specificity beats rejecting a whole session."""
        event = TelemetryEvent.from_dict(
            {"t_ms": 10, "action": "teleport", "shape": "hypercube", "value": 3})
        assert event.action == "unknown"
        assert event.shape == "unknown"
        assert event.value == 3


class TestSummarizeCounts:
    def test_counts_every_action_kind(self):
        summary = summarize([
            ev(0, "shape_add", "bbox", 4),
            ev(100, "shape_add", "polygon", 6),
            ev(200, "shape_edit", "bbox"),
            ev(300, "shape_remove", "bbox"),
            ev(400, "stroke", "mask", 80),
            ev(500, "fill", "mask", 900),
            ev(600, "undo"),
            ev(700, "redo"),
            ev(800, "tool"),
            ev(900, "pan", value=40),
        ])
        assert summary.shapes_added == 2
        assert summary.shapes_edited == 1
        assert summary.shapes_removed == 1
        assert summary.strokes == 1
        assert summary.stroke_px_total == 80
        assert summary.fills == 1
        assert summary.undo_count == 1
        assert summary.redo_count == 1
        assert summary.tool_switches == 1
        assert summary.pan_events == 1

    def test_shape_kinds_are_broken_out(self):
        summary = summarize([
            ev(0, "shape_add", "bbox", 4),
            ev(10, "shape_add", "bbox", 4),
            ev(20, "shape_add", "mask", 0),
        ])
        assert summary.shape_kinds == {"bbox": 2, "mask": 1}

    def test_vertices_median_ignores_shapes_with_no_vertices(self):
        """A mask has no vertices; counting it as zero would halve the median."""
        summary = summarize([
            ev(0, "shape_add", "polygon", 10),
            ev(10, "shape_add", "polygon", 20),
            ev(20, "shape_add", "mask", 0),
        ])
        assert summary.vertices_median == 15
        assert summary.vertices_total == 30

    def test_empty_stream_gives_an_empty_summary_not_an_error(self):
        summary = summarize([])
        assert summary.shapes_added == 0
        assert summary.duration_ms == 0
        assert summary.time_to_first_shape_ms is None


class TestSummarizeTiming:
    def test_unsorted_input_is_sorted_before_anything_is_derived(self):
        """A client batching from several buffers can deliver interleaved events."""
        ordered = summarize([ev(0, "shape_add", "bbox", 4),
                             ev(1000, "shape_add", "bbox", 4)])
        shuffled = summarize([ev(1000, "shape_add", "bbox", 4),
                              ev(0, "shape_add", "bbox", 4)])
        assert shuffled.duration_ms == ordered.duration_ms == 1000
        assert shuffled.shape_interval_median_ms == 1000

    def test_long_gaps_are_charged_to_idle_not_active(self):
        summary = summarize(
            [ev(0, "shape_add", "bbox", 4),
             ev(1_000, "shape_add", "bbox", 4),
             ev(500_000, "shape_add", "bbox", 4)],
            idle_ms=120_000,
        )
        assert summary.active_ms == 1_000
        assert summary.idle_ms == 499_000
        assert summary.duration_ms == 500_000

    def test_time_to_first_shape_is_measured_from_the_first_event(self):
        summary = summarize([
            ev(0, "tool"),
            ev(200, "zoom", value=200),
            ev(5_000, "shape_add", "bbox", 4),
        ])
        assert summary.time_to_first_shape_ms == 5_000

    def test_shape_interval_needs_two_shapes(self):
        one = summarize([ev(0, "shape_add", "bbox", 4)])
        assert one.shape_interval_median_ms is None
        assert one.shape_interval_min_ms is None

        two = summarize([ev(0, "shape_add", "bbox", 4),
                         ev(300, "shape_add", "bbox", 4),
                         ev(1_300, "shape_add", "bbox", 4)])
        assert two.shape_interval_median_ms == 650
        assert two.shape_interval_min_ms == 300


class TestZoom:
    def test_zoomed_time_accumulates_only_above_the_inspection_threshold(self):
        summary = summarize([
            ev(0, "tool"),
            ev(1_000, "zoom", value=300),     # 3x from here
            ev(3_000, "zoom", value=100),     # back to 1x
            ev(6_000, "shape_add", "bbox", 4),
        ])
        assert summary.max_zoom == 3.0
        assert summary.zoomed_ms == 2_000
        assert summary.zoomed_fraction == pytest.approx(2_000 / 6_000)

    def test_a_zoom_event_with_no_value_does_not_reset_the_running_level(self):
        """Otherwise a malformed event would silently read as 0.01x."""
        summary = summarize([
            ev(0, "zoom", value=400),
            ev(1_000, "zoom", value=0),
            ev(2_000, "shape_add", "bbox", 4),
        ])
        assert summary.max_zoom == 4.0
        assert summary.zoomed_ms == 2_000

    def test_fit_to_window_landing_just_above_one_is_not_inspection(self):
        summary = summarize([
            ev(0, "zoom", value=102),
            ev(10_000, "shape_add", "bbox", 4),
        ])
        assert summary.max_zoom == pytest.approx(1.02)
        assert summary.max_zoom < ZOOM_INSPECT_THRESHOLD
        assert summary.zoomed_ms == 0


class TestAISuggestionPairing:
    def test_latency_is_derived_from_suggestion_ids_not_from_the_client(self):
        summary = summarize([
            ev(0, "ai_suggest", "bbox", meta={"sid": "a"}),
            ev(0, "ai_suggest", "bbox", meta={"sid": "b"}),
            ev(300, "ai_accept", "bbox", meta={"sid": "a"}),
            ev(2_000, "ai_accept", "bbox", meta={"sid": "b"}),
        ])
        assert summary.ai_suggested == 2
        assert summary.ai_accepted == 2
        assert summary.ai_accept_latency_median_ms == 1150
        assert summary.ai_accept_latency_min_ms == 300

    def test_an_accept_with_no_matching_suggestion_contributes_no_latency(self):
        summary = summarize([ev(500, "ai_accept", "bbox", meta={"sid": "ghost"})])
        assert summary.ai_accepted == 1
        assert summary.ai_accept_latency_median_ms is None

    def test_accept_rate_is_over_suggestions_offered(self):
        summary = summarize([
            ev(0, "ai_suggest", meta={"sid": "a"}),
            ev(1, "ai_suggest", meta={"sid": "b"}),
            ev(2, "ai_suggest", meta={"sid": "c"}),
            ev(100, "ai_accept", meta={"sid": "a"}),
            ev(200, "ai_reject", meta={"sid": "b"}),
        ])
        assert summary.ai_rejected == 1
        assert summary.ai_accept_rate == pytest.approx(1 / 3)

    def test_an_edit_is_attributed_only_to_the_accept_it_follows(self):
        """One correction must not excuse a hundred rubber-stamps."""
        summary = summarize([
            ev(0, "ai_suggest", meta={"sid": "a"}),
            ev(100, "ai_accept", meta={"sid": "a"}),
            ev(200, "shape_edit", "bbox"),          # belongs to accept a
            ev(300, "ai_suggest", meta={"sid": "b"}),
            ev(400, "ai_accept", meta={"sid": "b"}),  # never corrected
            ev(500, "ai_suggest", meta={"sid": "c"}),
            ev(600, "ai_accept", meta={"sid": "c"}),  # never corrected
        ])
        assert summary.ai_accepted == 3
        assert summary.ai_accepted_then_edited == 1

    def test_an_edit_after_the_last_accept_still_counts_for_it(self):
        summary = summarize([
            ev(0, "ai_suggest", meta={"sid": "a"}),
            ev(100, "ai_accept", meta={"sid": "a"}),
            ev(900, "shape_edit", "bbox"),
        ])
        assert summary.ai_accepted_then_edited == 1

    def test_one_late_edit_does_not_credit_every_earlier_accept(self):
        """
        The failure this pins: attributing any later edit to every accept would
        let a single correction at the end of a session excuse all the
        rubber-stamping that preceded it. Written after a mutation test showed
        the previous case could not tell the two implementations apart.
        """
        summary = summarize([
            ev(0, "ai_accept", meta={"sid": "a"}),
            ev(100, "ai_accept", meta={"sid": "b"}),
            ev(200, "ai_accept", meta={"sid": "c"}),
            ev(300, "shape_edit", "bbox"),
        ])
        assert summary.ai_accepted == 3
        assert summary.ai_accepted_then_edited == 1


class TestRevisionRatio:
    def test_ratio_is_edits_over_creates_plus_edits(self):
        summary = summarize([
            ev(0, "shape_add", "bbox", 4),
            ev(10, "shape_add", "bbox", 4),
            ev(20, "shape_add", "bbox", 4),
            ev(30, "shape_edit", "bbox"),
        ])
        assert summary.revision_ratio == pytest.approx(0.25)

    def test_no_shapes_gives_zero_not_a_division_error(self):
        assert summarize([ev(0, "zoom", value=200)]).revision_ratio == 0.0


class TestEvaluate:
    def _rubber_stamp_summary(self):
        events = []
        t = 0
        for i in range(8):
            events.append(ev(t, "ai_suggest", "bbox", meta={"sid": str(i)}))
            events.append(ev(t + 200, "ai_accept", "bbox", meta={"sid": str(i)}))
            t += 400
        return summarize(events)

    def test_fast_uncorrected_accepts_are_flagged(self):
        verdict = evaluate(self._rubber_stamp_summary())
        assert "rubber_stamping" in verdict.flags
        assert verdict.scores["ai_accept_latency_median_ms"] == 200

    def test_the_flag_carries_a_note_saying_what_it_does_not_establish(self):
        """A flag surfaced without its caveat will be read as a finding."""
        verdict = evaluate(self._rubber_stamp_summary())
        note = verdict.notes["rubber_stamping"]
        assert "also with a detector" in note

    def test_correcting_the_accepted_suggestions_clears_the_flag(self):
        events = []
        t = 0
        for i in range(8):
            events.append(ev(t, "ai_suggest", "bbox", meta={"sid": str(i)}))
            events.append(ev(t + 200, "ai_accept", "bbox", meta={"sid": str(i)}))
            events.append(ev(t + 250, "shape_edit", "bbox"))
            t += 400
        verdict = evaluate(summarize(events))
        assert "rubber_stamping" not in verdict.flags

    def test_too_few_accepts_is_not_screened(self):
        """Latency over two accepts is noise, and a noisy flag trains people to ignore it."""
        summary = summarize([
            ev(0, "ai_suggest", meta={"sid": "a"}),
            ev(50, "ai_accept", meta={"sid": "a"}),
            ev(100, "ai_suggest", meta={"sid": "b"}),
            ev(150, "ai_accept", meta={"sid": "b"}),
        ])
        assert evaluate(summary).flags == []

    def test_hasty_fires_on_rapid_shape_production(self):
        events = [ev(i * 300, "shape_add", "bbox", 4) for i in range(6)]
        verdict = evaluate(summarize(events))
        assert "hasty" in verdict.flags
        assert "calibrate" in verdict.notes["hasty"]

    def test_accepted_suggestions_do_not_count_toward_drawing_pace(self):
        """
        Found by running the exporter on a two-annotator fixture: the annotator
        who reviewed each suggestion for four seconds was flagged `hasty`
        alongside the one who accepted in 120ms.

        The cause is structural, not a fixture artefact — the client commits an
        accepted suggestion through the same path as a hand-drawn shape, so it
        arrives as a `shape_add` milliseconds later. Counting those as drawing
        means the accept-latency measure says "careful" while the pace measure
        says "hasty" about the same behaviour, and the flag would fire hardest
        on exactly the annotators doing it right.
        """
        careful = []
        t = 0
        for i in range(8):
            careful.append(ev(t, "ai_suggest", "bbox", meta={"sid": str(i)}))
            careful.append(ev(t + 4_200, "ai_accept", "bbox", meta={"sid": str(i)}))
            careful.append(ev(t + 4_210, "shape_add", "bbox", 4))
            t += 4_300

        summary = summarize(careful)
        assert summary.shapes_added == 8
        assert summary.shapes_from_ai == 8
        assert summary.shapes_drawn == 0
        assert summary.shape_interval_median_ms is None
        assert evaluate(summary).flags == []

    def test_shapes_drawn_between_accepts_still_count_as_drawing(self):
        """The window attributes ONE shape to each accept, not everything after."""
        events = [
            ev(0, "ai_accept", "bbox", meta={"sid": "a"}),
            ev(50, "shape_add", "bbox", 4),      # the accepted suggestion
            ev(300, "shape_add", "bbox", 4),     # drawn by hand
            ev(900, "shape_add", "bbox", 4),     # drawn by hand
        ]
        summary = summarize(events)
        assert summary.shapes_from_ai == 1
        assert summary.shapes_drawn == 2

    def test_a_shape_long_after_an_accept_is_drawn_not_accepted(self):
        events = [
            ev(0, "ai_accept", "bbox", meta={"sid": "a"}),
            ev(9_000, "shape_add", "bbox", 4),
        ]
        summary = summarize(events)
        assert summary.shapes_from_ai == 0
        assert summary.shapes_drawn == 1

    def test_a_deliberate_pace_is_not_flagged(self):
        events = [ev(i * 9_000, "shape_add", "polygon", 12) for i in range(6)]
        assert evaluate(summarize(events)).flags == []

    def test_never_zoomed_is_reported_only_alongside_another_signal(self):
        """Alone it is uninformative: some projects need no zoom at all."""
        quiet = summarize([ev(i * 9_000, "shape_add", "bbox", 4) for i in range(6)])
        assert quiet.max_zoom == 1.0
        assert "never_zoomed" not in evaluate(quiet).flags

        hasty = summarize([ev(i * 300, "shape_add", "bbox", 4) for i in range(6)])
        assert "never_zoomed" in evaluate(hasty).flags

    def test_zooming_in_suppresses_never_zoomed_while_keeping_the_real_flag(self):
        events = [ev(0, "zoom", value=400)]
        events += [ev(1_000 + i * 300, "shape_add", "bbox", 4) for i in range(6)]
        verdict = evaluate(summarize(events))
        assert "hasty" in verdict.flags
        assert "never_zoomed" not in verdict.flags

    def test_thresholds_can_be_overridden(self):
        summary = self._rubber_stamp_summary()
        relaxed = evaluate(summary, thresholds={"ai_accept_latency_ms": 50})
        assert "rubber_stamping" not in relaxed.flags

    def test_verdict_round_trips_through_a_dict(self):
        verdict = evaluate(self._rubber_stamp_summary())
        back = TelemetryVerdict.from_dict(verdict.to_dict())
        assert back.flags == verdict.flags
        assert back.notes == verdict.notes


class TestMergeSummaries:
    def test_counts_add(self):
        a = summarize([ev(0, "shape_add", "bbox", 4), ev(100, "shape_add", "bbox", 4)])
        b = summarize([ev(0, "shape_add", "polygon", 8)])
        merged = merge_summaries([a, b])
        assert merged.shapes_added == 3
        assert merged.shape_kinds == {"bbox": 2, "polygon": 1}

    def test_a_single_summary_is_returned_unchanged(self):
        only = summarize([ev(0, "shape_add", "bbox", 4)])
        assert merge_summaries([only]) is only

    def test_empty_input_returns_none(self):
        assert merge_summaries([]) is None

    def test_rates_are_recomputed_not_averaged(self):
        """Averaging two rates over unequal denominators is simply wrong."""
        a = summarize([ev(0, "shape_add", "bbox", 4),
                       ev(1, "shape_add", "bbox", 4),
                       ev(2, "shape_add", "bbox", 4),
                       ev(3, "shape_edit", "bbox")])          # ratio 0.25
        b = summarize([ev(0, "shape_edit", "bbox")])           # ratio 1.0
        merged = merge_summaries([a, b])
        # 2 edits over 3 adds + 2 edits, not (0.25 + 1.0) / 2
        assert merged.revision_ratio == pytest.approx(2 / 5)

    def test_time_to_first_shape_takes_the_earliest(self):
        a = summarize([ev(0, "tool"), ev(9_000, "shape_add", "bbox", 4)])
        b = summarize([ev(0, "tool"), ev(400, "shape_add", "bbox", 4)])
        assert merge_summaries([a, b]).time_to_first_shape_ms == 400

    def test_max_zoom_takes_the_maximum(self):
        a = summarize([ev(0, "zoom", value=150)])
        b = summarize([ev(0, "zoom", value=800)])
        assert merge_summaries([a, b]).max_zoom == 8.0

    def test_merged_view_can_clear_a_flag_the_parts_would_fire(self):
        """Five fast accepts in one short session may be a small share of the item."""
        fast = summarize([
            e for i in range(6) for e in (
                ev(i * 400, "ai_suggest", meta={"sid": f"f{i}"}),
                ev(i * 400 + 100, "ai_accept", meta={"sid": f"f{i}"}),
            )
        ])
        assert "rubber_stamping" in evaluate(fast).flags

        careful = summarize([
            e for i in range(6) for e in (
                ev(i * 20_000, "ai_suggest", meta={"sid": f"c{i}"}),
                ev(i * 20_000 + 9_000, "ai_accept", meta={"sid": f"c{i}"}),
                ev(i * 20_000 + 9_500, "shape_edit", "bbox"),
            )
        ])
        merged = merge_summaries([fast, careful])
        assert "rubber_stamping" not in evaluate(merged).flags


class TestSummarySerialization:
    def test_round_trips_through_a_dict(self):
        summary = summarize([
            ev(0, "shape_add", "bbox", 4),
            ev(500, "zoom", value=250),
            ev(900, "ai_suggest", meta={"sid": "a"}),
            ev(1_000, "ai_accept", meta={"sid": "a"}),
        ], schema_name="objects", instance_id="img_1")
        back = TelemetrySummary.from_dict(summary.to_dict())
        assert back.to_dict() == summary.to_dict()

    def test_unknown_keys_in_stored_data_are_ignored(self):
        """Reading a state written by a newer build must not raise."""
        back = TelemetrySummary.from_dict(
            {"shapes_added": 3, "a_feature_from_the_future": 9})
        assert back.shapes_added == 3


class TestCalibration:
    def test_a_small_sample_fits_nothing(self):
        """A threshold from a handful of sessions is worse than the default:
        it looks principled."""
        rows = [{"ai_accept_latency_median_ms": 100.0} for _ in range(10)]
        assert calibrate_thresholds(rows) == {}

    def test_fits_the_requested_lower_percentile(self):
        rows = [{"ai_accept_latency_median_ms": float(i),
                 "shape_interval_median_ms": float(i * 10)}
                for i in range(100)]
        fitted = calibrate_thresholds(rows, percentile=5.0)
        assert fitted["ai_accept_latency_ms"] == pytest.approx(5.0, abs=1.0)
        assert fitted["shape_interval_ms"] == pytest.approx(50.0, abs=10.0)

    def test_missing_values_are_skipped_not_treated_as_zero(self):
        rows = [{"ai_accept_latency_median_ms": None} for _ in range(50)]
        rows += [{"ai_accept_latency_median_ms": 900.0} for _ in range(50)]
        fitted = calibrate_thresholds(rows, percentile=50.0)
        assert fitted["ai_accept_latency_ms"] == 900.0

    def test_defaults_are_all_present_for_every_rule_that_reads_one(self):
        for key in ("ai_accept_latency_ms", "min_accepts", "accept_edit_floor",
                    "shape_interval_ms", "min_shapes"):
            assert key in DEFAULT_THRESHOLDS


class TestHasSubstance:
    """
    Found in live use, not by a unit test: arming a tool is emitted on every
    page view (the manager selects a default tool at construction and clears it
    on teardown), so four page views produced four stored sessions containing a
    single `tool` event each.

    That is not just clutter. Session count is the denominator of the admin risk
    score, so a row per page view dilutes every flag rate toward zero.
    """

    def test_a_tool_only_stream_is_a_page_view_not_work(self):
        assert not has_substance([ev(0, "tool", meta={"tool": "bbox"})])

    def test_focus_and_blur_alone_are_not_work(self):
        assert not has_substance([ev(0, "focus"), ev(100, "blur")])

    def test_an_empty_stream_has_no_substance(self):
        assert not has_substance([])

    def test_drawing_is_work(self):
        assert has_substance([ev(0, "tool"), ev(10, "shape_add", "bbox", 4)])

    def test_inspecting_without_drawing_is_still_work(self):
        """"Spent two minutes examining this image and drew nothing" is a real
        observation; "the page loaded" is not."""
        assert has_substance([ev(0, "tool"), ev(10, "zoom", value=400)])
        assert has_substance([ev(0, "pan", value=120)])

    def test_a_rejected_suggestion_is_work(self):
        assert has_substance([ev(0, "ai_reject", meta={"sid": "a"})])

    def test_an_undo_is_work(self):
        assert has_substance([ev(0, "undo")])


class TestContentBlindness:
    def test_no_event_field_can_carry_a_coordinate(self):
        """The privacy claim is structural, so assert the structure."""
        fields = set(TelemetryEvent.__dataclass_fields__)
        assert fields == {"t_ms", "action", "shape", "value", "meta"}

    def test_packing_drops_nothing_but_also_adds_no_geometry(self):
        events = [ev(0, "shape_add", "polygon", 12)]
        restored = unpack_events(pack_events(events))
        assert restored[0].to_dict() == {
            "t_ms": 0, "action": "shape_add", "shape": "polygon", "value": 12,
        }
