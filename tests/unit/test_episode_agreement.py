"""
Agreement over episode annotations, and the export conversion.

An episode annotation is three answers in one value, and the point of the
report is that they are scored *separately*: "they agree it failed but not when
the grasp started" and "they agree on the phases but not on whether it worked"
are different problems with different remedies, and one blended number hides
which you have.
"""

import json
import math

import pytest

from potato.server_utils import annotation_values
from potato.server_utils.iaa import episodes as episode_iaa
from potato.server_utils.iaa.dispatcher import SchemaKind, classify_schema

SCHEME = {"annotation_type": "episode_annotation", "name": "review"}


def stored(phases=None, reward=None, outcome=None):
    """The blob shape the timeline writes into the hidden input."""
    return {"_data": json.dumps({
        "phases": phases or [],
        "reward": reward or [],
        "outcome": outcome or {},
        "instructions": [],
    })}


# ---------------------------------------------------------------------------
# Reading the layers back out
# ---------------------------------------------------------------------------

class TestLayerExtraction:
    def test_phases_are_the_temporal_segmentation(self):
        value = stored(phases=[{"start": 0.0, "end": 1.5, "label": "reach"}])
        segments = annotation_values.temporal_segments(SCHEME, value)
        assert segments == [{"start": 0.0, "end": 1.5, "label": "reach"}]

    def test_the_reward_curve_is_not_read_as_segments(self):
        # Reading the whole blob as segments would silently score zero segments
        # for every episode -- the number would exist and mean nothing.
        value = stored(reward=[{"t": 0.0, "value": 0.2}])
        assert annotation_values.temporal_segments(SCHEME, value) == []

    def test_audio_and_video_segments_still_work(self):
        # The episode timeline writes start/end; audio and video write
        # start_time/end_time. Both spellings have to keep working.
        av = {"annotation_type": "video_annotation", "name": "v"}
        value = {"_data": json.dumps({"segments": [
            {"start_time": 1.0, "end_time": 2.0, "label": "x"}]})}
        assert annotation_values.temporal_segments(av, value) == [
            {"start": 1.0, "end": 2.0, "label": "x"}]

    def test_the_reward_curve_comes_back_sorted(self):
        value = stored(reward=[{"t": 2.0, "value": 1.0},
                               {"t": 0.0, "value": 0.0}])
        curve = annotation_values.reward_curve(SCHEME, value)
        assert [p["t"] for p in curve] == [0.0, 2.0]

    def test_an_unanswered_outcome_is_none_not_empty_string(self):
        # "not answered" and "answered as empty" must stay distinguishable: an
        # unanswered outcome is excluded from alpha rather than counted as a
        # category everyone agreed on.
        assert annotation_values.episode_outcome(SCHEME, stored()) is None
        assert annotation_values.episode_outcome(
            SCHEME, stored(outcome={"result": "failure"})) == "failure"

    def test_other_schemas_get_nothing_from_the_episode_readers(self):
        radio = {"annotation_type": "radio", "name": "r"}
        assert annotation_values.reward_curve(radio, stored()) == []
        assert annotation_values.episode_outcome(radio, stored()) is None

    def test_the_dispatcher_classifies_it_as_its_own_kind(self):
        assert classify_schema(SCHEME) == SchemaKind.EPISODE


# ---------------------------------------------------------------------------
# The reward curve
# ---------------------------------------------------------------------------

class TestRewardInterpolation:
    CURVE = [{"t": 0.0, "value": 0.0}, {"t": 2.0, "value": 1.0}]

    def test_interpolates_between_samples(self):
        assert episode_iaa.reward_at(self.CURVE, 1.0) == pytest.approx(0.5)

    def test_returns_nothing_outside_the_drawn_range(self):
        # "The annotator did not say" and "the annotator said zero" are
        # different. A reward model trained on the second when the first was
        # true learns that unlabelled regions are bad.
        assert episode_iaa.reward_at(self.CURVE, 5.0) is None
        assert episode_iaa.reward_at(self.CURVE, -1.0) is None

    def test_an_empty_curve_is_nothing_everywhere(self):
        assert episode_iaa.reward_at([], 1.0) is None

    def test_duplicate_timestamps_do_not_divide_by_zero(self):
        curve = [{"t": 1.0, "value": 0.2}, {"t": 1.0, "value": 0.8}]
        assert episode_iaa.reward_at(curve, 1.0) is not None

    def test_resampling_keeps_only_the_shared_range(self):
        # Comparing a region one annotator labelled against one they did not is
        # comparing a judgement to an absence.
        a = [{"t": 0.0, "value": 0.0}, {"t": 2.0, "value": 1.0}]
        b = [{"t": 1.0, "value": 0.5}, {"t": 4.0, "value": 1.0}]
        xs, ys = episode_iaa.resample_pair(a, b, duration=4.0, grid=41)
        assert len(xs) == len(ys)
        # Overlap is [1, 2] out of [0, 4]: about a quarter of the grid.
        assert 8 <= len(xs) <= 13


class TestRewardAgreement:
    def test_identical_curves_agree_perfectly(self):
        curve = [{"t": 0.0, "value": 0.0}, {"t": 4.0, "value": 1.0}]
        out = episode_iaa.reward_agreement({"a": curve, "b": list(curve)}, 4.0)
        assert out["reward_pearson_r"] == pytest.approx(1.0)
        assert out["reward_icc"] > 0.99
        assert out["reward_coverage"] == pytest.approx(1.0)

    def test_opposed_curves_disagree(self):
        rising = [{"t": 0.0, "value": 0.0}, {"t": 4.0, "value": 1.0}]
        falling = [{"t": 0.0, "value": 1.0}, {"t": 4.0, "value": 0.0}]
        out = episode_iaa.reward_agreement({"a": rising, "b": falling}, 4.0)
        assert out["reward_pearson_r"] == pytest.approx(-1.0)

    def test_partial_coverage_is_reported(self):
        # A high correlation over 5% of the timeline is not evidence about the
        # other 95%, and reporting it without the coverage invites that reading.
        a = [{"t": 0.0, "value": 0.0}, {"t": 4.0, "value": 1.0}]
        b = [{"t": 3.0, "value": 0.7}, {"t": 4.0, "value": 1.0}]
        out = episode_iaa.reward_agreement({"a": a, "b": b}, 4.0)
        assert out["reward_coverage"] < 0.35

    def test_one_curve_is_not_agreement(self):
        out = episode_iaa.reward_agreement({"a": [{"t": 0, "value": 0}]}, 4.0)
        assert out["n_annotators"] == 1
        assert "note" in out


class TestOutcomeAgreement:
    def test_full_agreement_with_variation_is_one(self):
        out = episode_iaa.outcome_agreement({
            "i1": {"a": "success", "b": "success"},
            "i2": {"a": "failure", "b": "failure"},
        })
        assert out["outcome_alpha"] == pytest.approx(1.0)

    def test_no_variation_is_undefined_with_a_reason(self):
        # Alpha divides by expected disagreement. A corpus where everyone said
        # the same thing everywhere has none, so alpha is genuinely undefined
        # -- and a bare NaN cannot be told from a broken computation.
        out = episode_iaa.outcome_agreement({
            "i1": {"a": "success", "b": "success"},
            "i2": {"a": "success", "b": "success"},
        })
        assert out["outcome_alpha"] is None
        assert "no variation" in out["outcome_alpha_note"]

    def test_unanswered_outcomes_are_dropped(self):
        # Counting "did not say" as a category manufactures agreement between
        # two people who both skipped the question.
        out = episode_iaa.outcome_agreement({
            "i1": {"a": "success", "b": None},
            "i2": {"a": "failure", "b": "failure"},
        })
        assert out["n_outcomes"] == 3

    def test_disagreement_scores_below_perfect(self):
        out = episode_iaa.outcome_agreement({
            "i1": {"a": "success", "b": "failure"},
            "i2": {"a": "failure", "b": "success"},
            "i3": {"a": "success", "b": "success"},
        })
        assert out["outcome_alpha"] < 0.5


class TestEpisodeReport:
    def _rows(self):
        a = stored(
            phases=[{"start": 0.0, "end": 2.0, "label": "reach"},
                    {"start": 2.0, "end": 4.0, "label": "grasp"}],
            reward=[{"t": 0.0, "value": 0.0}, {"t": 4.0, "value": 1.0}],
            outcome={"result": "success"})
        b = stored(
            phases=[{"start": 0.0, "end": 2.1, "label": "reach"},
                    {"start": 2.1, "end": 4.0, "label": "grasp"}],
            reward=[{"t": 0.0, "value": 0.05}, {"t": 4.0, "value": 0.95}],
            outcome={"result": "failure"})
        return {"ep0": {"alice": a, "bob": b}}

    def test_the_three_layers_are_reported_separately(self):
        report = episode_iaa.episode_report(self._rows(), SCHEME)
        assert set(report) >= {"n_items", "phases", "outcome", "reward"}

    def test_near_identical_phases_score_high(self):
        report = episode_iaa.episode_report(self._rows(), SCHEME)
        assert report["phases"]["mean_matched_iou"] > 0.9

    def test_disagreeing_outcomes_do_not_drag_the_phase_score(self):
        # The whole point of splitting: these annotators agree almost exactly
        # about WHEN and completely disagree about WHETHER.
        report = episode_iaa.episode_report(self._rows(), SCHEME)
        assert report["phases"]["mean_agreement"] > 0.8
        assert (report["outcome"]["outcome_alpha"] is None
                or report["outcome"]["outcome_alpha"] < 0.5)

    def test_reward_agreement_is_computed_without_a_supplied_duration(self):
        # The report runs from stored values alone; the manifest is on disk.
        report = episode_iaa.episode_report(self._rows(), SCHEME)
        assert report["reward"]["reward_pearson_r"] == pytest.approx(1.0)

    def test_an_empty_report_does_not_invent_numbers(self):
        report = episode_iaa.episode_report({}, SCHEME)
        assert report["n_items"] == 0
        assert "phases" not in report


# ---------------------------------------------------------------------------
# Export conversion
# ---------------------------------------------------------------------------

class TestExportConversion:
    def test_phases_become_one_label_per_frame(self):
        from potato.episodes.export import phases_to_frames
        phases = [{"start": 0.0, "end": 1.0, "label": "reach"},
                  {"start": 1.0, "end": 2.0, "label": "grasp"}]
        assert phases_to_frames(phases, 2.0, 4) == [
            "reach", "reach", "grasp", "grasp"]

    def test_boundaries_are_half_open(self):
        # A frame claimed by both neighbours is invisible in a plot and
        # produces a duplicated row in every join downstream.
        from potato.episodes.export import phases_to_frames
        phases = [{"start": 0.0, "end": 1.0, "label": "a"},
                  {"start": 1.0, "end": 2.0, "label": "b"}]
        out = phases_to_frames(phases, 1.0, 2)
        assert out == ["a", "b"]

    def test_an_unlabelled_stretch_stays_none(self):
        # Filling forward invents a label the annotator never gave.
        from potato.episodes.export import phases_to_frames
        phases = [{"start": 0.0, "end": 1.0, "label": "a"}]
        assert phases_to_frames(phases, 1.0, 4) == ["a", None, None, None]

    def test_the_frame_rate_actually_matters(self):
        # The failure this whole conversion exists to prevent: the same phase
        # at a different fps covers a different number of frames, and nothing
        # downstream can detect the mistake.
        from potato.episodes.export import phases_to_frames
        phases = [{"start": 0.0, "end": 1.0, "label": "a"}]
        assert phases_to_frames(phases, 10.0, 20).count("a") == 10
        assert phases_to_frames(phases, 20.0, 40).count("a") == 20

    def test_reward_is_resampled_per_frame(self):
        from potato.episodes.export import reward_to_frames
        curve = [{"t": 0.0, "value": 0.0}, {"t": 1.0, "value": 1.0}]
        out = reward_to_frames(curve, 2.0, 4)
        assert out[0] == pytest.approx(0.0)
        assert out[1] == pytest.approx(0.5)
        # Frame 2 is t = 1.0, the curve's last sample: inside the range.
        assert out[2] == pytest.approx(1.0)
        # Frame 3 is t = 1.5, past where the annotator drew.
        assert out[3] is None, "beyond the drawn range is not zero"

    def test_rows_carry_the_episode_level_fields(self):
        # Repeated on every row rather than living in a second file: a sidecar
        # that needs a join to be usable is one people rewrite themselves.
        from potato.episodes.export import annotation_rows
        rows = annotation_rows("ep0", {
            "phases": [{"start": 0.0, "end": 1.0, "label": "a"}],
            "reward": [],
            "outcome": {"result": "failure", "cause": "slipped"},
        }, 2.0, 2)
        assert len(rows) == 2
        assert all(r["outcome"] == "failure" for r in rows)
        assert all(r["failure_cause"] == "slipped" for r in rows)
        assert rows[1]["timestamp"] == pytest.approx(0.5)

    def test_every_frame_gets_a_row_even_when_unannotated(self):
        # A sidecar with holes forces every consumer to decide what a missing
        # frame means, and they will not all decide the same thing.
        from potato.episodes.export import annotation_rows
        rows = annotation_rows("ep0", {}, 1.0, 3)
        assert len(rows) == 3
        assert all(r["phase"] is None for r in rows)

    def test_writes_json_lines(self, tmp_path):
        from potato.episodes.export import annotation_rows, write_jsonl
        rows = annotation_rows("ep0", {"phases": []}, 1.0, 2)
        path = write_jsonl(rows, tmp_path / "out" / "a.jsonl")
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["episode_id"] == "ep0"
