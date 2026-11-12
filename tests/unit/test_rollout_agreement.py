"""
Agreement over rollout break-points.

The claim this module makes is "annotators agree on when the physics broke, to
within N frames". A statistic that cannot be wrong is not evidence, so every
test here is written so that it fails on the plausible alternative
implementation, not merely on a crash:

* detection must go NEGATIVE when annotators systematically disagree, not
  merely below some threshold;
* the tolerance sweep must actually move -- marks that match at 1 s and not at
  40 ms must show that difference;
* an annotator who never answered about a stream must be EXCLUDED, not counted
  as having found nothing, because those two readings give opposite answers.
"""

from __future__ import annotations

import json

import pytest

from potato.server_utils.iaa import rollouts as R

SCHEME = {"annotation_type": "rollout_evaluation", "name": "wm", "fps": 25}


def blob(violations=None, clean=None, winner="", verdict=""):
    """A stored value in the shape the client actually writes."""
    return {"_data": json.dumps({
        "violations": violations or [],
        "clean": clean or [],
        "preference": {"winner": winner, "confidence": "", "rubric": {}},
        "counterfactual": {"verdict": verdict, "t": None, "note": ""},
    })}


def mark(stream, t, type_="interpenetration", severity=2):
    return {"stream": stream, "t": t, "type": type_, "severity": severity,
            "note": ""}


class TestMatching:
    def test_two_marks_inside_the_window_are_one_break(self):
        matches, left, right = R.match_breakpoints(
            [mark("a", 2.0)], [mark("a", 2.2)], tolerance=0.5)
        assert len(matches) == 1
        assert not left and not right

    def test_two_marks_outside_the_window_are_two_breaks(self):
        matches, left, right = R.match_breakpoints(
            [mark("a", 2.0)], [mark("a", 3.0)], tolerance=0.5)
        assert not matches
        assert left == [0] and right == [0]

    def test_a_mark_exactly_one_tolerance_away_does_not_match(self):
        # The boundary case the window exists to exclude.
        matches, _, _ = R.match_breakpoints(
            [mark("a", 2.0)], [mark("a", 2.5)], tolerance=0.5)
        assert not matches

    def test_the_matcher_prefers_the_closer_of_two_candidates(self):
        # A step function would leave this to tie-breaking order; the linear
        # ramp makes it deterministic.
        matches, _, _ = R.match_breakpoints(
            [mark("a", 2.0)],
            [mark("a", 2.4), mark("a", 2.05)], tolerance=0.5)
        assert matches[0][1] == 1

    def test_similarity_falls_off_linearly_to_the_window(self):
        assert R.breakpoint_similarity(mark("a", 2.0), mark("a", 2.0), 1.0) == 1.0
        assert R.breakpoint_similarity(mark("a", 2.0), mark("a", 2.5), 1.0) == 0.5
        assert R.breakpoint_similarity(mark("a", 2.0), mark("a", 3.5), 1.0) == 0.0


class TestSplittingByStream:
    def test_marks_are_grouped_and_sorted(self):
        grouped = R.by_stream([mark("b", 3.0), mark("a", 2.0), mark("a", 1.0)])
        assert set(grouped) == {"a", "b"}
        assert [m["t"] for m in grouped["a"]] == [1.0, 2.0]

    def test_a_mark_with_no_usable_time_is_dropped(self):
        # A zero-time default would silently agree with every other malformed
        # mark at the origin.
        grouped = R.by_stream([{"stream": "a"}, {"stream": "a", "t": "nope"},
                               mark("a", 1.0)])
        assert len(grouped["a"]) == 1

    def test_answered_streams_are_the_union_of_marked_and_cleaned(self):
        assert R.answered_streams([mark("a", 1.0)], ["b"]) == {"a", "b"}
        assert R.answered_streams([], []) == set()


class TestDetection:
    def _rows(self, per_item):
        return {f"item{i}": row for i, row in enumerate(per_item)}

    def test_annotators_who_agree_everywhere_report_unanimity_not_a_number(self):
        # Alpha divides by expected disagreement, which is zero here. Reporting
        # 1.0 would be a fabrication and a bare NaN would be unreadable.
        rows = self._rows([
            {"a": blob([mark("gen_a", 1.0 + i)], ["real"]),
             "b": blob([mark("gen_a", 1.05 + i)], ["real"])}
            for i in range(4)
        ])
        report = R.rollout_report(rows, SCHEME)
        assert report["detection"]["alpha"] is None
        assert "no variation" in report["detection"]["note"]

    def test_systematic_disagreement_goes_NEGATIVE(self):
        # The discriminating case. One annotator finds a break on gen_a; the
        # other says gen_a is clean, every time. Anything that reported a
        # positive number here would be broken.
        rows = self._rows([
            {"a": blob([mark("gen_a", 1.0 + i)], []),
             "b": blob([], ["gen_a"])}
            for i in range(5)
        ])
        report = R.rollout_report(rows, SCHEME)
        assert report["detection"]["alpha"] < 0

    def test_an_annotator_who_never_answered_is_excluded_not_counted(self):
        # Carol answered about gen_b only. Counting her as "found no break on
        # gen_a" would manufacture agreement with whoever also found none.
        rows = {
            f"item{i}": {
                "alice": blob([mark("gen_a", 1.0 + i)], []),
                "bob": blob([mark("gen_a", 1.05 + i)], []),
                "carol": blob([], ["gen_b"]),
            } for i in range(3)
        }
        report = R.rollout_report(rows, SCHEME)
        # 2 annotators x 3 items, not 3 x 3.
        assert report["detection"]["n_judgements"] == 6

    def test_coverage_reports_how_much_of_the_task_was_answered(self):
        # Detection is computed only over answered streams, which silently
        # narrows the denominator; the coverage keeps that visible.
        rows = {
            f"item{i}": {
                "alice": blob([mark("gen_a", 1.0)], []),
                "bob": blob([], ["gen_b"]),
            } for i in range(3)
        }
        report = R.rollout_report(rows, SCHEME)
        assert report["coverage"]["answered_fraction"] == pytest.approx(0.5)


class TestLocalization:
    def test_the_mean_offset_is_reported_in_seconds_and_in_frames(self):
        rows = {
            f"item{i}": {"a": blob([mark("gen_a", 1.0 + i)], []),
                         "b": blob([mark("gen_a", 1.08 + i)], [])}
            for i in range(3)
        }
        report = R.rollout_report(rows, SCHEME)
        loc = report["localization"]
        assert loc["mean_offset"] == pytest.approx(0.08, abs=1e-6)
        # 0.08 s at 25 fps is exactly two frames -- the number a paper quotes.
        assert loc["mean_offset_frames"] == pytest.approx(2.0, abs=1e-6)

    def test_no_frame_rate_means_no_frame_number(self):
        rows = {
            f"item{i}": {"a": blob([mark("gen_a", 1.0 + i)], []),
                         "b": blob([mark("gen_a", 1.08 + i)], [])}
            for i in range(3)
        }
        report = R.rollout_report(
            rows, {"annotation_type": "rollout_evaluation", "name": "wm"})
        assert "mean_offset_frames" not in report["localization"]

    def test_close_annotators_score_higher_than_scattered_ones(self):
        def report_for(jitter):
            rows = {
                f"item{i}": {"a": blob([mark("gen_a", 1.0 + i * 3)], []),
                             "b": blob([mark("gen_a", 1.0 + i * 3 + jitter)], [])}
                for i in range(6)
            }
            return R.rollout_report(rows, SCHEME, tolerances=(2.0,),
                                    headline=2.0)["localization"]

        tight = report_for(0.04)
        loose = report_for(1.5)
        assert tight["sigma"] > loose["sigma"]
        assert tight["mean_offset"] < loose["mean_offset"]

    def test_sigma_is_undefined_rather_than_perfect_with_no_chance_pairs(self):
        # One item means there are no between-item pairs to form a baseline
        # against, so the chance correction is genuinely undefined.
        rows = {"only": {"a": blob([mark("gen_a", 1.0)], []),
                         "b": blob([mark("gen_a", 1.05)], [])}}
        loc = R.rollout_report(rows, SCHEME)["localization"]
        assert loc["sigma"] != loc["sigma"]  # NaN


class TestTheToleranceSweep:
    def test_the_sweep_actually_moves_with_the_tolerance(self):
        # The reason the report is a sweep rather than one number. These marks
        # are 0.4 s apart: the same break at a 1 s window, two separate breaks
        # at a 40 ms one.
        rows = {
            f"item{i}": {"a": blob([mark("gen_a", 1.0 + i * 5)], []),
                         "b": blob([mark("gen_a", 1.4 + i * 5)], [])}
            for i in range(4)
        }
        report = R.rollout_report(rows, SCHEME)
        by_tol = {row["tolerance"]: row for row in report["sweep"]}
        assert by_tol[0.04]["localization"]["n_matched_pairs"] == 0
        assert by_tol[1.0]["localization"]["n_matched_pairs"] == 4
        # And the detection units differ: unmatched marks are separate breaks.
        assert (by_tol[0.04]["detection"]["n_units"]
                > by_tol[1.0]["detection"]["n_units"])

    def test_a_wider_window_never_matches_fewer_pairs(self):
        # The sweep is only readable as a curve if it is monotone. A matcher
        # that lost pairs as the window grew -- reachable by a greedy pass that
        # re-orders its candidates -- would produce a curve that looks like a
        # finding about the annotators and is really a bug.
        rows = {}
        for i in range(8):
            rows[f"i{i}"] = {
                "a": blob([mark("g", 1.0 + i * 5)]),
                "b": blob([mark("g", 1.0 + i * 5 + 0.1 * i)]),
            }
        sweep = R.rollout_report(rows, SCHEME)["sweep"]
        counts = [row["localization"]["n_matched_pairs"] for row in sweep]
        assert counts == sorted(counts)
        # And it must actually move, or the sweep is telling us nothing.
        assert counts[0] < counts[-1]

    def test_the_headline_tolerance_is_present_in_the_sweep(self):
        rows = {"i": {"a": blob([mark("gen_a", 1.0)], []),
                      "b": blob([mark("gen_a", 1.05)], [])},
                "j": {"a": blob([mark("gen_a", 4.0)], []),
                      "b": blob([mark("gen_a", 4.05)], [])}}
        report = R.rollout_report(rows, SCHEME, tolerances=(0.25,),
                                  headline=0.75)
        assert 0.75 in [row["tolerance"] for row in report["sweep"]]
        assert report["headline_tolerance"] == 0.75

    def test_the_sweep_carries_the_tolerance_in_frames_too(self):
        rows = {"i": {"a": blob([mark("gen_a", 1.0)], []),
                      "b": blob([mark("gen_a", 1.05)], [])},
                "j": {"a": blob([mark("gen_a", 4.0)], []),
                      "b": blob([mark("gen_a", 4.05)], [])}}
        report = R.rollout_report(rows, SCHEME, tolerances=(0.4,), headline=0.4)
        assert report["sweep"][0]["tolerance_frames"] == pytest.approx(10.0)


class TestCategoryAndSeverity:
    def test_categories_are_compared_only_on_matched_breaks(self):
        # Mixing in marks only one annotator made would conflate "we disagree
        # what broke" with "one of us missed it".
        rows = {
            f"item{i}": {
                "a": blob([mark("gen_a", 1.0 + i, "interpenetration"),
                           mark("gen_b", 9.0 + i, "gravity_violation")], []),
                "b": blob([mark("gen_a", 1.05 + i, "gravity_violation")], []),
            } for i in range(4)
        }
        report = R.rollout_report(rows, SCHEME)
        # Only the gen_a cluster is matched: 4 units, 8 judgements.
        assert report["category"]["n_units"] == 4
        assert report["category"]["n_judgements"] == 8

    def test_severity_is_scored_ordinally(self):
        # The distance from "subtle" to "breaks the scene" is genuinely larger
        # than between adjacent grades; nominal alpha throws that away.
        def alpha_for(second_severity):
            rows = {
                f"item{i}": {
                    "a": blob([mark("gen_a", 1.0 + i * 4, severity=1)], []),
                    "b": blob([mark("gen_a", 1.05 + i * 4,
                                    severity=second_severity)], []),
                } for i in range(5)
            }
            rows["extra"] = {
                "a": blob([mark("gen_a", 40.0, severity=3)], []),
                "b": blob([mark("gen_a", 40.05, severity=3)], []),
            }
            return R.rollout_report(rows, SCHEME)["severity"]["alpha"]

        assert alpha_for(2) > alpha_for(3)


class TestPerItemAnswers:
    def test_preference_agreement_is_nominal_alpha_over_the_winner(self):
        rows = {
            f"item{i}": {"a": blob(clean=["real", "gen_a", "gen_b"],
                                   winner="gen_a"),
                         "b": blob(clean=["real", "gen_a", "gen_b"],
                                   winner="gen_b")}
            for i in range(5)
        }
        report = R.rollout_report(rows, SCHEME)
        assert report["preference"]["alpha"] < 0

    def test_an_unanswered_preference_is_dropped_not_counted_as_a_category(self):
        # "did not say" is not a value two annotators can agree on.
        rows = {
            f"item{i}": {"a": blob(clean=["real"], winner="gen_a"),
                         "b": blob(clean=["real"], winner="")}
            for i in range(4)
        }
        report = R.rollout_report(rows, SCHEME)
        assert report["preference"]["n_judgements"] == 4

    def test_counterfactual_verdicts_are_scored(self):
        rows = {
            f"item{i}": {"a": blob(clean=["real"], verdict="plausible"),
                         "b": blob(clean=["real"],
                                   verdict="plausible" if i % 2 else "implausible")}
            for i in range(6)
        }
        report = R.rollout_report(rows, SCHEME)
        assert report["counterfactual"]["n_judgements"] == 12


class TestDegenerateInput:
    def test_an_item_with_one_annotator_is_excluded_and_counted(self):
        rows = {"lonely": {"a": blob([mark("gen_a", 1.0)], [])}}
        report = R.rollout_report(rows, SCHEME)
        assert report["n_items"] == 0
        assert report["n_items_skipped"] == 1
        assert "undefined" in report["note"]

    def test_a_value_that_is_not_a_rollout_blob_is_skipped(self):
        rows = {"i": {"a": {"_data": "not json"},
                      "b": blob([mark("gen_a", 1.0)], [])}}
        report = R.rollout_report(rows, SCHEME)
        assert report["n_items"] == 0

    def test_the_report_survives_annotators_who_marked_nothing_at_all(self):
        rows = {f"i{n}": {"a": blob(), "b": blob()} for n in range(3)}
        report = R.rollout_report(rows, SCHEME)
        assert report["n_items"] == 3
        assert report["detection"]["alpha"] is None
