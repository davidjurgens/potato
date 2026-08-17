"""
Inter-annotator agreement over a `grounding_eval` schema.

The traps this pins, in the order they would bite:

1. `grounding_eval` was absent from the dispatcher's type table, so it fell
   through to UNSUPPORTED and no grounding project ever got an agreement number.
2. IoU between two POINTS is always 0 — a point has no area — so scoring a
   `region_type: point` schema with the region measure reports total
   disagreement on data where the annotators agreed exactly.
3. An expression nobody answered must be excluded, not counted as a
   disagreement, or the score improves when you delete the hard expressions.
4. Metric names must classify onto the right presentation scale, or the admin
   page bands a distance as if it were an agreement coefficient.
"""

import json
import math

import pytest

from potato.server_utils.iaa import grounding as g
from potato.server_utils.iaa.dispatcher import (SchemaKind, classify_schema,
                                                metrics_for_schema)
from potato.server_utils.iaa.presentation import BANDABLE, metric_scale


def box(x, y, w, h, label="thing"):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def point(x, y, label="thing"):
    return {"type": "landmark", "label": label, "coordinates": {"x": x, "y": y}}


def blob(regions=None, absent=()):
    return json.dumps({"regions": regions or {}, "absent": list(absent),
                       "verdicts": {}, "region_type": "box"})


class TestParsing:
    def test_parses_regions_and_absences(self):
        answers = g.parse_answers(blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}, ["e2"]))
        assert answers["e1"]["absent"] is False
        assert len(answers["e1"]["regions"]) == 1
        assert answers["e2"]["absent"] is True
        assert answers["e2"]["regions"] == []

    def test_explicit_absence_overrides_a_stale_region_list(self):
        """
        The client clears regions when the annotator presses "not present".
        If a stale list survives, trusting it resurrects a retracted answer.
        """
        answers = g.parse_answers(
            json.dumps({"regions": {"e1": [box(0.1, 0.1, 0.2, 0.2)]},
                        "absent": ["e1"]}))
        assert answers["e1"]["absent"] is True
        assert answers["e1"]["regions"] == []

    def test_a_non_grounding_blob_is_none_not_empty(self):
        """
        None means "this is not grounding data"; {} would mean "an annotator
        answered nothing", and a misconfigured schema must not look like the
        latter.
        """
        assert g.parse_answers(json.dumps({"captions": []})) is None
        assert g.parse_answers("not json at all") is None
        assert g.parse_answers(blob({"e1": [box(0, 0, 1, 1)]})) is not None

    def test_items_with_one_annotator_are_dropped(self):
        rows = {"i1": {"u1": blob({"e1": [box(0, 0, 0.5, 0.5)]})}}
        assert g.parse_rows(rows) == {}


class TestSetSimilarity:
    def test_one_region_each_is_plain_iou(self):
        identical = g.set_similarity([box(0.1, 0.1, 0.2, 0.2)],
                                     [box(0.1, 0.1, 0.2, 0.2)])
        assert identical == pytest.approx(1.0, abs=1e-6)

        disjoint = g.set_similarity([box(0.0, 0.0, 0.1, 0.1)],
                                    [box(0.8, 0.8, 0.1, 0.1)])
        assert disjoint == pytest.approx(0.0, abs=1e-6)

    def test_an_unmatched_region_costs_something(self):
        """
        Dividing by the number of MATCHES would score "I found one of your two"
        as perfect agreement about that one — true, and useless.
        """
        score = g.set_similarity(
            [box(0.1, 0.1, 0.2, 0.2)],
            [box(0.1, 0.1, 0.2, 0.2), box(0.6, 0.6, 0.2, 0.2)])
        assert score == pytest.approx(0.5, abs=1e-6)

    def test_empty_side_is_none_not_zero(self):
        assert g.set_similarity([], [box(0, 0, 1, 1)]) is None


class TestPointsAreNotScoredWithIou:
    def test_the_region_measure_calls_opposite_corners_strong_agreement(self):
        """
        The trap, measured rather than assumed.

        A point has no area, so `region_similarity` cannot use overlap and falls
        back to a distance-derived score. That score is compressed into the top
        of the range: two annotators pointing at OPPOSITE CORNERS of the image —
        the most complete disagreement available — still score ~0.86, which the
        admin page bands "strong agreement" in green.

        This is a confidently wrong number rather than a missing one, which is
        why pointing gets its own measure instead of reusing this one.
        """
        from potato.grounding.metrics import region_similarity
        from potato.server_utils.iaa.presentation import band_for

        worst_possible = region_similarity(point(0.0, 0.0), point(1.0, 1.0))
        assert worst_possible > 0.8
        assert band_for("localization.mean_iou", worst_possible) == "strong"

    def test_pointing_is_reported_as_distance_not_overlap(self):
        report = g.grounding_report(
            {"i1": {"u1": blob({"e1": [point(0.5, 0.5)]}),
                    "u2": blob({"e1": [point(0.5, 0.5)]})}},
            {"region_type": "point"})

        assert "pointing" in report
        assert report["pointing"]["mean_pairwise_distance"] == pytest.approx(0.0)
        # And it must NOT have been counted as a localization failure.
        assert report["localization"]["n_pairs_compared"] == 0

    def test_distance_grows_with_disagreement(self):
        near = g.grounding_report(
            {"i1": {"u1": blob({"e1": [point(0.50, 0.50)]}),
                    "u2": blob({"e1": [point(0.52, 0.50)]})}},
            {"region_type": "point"})
        far = g.grounding_report(
            {"i1": {"u1": blob({"e1": [point(0.1, 0.1)]}),
                    "u2": blob({"e1": [point(0.9, 0.9)]})}},
            {"region_type": "point"})
        assert (near["pointing"]["mean_pairwise_distance"]
                < far["pointing"]["mean_pairwise_distance"])


class TestDetection:
    def test_agreeing_on_present_and_absent_scores_perfectly(self):
        report = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}, ["e2"]),
            "u2": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}, ["e2"]),
        }})
        assert report["detection"]["percent_agreement"] == pytest.approx(1.0)
        assert report["detection"]["alpha"] == pytest.approx(1.0)

    def test_one_says_present_the_other_absent(self):
        report = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}),
            "u2": blob({}, ["e1"]),
        }})
        assert report["detection"]["percent_agreement"] == pytest.approx(0.0)
        # No localization pair: one annotator says there is nothing to locate,
        # and counting it as an IoU of 0 as well would penalise it twice.
        assert report["localization"]["n_pairs_compared"] == 0

    def test_alpha_is_undefined_and_says_so_when_every_answer_matches(self):
        """
        A corpus where every expression is present is normal, and alpha is
        genuinely undefined there. A bare NaN reads as a bug; the note says
        which degenerate case it is.
        """
        report = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}),
            "u2": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}),
        }})
        assert math.isnan(report["detection"]["alpha"])
        assert "undefined" in report["detection"]["note"]
        # ...while the raw agreement is still reported and still 1.0.
        assert report["detection"]["percent_agreement"] == pytest.approx(1.0)


class TestCoverage:
    def test_an_unanswered_expression_is_excluded_not_counted_against(self):
        both_answered = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}),
            "u2": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}),
        }})
        one_skipped = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)],
                        "e2": [box(0.4, 0.4, 0.2, 0.2)]}),
            "u2": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}),
        }})
        # The skipped expression must not move the localization score...
        assert (one_skipped["localization"]["mean_iou"]
                == pytest.approx(both_answered["localization"]["mean_iou"]))
        # ...but it must show up as reduced coverage, so it is not invisible.
        assert one_skipped["coverage"]["n_unanswered_excluded"] == 1
        assert one_skipped["coverage"]["answered_fraction"] < 1.0


class TestSweep:
    def test_agreement_falls_as_the_threshold_tightens(self):
        report = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.10, 0.10, 0.20, 0.20)]}),
            "u2": blob({"e1": [box(0.13, 0.13, 0.20, 0.20)]}),
        }})
        by_threshold = {row["iou_threshold"]: row["localization"]["agreement"]
                        for row in report["sweep"]}
        assert by_threshold[0.25] >= by_threshold[0.9]
        assert report["sweep_parameter"] == "iou_threshold"

    def test_headline_threshold_is_a_row_in_the_sweep(self):
        report = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}),
            "u2": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}),
        }})
        thresholds = [row["iou_threshold"] for row in report["sweep"]]
        assert report["headline_iou_threshold"] in thresholds


class TestDispatcherWiring:
    def test_grounding_eval_is_classified_not_unsupported(self):
        """The whole reason no grounding project had an agreement number."""
        scheme = {"annotation_type": "grounding_eval", "name": "grounding"}
        assert classify_schema(scheme) == SchemaKind.GROUNDING

    def test_declared_metrics_are_the_names_the_report_produces(self):
        """
        metrics_for_schema drives the admin table's column set. A declared name
        the report never emits renders as a permanent "n/a"; an emitted name
        that is not declared is invisible.
        """
        report = g.grounding_report({"i1": {
            "u1": blob({"e1": [point(0.5, 0.5)]}),
            "u2": blob({"e1": [point(0.4, 0.5)]}),
        }}, {"region_type": "point"})

        produced = {f"{group}.{leaf}"
                    for group, values in report.items()
                    if isinstance(values, dict)
                    for leaf in values}
        declared = set(metrics_for_schema(
            {"annotation_type": "grounding_eval", "name": "g"}))
        assert declared <= produced, (
            f"declared but never produced: {sorted(declared - produced)}")


class TestPresentationScales:
    """A metric banded on the wrong scale is a false claim, not a missing hint."""

    @pytest.mark.parametrize("name,expected", [
        ("detection.alpha", "kappa"),
        ("detection.percent_agreement", "raw"),
        ("localization.mean_iou", "raw"),
        ("localization.median_iou", "raw"),
        ("coverage.answered_fraction", "coverage"),
        ("localization.n_pairs_compared", "count"),
        ("iou_threshold", "count"),
        ("headline_iou_threshold", "count"),
    ])
    def test_scale(self, name, expected):
        assert metric_scale(name) == expected

    @pytest.mark.parametrize("name", ["pointing.mean_pairwise_distance",
                                      "pointing.median_pairwise_distance"])
    def test_point_distances_are_never_banded_as_agreement(self, name):
        """
        0 is a PERFECT score for a distance and a terrible one for a
        coefficient. Banding it green at 0.6 would invert the reading.
        """
        assert metric_scale(name) == "lower"
        assert metric_scale(name) not in BANDABLE

    def test_every_produced_metric_name_has_a_known_scale(self):
        """
        An unrecognised name falls back to "unknown", which is safe but means
        the page shows no interpretive hint at all. This catches a metric that
        was added to the report and not to the scale table.
        """
        report = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}, ["e2"]),
            "u2": blob({"e1": [box(0.2, 0.2, 0.2, 0.2)]}),
        }})
        unknown = []
        for group, values in report.items():
            if group in ("sweep", "sweep_parameter", "sweep_parameter_label"):
                continue
            if isinstance(values, dict):
                for leaf, value in values.items():
                    if leaf == "note" or not isinstance(value, (int, float)):
                        continue
                    if metric_scale(f"{group}.{leaf}") == "unknown":
                        unknown.append(f"{group}.{leaf}")
            elif isinstance(values, (int, float)):
                if metric_scale(group) == "unknown":
                    unknown.append(group)
        assert not unknown, (
            f"no presentation scale for: {unknown} — add them to the tables in "
            f"potato/server_utils/iaa/presentation.py")


class TestRendersOnTheAdminPage:
    def test_the_report_flattens_into_rows_without_blowing_up(self):
        from potato.server_utils.iaa.presentation import flatten, sweep_table

        report = g.grounding_report({"i1": {
            "u1": blob({"e1": [box(0.1, 0.1, 0.2, 0.2)]}, ["e2"]),
            "u2": blob({"e1": [box(0.15, 0.15, 0.2, 0.2)]}, ["e2"]),
        }})
        rows = flatten(report)
        assert rows, "the grounding report produced no display rows"
        names = {row["name"] for row in rows}
        assert "detection.alpha" in names
        assert "localization.mean_iou" in names
        # No row prints the raw "nan" string at the reader.
        assert not any("nan" in str(row["display"]).lower() for row in rows)

        table = sweep_table(report)
        assert table is not None, "the IoU sweep did not render as a table"
