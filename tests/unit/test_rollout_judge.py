"""
The VLM rollout judge: sampling, parsing, and alignment against humans.

The model call itself is not tested here — it needs ffmpeg, Pillow and a vision
endpoint. What is tested is everything around it, which is where a judge
quietly starts flattering itself:

* a failed call must be **excluded** from alignment, not counted as "no break";
* a tolerance finer than the sampling resolution must be **refused**, not
  reported as a disagreement about the model;
* a model that names a tile it cannot have seen must be an error, not a
  plausible-looking timestamp near the end of the clip.
"""

from __future__ import annotations

import pytest

from potato.ai import rollout_judge as J

TYPES = ["object_permanence", "interpenetration", "gravity_violation"]


def frames(times):
    return [(t, f"/tmp/tile_{i}.jpg") for i, t in enumerate(times)]


class TestSampling:
    def test_times_are_evenly_spread_and_avoid_both_edges(self):
        # The first frame is the conditioning frame, correct by construction;
        # the last is often a fade. Sampling them wastes two of twelve tiles.
        times = J.sample_times(6.0, tiles=12)
        assert len(times) == 12
        assert times[0] == pytest.approx(0.25)
        assert times[-1] == pytest.approx(5.75)
        gaps = {round(b - a, 6) for a, b in zip(times, times[1:])}
        assert len(gaps) == 1

    def test_a_zero_length_clip_yields_nothing_rather_than_dividing_by_zero(self):
        assert J.sample_times(0.0) == []
        assert J.sample_times(-1.0) == []

    def test_the_resolution_is_half_the_sampling_interval(self):
        # A break reported at tile N happened between the midpoints of tiles
        # N-1 and N, so the true instant is within half an interval.
        assert J.sheet_resolution(6.0, tiles=12) == pytest.approx(0.25)
        assert J.sheet_resolution(0.0) == 0.0


class TestParsing:
    def test_a_tile_becomes_the_timestamp_it_was_sampled_at(self):
        result = J.parse_verdict(
            {"break_tile": 3, "violation_type": "interpenetration",
             "confidence": 0.8, "rationale": "hand through mug"},
            frames([0.25, 0.75, 1.25, 1.75]), TYPES)
        assert result["t"] == 1.25
        assert result["violation_type"] == "interpenetration"
        assert result["confidence"] == 0.8

    def test_tile_zero_means_no_break_which_is_a_real_answer(self):
        # The prompt asks for it explicitly, because a model given only "which
        # frame is wrong" will always name one.
        result = J.parse_verdict(
            {"break_tile": 0, "confidence": 0.6, "rationale": "all coherent"},
            frames([0.25, 0.75]), TYPES)
        assert result["t"] is None
        assert "error" not in result

    def test_a_tile_off_the_sheet_is_an_error_not_a_clamp(self):
        # Clamping would silently place the break at the end of the clip, which
        # is a plausible-looking wrong answer.
        result = J.parse_verdict({"break_tile": 9}, frames([0.25, 0.75]), TYPES)
        assert "error" in result
        assert "9" in result["error"]

    def test_a_category_outside_the_taxonomy_is_recorded_but_not_adopted(self):
        result = J.parse_verdict(
            {"break_tile": 1, "violation_type": "vibes_are_off"},
            frames([0.25, 0.75]), TYPES)
        assert result["violation_type"] == ""
        assert result["unknown_type"] == "vibes_are_off"

    def test_a_category_is_matched_case_insensitively(self):
        result = J.parse_verdict(
            {"break_tile": 1, "violation_type": "  Interpenetration "},
            frames([0.25, 0.75]), TYPES)
        assert result["violation_type"] == "interpenetration"

    def test_fenced_json_from_an_open_model_is_parsed(self):
        raw = 'Sure!\n```json\n{"break_tile": 2, "confidence": 0.5}\n```\n'
        result = J.parse_verdict(raw, frames([0.25, 0.75, 1.25]), TYPES)
        assert result["t"] == 0.75

    def test_a_string_tile_is_coerced_rather_than_rejected(self):
        result = J.parse_verdict({"break_tile": "2"},
                                 frames([0.25, 0.75, 1.25]), TYPES)
        assert result["t"] == 0.75

    def test_unusable_output_is_an_error_with_a_reason(self):
        assert "error" in J.parse_verdict("no json at all", frames([0.25]), TYPES)
        assert "error" in J.parse_verdict({"break_tile": "soon"},
                                          frames([0.25]), TYPES)

    def test_confidence_is_clamped_into_range(self):
        result = J.parse_verdict({"break_tile": 1, "confidence": 7.0},
                                 frames([0.25, 0.75]), TYPES)
        assert result["confidence"] == 1.0


class TestAlignment:
    def _pred(self, stream, t, type_="interpenetration", error="",
              resolution=0.25):
        return J.BreakPrediction(
            instance_id="item1", schema_name="wm", stream_id=stream, t=t,
            violation_type=type_, resolution=resolution, error=error)

    def test_a_matching_break_counts_as_a_hit(self):
        report = J.align_with_humans(
            [self._pred("gen_a", 3.0)],
            {"item1::gen_a": {"t": 3.1, "type": "interpenetration"}},
            tolerance=0.5)
        assert report["detection"]["both_found"] == 1
        assert report["localization"]["within_tolerance"] == 1
        assert report["category"]["matched"] == 1

    def test_the_confusion_counts_cover_every_combination(self):
        preds = [self._pred("a", 3.0), self._pred("b", None),
                 self._pred("c", 2.0), self._pred("d", None)]
        human = {"item1::a": {"t": 3.1}, "item1::b": {"t": 4.0},
                 "item1::c": {"t": None}, "item1::d": {"t": None}}
        report = J.align_with_humans(preds, human, tolerance=0.5)
        assert report["detection"] == {
            "both_found": 1, "judge_only": 1, "human_only": 1,
            "neither_found": 1, "agreement_rate": 0.5}

    def test_an_errored_prediction_is_excluded_not_counted_as_no_break(self):
        # A model that timed out has said nothing about the rollout. Counting
        # that as agreement with an annotator who also found nothing is how an
        # automatic metric flatters itself.
        report = J.align_with_humans(
            [self._pred("a", None, error="timed out")],
            {"item1::a": {"t": None}}, tolerance=0.5)
        assert report["n_excluded_errors"] == 1
        assert report["n_compared"] == 0
        assert report["detection"]["neither_found"] == 0

    def test_a_tolerance_finer_than_the_sampling_is_refused(self):
        # A contact sheet cannot localise below half its sampling interval, and
        # a disagreement at that scale is an artifact, not a finding.
        report = J.align_with_humans(
            [self._pred("a", 3.0, resolution=0.25)],
            {"item1::a": {"t": 3.1}}, tolerance=0.04)
        assert "error" in report
        assert "resolution" in report["error"]

    def test_a_rollout_with_no_human_answer_is_skipped(self):
        report = J.align_with_humans(
            [self._pred("a", 3.0)], {"item1::other": {"t": 1.0}},
            tolerance=0.5)
        assert report["n_compared"] == 0

    def test_the_mean_offset_is_over_pairs_where_both_found_a_break(self):
        preds = [self._pred("a", 3.0), self._pred("b", 5.0),
                 self._pred("c", None)]
        human = {"item1::a": {"t": 3.2}, "item1::b": {"t": 6.0},
                 "item1::c": {"t": 9.0}}
        report = J.align_with_humans(preds, human, tolerance=0.5)
        # `c` is judge-said-nothing vs human-found-one: a detection
        # disagreement, not a localization pair.
        assert report["localization"]["n_pairs"] == 2
        assert report["localization"]["mean_offset"] == pytest.approx(0.6)
        # Both are pairs, but only `a` is close enough to be a hit.
        assert report["localization"]["within_tolerance"] == 1
        assert report["localization"]["hit_rate"] == pytest.approx(0.5)

    def test_categories_are_only_compared_on_hits(self):
        # Matching the category on a break the judge put two seconds away is
        # not evidence that it understood the same event.
        preds = [self._pred("a", 3.0, "interpenetration")]
        human = {"item1::a": {"t": 9.0, "type": "interpenetration"}}
        report = J.align_with_humans(preds, human, tolerance=0.5)
        assert report["category"]["n_compared"] == 0
        assert report["category"]["match_rate"] is None


class TestPredictionSerialization:
    def test_a_prediction_round_trips(self):
        prediction = J.BreakPrediction(
            instance_id="i", schema_name="s", stream_id="gen_a", t=3.4,
            violation_type="interpenetration", confidence=0.7,
            resolution=0.25, model_name="m", prompt_version="v1")
        restored = J.BreakPrediction.from_dict(prediction.to_dict())
        assert restored == prediction
