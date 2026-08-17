"""
The presentation layer between an agreement report and the admin table.

Two of these tests exist because of a live defect: `/admin/iaa?format=html`
rendered every metric of a rollout or episode report as "n/a" (they are nested,
and the template formatted only top-level numbers), while `n_items_skipped: 0`
rendered as **"weak agreement"** in red (the banding rule was `value < 0.2`,
applied to whatever happened to be a number). Both are pinned below.
"""

import json

import pytest

from potato.server_utils.iaa import presentation as P


class TestMetricScale:
    """Classification is by name, because a value cannot tell you its scale."""

    @pytest.mark.parametrize("name,scale", [
        ("alpha", "kappa"),
        ("detection.alpha", "kappa"),          # the leaf decides, not the group
        ("cohens_kappa", "kappa"),
        ("token_level_kappa", "span"),
        ("gamma_mathet", "kappa"),
        ("localization.sigma", "kappa"),
        ("localization.ks", "distribution"),
        ("pearson_r", "correlation"),
        ("reward.reward_icc", "correlation"),
        ("phases.mean_agreement", "raw"),
        ("phases.detection_f1", "raw"),
        ("mae", "lower"),
        ("localization.mean_offset", "lower"),
        # A metric quoted in frames is the same metric in other units.
        ("localization.mean_offset_frames", "lower"),
        ("localization.median_offset_frames", "lower"),
        ("coverage.answered_fraction", "coverage"),
        ("reward.reward_coverage", "coverage"),
        ("n_items", "count"),
        ("detection.n_judgements", "count"),
        ("headline_tolerance", "count"),
        ("fps", "count"),
    ])
    def test_scale(self, name, scale):
        assert P.metric_scale(name) == scale

    def test_every_scale_that_can_appear_has_a_note(self):
        """A metric on an unexplained scale is a number with no units."""
        for scale in P.SCALES:
            if scale in ("count", "unknown"):
                continue  # neither has a scale to explain
            assert scale in P.SCALE_NOTES

    def test_every_declared_metric_is_classified(self):
        """
        Drift guard. `metrics_for_schema` is the dispatcher's declaration of
        what each schema kind reports; a name in it that lands on "unknown"
        renders unbanded and unexplained, which is safe but is also a metric
        nobody taught the page to read.
        """
        from potato.server_utils.iaa.dispatcher import metrics_for_schema

        unknown = []
        for annotation_type in ("radio", "likert", "slider", "multiselect",
                                "span", "ranking", "image_annotation",
                                "video_annotation", "episode_annotation",
                                "rollout_evaluation"):
            for name in metrics_for_schema({"annotation_type": annotation_type,
                                            "name": "x"}):
                if P.metric_scale(name) == "unknown":
                    unknown.append((annotation_type, name))
        assert not unknown, f"unclassified metrics: {unknown}"

    def test_every_scale_note_is_localizable(self):
        """
        The note text lives in the i18n catalogs, not in this module. A scale
        the template cannot look up renders as nothing at all.
        """
        from potato.server_utils.i18n import UI_LANG_DEFAULTS

        for scale in P.SCALE_NOTES:
            assert f"iaa_scale_{scale}_label" in UI_LANG_DEFAULTS, scale


class TestBanding:
    def test_counts_are_never_banded(self):
        """The original defect: `n_items_skipped: 0` labelled weak agreement."""
        assert P.band_for("n_items_skipped", 0) == ""
        assert P.band_for("n_items", 0) == ""
        assert P.band_for("localization.n_matched_pairs", 0) == ""

    def test_the_defect_would_be_caught_by_the_generic_rule(self):
        """
        Proof the test above is load-bearing: the rule it replaced *would*
        have banded that value, so this is not a test that cannot fail.
        """
        naive = "weak" if 0 < 0.2 else ""
        assert naive == "weak"
        assert P.band_for("n_items_skipped", 0) != naive

    def test_lower_is_better_metrics_are_never_banded(self):
        """Banding them would invert the colours: a 0.1 s offset is excellent."""
        assert P.band_for("localization.mean_offset", 0.1) == ""
        assert P.band_for("mae", 0.05) == ""

    def test_coverage_is_not_agreement(self):
        """Full coverage means everyone answered, not that they agreed."""
        assert P.band_for("coverage.answered_fraction", 1.0) == ""

    def test_agreement_metrics_are_banded(self):
        assert P.band_for("detection.alpha", 0.81) == "strong"
        assert P.band_for("detection.alpha", 0.05) == "weak"
        assert P.band_for("detection.alpha", 0.45) == ""

    def test_nan_is_not_banded(self):
        assert P.band_for("alpha", float("nan")) == ""

    def test_an_unrecognised_metric_is_not_banded(self):
        """
        The fallback used to be a bandable scale, so any name this module did
        not know became "strong agreement" at 0.6 on no evidence but being a
        number. That is how `median_offset_frames: 5.0` — a five-frame
        disagreement — came to render green.
        """
        assert P.metric_scale("some_future_measure") == "unknown"
        assert P.band_for("some_future_measure", 0.9) == ""
        assert P.band_for("some_future_measure", 5.0) == ""


class TestFlatten:
    def test_nested_groups_become_dotted_rows(self):
        rows = P.flatten({"n_items": 3,
                          "detection": {"alpha": 0.7, "n_units": 4}})
        by_name = {r["name"]: r for r in rows}
        assert by_name["detection.alpha"]["value"] == 0.7

    def test_a_groups_counts_become_a_caption_on_its_measures(self):
        """
        Not dropped — an alpha over 4 judgements and one over 400 are
        different claims — but not competing rows either.
        """
        rows = P.flatten({"detection": {"alpha": 0.7, "n_units": 4,
                                        "n_judgements": 12}})
        assert [r["name"] for r in rows] == ["detection.alpha"]
        assert rows[0]["context"] == "4 units, 12 judgements"

    def test_a_group_of_only_counts_keeps_them_as_rows(self):
        """There is nothing for them to be a caption on."""
        rows = P.flatten({"tallies": {"n_items": 4, "n_annotators": 2}})
        assert {r["name"] for r in rows} == {"tallies.n_items",
                                             "tallies.n_annotators"}

    def test_a_nested_report_renders_no_values_without_flattening(self):
        """
        The defect, stated directly: with the template's old rule, a rollout
        report had exactly one displayable metric per top-level key and every
        group was unprintable.
        """
        metrics = {"n_items": 3, "detection": {"alpha": 0.7},
                   "localization": {"sigma": 0.6}}
        printable_before = [k for k, v in metrics.items()
                            if isinstance(v, (int, float))]
        assert printable_before == ["n_items"]
        printable_after = [r["name"] for r in P.flatten(metrics)
                           if r["value"] is not None]
        assert "detection.alpha" in printable_after
        assert "localization.sigma" in printable_after

    def test_a_groups_note_attaches_to_its_undefined_value(self):
        """
        `alpha: None` plus "everyone agreed" must not print as "n/a": the note
        says the opposite of what "n/a" implies.
        """
        rows = P.flatten({"detection": {
            "alpha": None, "n_units": 3,
            "note": "every annotator marked the same breaks"}})
        alpha = next(r for r in rows if r["name"] == "detection.alpha")
        assert alpha["note"] == "every annotator marked the same breaks"
        assert alpha["display"] == ""      # not "n/a"
        assert alpha["context"] == "3 units"

    def test_counts_render_as_integers_and_parameters_keep_their_decimals(self):
        rows = {r["name"]: r["display"] for r in P.flatten(
            {"n_units": 3, "n_chance_pairs": 2000,
             "headline_tolerance": 0.5, "fps": 29.97, "alpha": 0.5})}
        assert rows["n_units"] == "3"
        assert rows["n_chance_pairs"] == "2,000"
        assert rows["headline_tolerance"] == "0.5"   # not "0"
        assert rows["fps"] == "29.97"                # not "30"
        assert rows["alpha"] == "0.500"

    def test_sweep_keys_are_not_emitted_as_rows(self):
        names = [r["name"] for r in P.flatten(
            {"sweep": [{"tolerance": 1.0}], "sweep_parameter": "tolerance",
             "sweep_parameter_label": "window (s)", "n_items": 2})]
        assert names == ["n_items"]

    def test_a_top_level_note_survives_as_its_own_row(self):
        rows = P.flatten({"n_items": 0, "note": "no item has two annotators"})
        note = next(r for r in rows if r["name"] == "note")
        assert note["note"] == "no item has two annotators"


class TestSweepTable:
    def _metrics(self):
        return {
            "headline_tolerance": 0.5,
            "sweep_parameter": "tolerance",
            "sweep_parameter_label": "matching window (s)",
            "sweep": [
                {"tolerance": 0.04, "detection": {"alpha": -0.8},
                 "localization": {"sigma": 0.1}},
                {"tolerance": 0.5, "detection": {"alpha": 0.7},
                 "localization": {"sigma": 0.6}},
                {"tolerance": 2.0,
                 "detection": {"alpha": None, "note": "everyone agreed"},
                 "localization": {"sigma": 0.9}},
            ],
        }

    def test_columns_and_rows(self):
        table = P.sweep_table(self._metrics())
        assert table["columns"] == ["detection.alpha", "localization.sigma"]
        assert [r["parameter"] for r in table["rows"]] == [0.04, 0.5, 2.0]

    def test_the_headline_row_is_marked_not_extracted(self):
        """The curve either side of the headline is the point of the sweep."""
        table = P.sweep_table(self._metrics())
        assert [r["is_headline"] for r in table["rows"]] == [False, True, False]

    def test_declared_columns_pin_the_order(self):
        table = P.sweep_table(self._metrics(),
                              ["localization.sigma", "detection.alpha"])
        assert table["columns"] == ["localization.sigma", "detection.alpha"]

    def test_columns_absent_from_the_sweep_are_dropped(self):
        table = P.sweep_table(self._metrics(),
                              ["detection.alpha", "preference.alpha"])
        assert table["columns"] == ["detection.alpha"]

    def test_undefined_cells_carry_a_numbered_footnote(self):
        """A blank cell in a sweep needs its reason as much as one in a list."""
        table = P.sweep_table(self._metrics())
        last = table["rows"][-1]["cells"][0]
        assert last["display"] == "—"
        assert last["footnote"] == 1
        assert table["footnotes"] == ["everyone agreed"]

    def test_no_sweep_returns_none(self):
        assert P.sweep_table({"n_items": 2}) is None
        assert P.sweep_table({"sweep": []}) is None
        assert P.sweep_table({"sweep": ["not a row"]}) is None

    def test_a_sweep_without_its_parameter_is_refused(self):
        """Better no table than a table whose first column is invented."""
        assert P.sweep_table({"sweep": [{"detection": {"alpha": 1}}],
                              "sweep_parameter": "tolerance"}) is None


class TestPresentAgainstARealRolloutReport:
    """End to end on the report the dispatcher actually produces."""

    @pytest.fixture(scope="class")
    def presented(self):
        from potato.server_utils.iaa import rollouts

        def value(t, severity):
            return json.dumps({
                "violations": [{"stream_id": "gen_a", "t": t,
                                "type": "gravity_violation",
                                "severity": severity}],
                "clean": ["gen_b"],
                "preference": {"winner": "gen_b"},
                "counterfactual": {"verdict": "plausible"},
            })

        rows = {f"item{i}": {"a": value(base, "major"),
                             "b": value(base + 0.2, "minor")}
                for i, base in enumerate([2.0, 2.6, 3.0])}
        metrics = rollouts.rollout_report(
            rows, {"name": "r", "annotation_type": "rollout_evaluation"})
        report = {"n_overlap_items": 3, "items": {},
                  "schemas": {"r": {"kind": "rollout",
                                    "annotation_type": "rollout_evaluation",
                                    "metrics": metrics}}}
        return P.present(report)["schemas"]["r"]

    def test_the_agreement_numbers_are_displayable(self, presented):
        shown = {r["name"]: r["display"] for r in presented["rows"]
                 if r["display"]}
        assert shown["localization.sigma"].startswith("0.")
        assert shown["localization.mean_offset"] == "0.200"
        assert shown["severity.alpha"].startswith("-0.")

    def test_no_count_is_banded(self, presented):
        for row in presented["rows"]:
            if row["scale"] == "count":
                assert row["band"] == "", row["name"]

    def test_nothing_lower_is_better_is_banded(self, presented):
        """Including the frame-denominated twins of the second-denominated."""
        for row in presented["rows"]:
            if row["scale"] in ("lower", "unknown", "coverage",
                                "distribution"):
                assert row["band"] == "", row["name"]

    def test_the_denominators_appear_once_per_group(self, presented):
        """Six consecutive identical captions read as six different facts."""
        localization = [r for r in presented["rows"]
                        if r["name"].startswith("localization.")]
        assert len(localization) > 1
        assert localization[0]["context"]
        assert all(not r["context"] for r in localization[1:])

    def test_the_sweep_is_a_table_not_rows(self, presented):
        assert presented["sweep"] is not None
        assert presented["sweep"]["parameter_label"] == "matching window (s)"
        assert len(presented["sweep"]["rows"]) >= 5
        assert not any(r["name"].startswith("sweep")
                       for r in presented["rows"])

    def test_the_declared_metrics_drive_the_sweep_columns(self, presented):
        """
        `metrics_for_schema` had no production consumer before this — it
        declared dotted names nothing rendered. The sweep's columns are it.
        """
        from potato.server_utils.iaa.dispatcher import metrics_for_schema

        declared = metrics_for_schema(
            {"annotation_type": "rollout_evaluation", "name": "r"})
        for column in presented["sweep"]["columns"]:
            assert column in declared

    def test_every_scale_present_is_explained(self, presented):
        scales = set(presented["scales"])
        used = {r["scale"] for r in presented["rows"]
                if r["scale"] in P.SCALE_NOTES}
        assert used <= scales

    def test_the_legend_keeps_a_fixed_order(self, presented):
        """A legend that reorders per card reads as a different legend."""
        order = [s for s in P.SCALE_NOTES if s in presented["scales"]]
        assert presented["scales"] == order


class TestPresentAgainstAnEpisodeReport:
    """Wave 9's report is nested for the same reason and broke the same way."""

    def test_grouped_metrics_flatten(self):
        report = {"schemas": {"ep": {
            "kind": "episode", "annotation_type": "episode_annotation",
            "metrics": {"n_items": 4,
                        "phases": {"mean_agreement": 0.72, "detection_f1": 0.8},
                        "outcome": {"outcome_alpha": 0.65},
                        "reward": {"reward_icc": 0.5, "reward_coverage": 0.9}}}}}
        rows = {r["name"]: r for r in P.present(report)["schemas"]["ep"]["rows"]}
        assert rows["phases.mean_agreement"]["display"] == "0.720"
        assert rows["outcome.outcome_alpha"]["band"] == "strong"
        assert rows["reward.reward_coverage"]["band"] == ""   # coverage
        assert P.present(report)["schemas"]["ep"]["sweep"] is None


class TestPresentIsNonDestructive:
    def test_the_original_report_is_not_mutated(self):
        """
        The JSON body of /admin/iaa is the nested report; presentation must not
        reach back into it.
        """
        metrics = {"n_items": 2, "detection": {"alpha": 0.5}}
        report = {"schemas": {"s": {"annotation_type": "rollout_evaluation",
                                    "metrics": metrics}}}
        before = json.dumps(report, sort_keys=True)
        P.present(report)
        assert json.dumps(report, sort_keys=True) == before

    def test_an_unknown_annotation_type_still_presents(self):
        report = {"schemas": {"s": {"annotation_type": "radio",
                                    "metrics": {"cohens_kappa": 0.9}}}}
        rows = P.present(report)["schemas"]["s"]["rows"]
        assert rows[0]["band"] == "strong"
