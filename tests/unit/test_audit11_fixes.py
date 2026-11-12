"""
Regressions for the audit-11 findings.

The theme is the same key-versus-value inversion audit 10 fixed for parquet and
for the matrix kinds, one reader further along -- plus a phase enum that could
write a value its own parser rejected.
"""

import json
import os
import re

import pytest

from potato.item_state_management import Label
from potato.phase import UserPhase
from potato.server_utils.iaa import dispatcher as disp


def _flat(schema, values):
    """The stored shape: a flat {Label: value} container."""
    return {Label(schema, k): v for k, v in values.items()}


class _State:
    """Minimum surface `_gather_labels` / `_gather_matrix` read."""

    def __init__(self, per_item):
        self._per_item = per_item

    def get_label_annotations(self, instance_id):
        return self._per_item.get(instance_id, {})


class TestEveryPhaseRoundTrips:
    """A phase that can be written but not read back drops the annotator.

    `UserPhase.DONE` had no branch in `fromstr`, so every annotator who reached
    the Thank You page raised ValueError at the next boot. `load_user_data`
    catches that per directory and skips it, which emptied agreement, the
    adjudication queue and the per-item annotator cap while the state files on
    disk were intact.
    """

    @pytest.mark.parametrize("member", list(UserPhase))
    def test_member_round_trips(self, member):
        assert UserPhase.fromstr(str(member)) is member

    @pytest.mark.parametrize("member", list(UserPhase))
    def test_round_trip_is_case_insensitive(self, member):
        assert UserPhase.fromstr(str(member).upper()) is member

    def test_done_specifically(self):
        # The one that was missing, named so a regression reads as itself.
        assert UserPhase.fromstr("done") is UserPhase.DONE

    def test_an_unknown_phase_still_raises(self):
        with pytest.raises(ValueError):
            UserPhase.fromstr("not-a-phase")


class TestPackedAnswersAreRead:
    """Six of seven set/order-valued types store the answer in the VALUE."""

    def test_a_taxonomy_disagreement_is_not_perfect_agreement(self):
        scheme = {"annotation_type": "hierarchical_multiselect", "name": "topics"}
        r1 = _State({"t01": _flat("topics", {
            "selected_labels": "Annotation,People,Crowdworkers"})})
        r2 = _State({"t01": _flat("topics", {
            "selected_labels": "Annotation,People,Experts"})})

        rows = disp._gather_labels(["t01"], {"r1": r1, "r2": r2}, "topics",
                                   scheme=scheme)
        # Two shared paths, four in the union.
        assert disp._aggregate_multilabel(rows)["mean_jaccard"] == pytest.approx(0.5)

    def test_the_gathered_value_is_never_the_key_name(self):
        scheme = {"annotation_type": "hierarchical_multiselect", "name": "topics"}
        state = _State({"t01": _flat("topics", {"selected_labels": "A,B"})})
        rows = disp._gather_labels(
            ["t01"], {"r1": state, "r2": state}, "topics", scheme=scheme)
        assert rows["t01"]["r1"] == ["A", "B"]
        assert "selected_labels" not in rows["t01"]["r1"]

    def test_a_reversed_ranking_is_not_agreement(self):
        scheme = {"annotation_type": "ranking", "name": "priority"}
        a = _State({"i1": _flat("priority", {"rank_order": "Cost,Agreement,Accuracy"})})
        b = _State({"i1": _flat("priority", {"rank_order": "Accuracy,Agreement,Cost"})})
        rows = disp._gather_labels(["i1"], {"a": a, "b": b}, "priority", scheme=scheme)
        assert disp._aggregate_ranking(rows)["kendall_tau"] == pytest.approx(-1.0)

    def test_a_card_sort_compares_placements_not_group_names(self):
        scheme = {"annotation_type": "card_sort", "name": "sortit"}
        a = _State({"i1": _flat("sortit", {"sortit": json.dumps(
            {"A": ["c1", "c2"], "B": ["c3"]})})})
        b = _State({"i1": _flat("sortit", {"sortit": json.dumps(
            {"A": ["c1"], "B": ["c2", "c3"]})})})
        rows = disp._gather_labels(["i1"], {"a": a, "b": b}, "sortit", scheme=scheme)
        # Both saw the same two groups; scoring group names would give 1.0.
        assert disp._aggregate_multilabel(rows)["mean_jaccard"] < 1.0

    def test_pairwise_scale_reads_a_number_from_the_value(self):
        scheme = {"annotation_type": "pairwise", "name": "pw", "mode": "scale"}
        a = _State({"i1": _flat("pw", {"scale_value": "-2"}),
                    "i2": _flat("pw", {"scale_value": "1"})})
        b = _State({"i1": _flat("pw", {"scale_value": "-1"}),
                    "i2": _flat("pw", {"scale_value": "1"})})
        rows = disp._gather_labels(["i1", "i2"], {"a": a, "b": b}, "pw",
                                   numeric=True, scheme=scheme)
        assert rows["i1"]["a"] == [-2.0]
        assert disp._aggregate_continuous(rows)["mae"] == pytest.approx(0.5)

    def test_a_type_that_is_not_packed_is_left_alone(self):
        # radio's key IS the answer; touching it would break the majority type.
        assert disp.packed_answer(
            {"annotation_type": "radio", "name": "r"}, {"positive": True}) is None


class TestKindMatchesWhatTheTypeStores:
    """None of bws/pairwise/conjoint holds a ranked sequence."""

    @pytest.mark.parametrize("scheme,expected", [
        ({"annotation_type": "ranking", "name": "x"}, "ranking"),
        ({"annotation_type": "bws", "name": "x"}, "matrix"),
        ({"annotation_type": "conjoint", "name": "x"}, "nominal"),
        ({"annotation_type": "pairwise", "name": "x"}, "nominal"),
        ({"annotation_type": "pairwise", "name": "x", "mode": "scale"}, "continuous"),
        ({"annotation_type": "pairwise", "name": "x",
          "mode": "multi_dimension"}, "matrix"),
        ({"annotation_type": "hierarchical_multiselect", "name": "x"}, "multilabel"),
        ({"annotation_type": "card_sort", "name": "x"}, "multilabel"),
    ])
    def test_classification(self, scheme, expected):
        assert disp.classify_schema(scheme).value == expected

    def test_bws_scores_best_and_worst_separately(self):
        scheme = {"annotation_type": "bws", "name": "bw"}
        a = _State({"i1": _flat("bw", {"best": "A", "worst": "C"}),
                    "i2": _flat("bw", {"best": "B", "worst": "A"})})
        b = _State({"i1": _flat("bw", {"best": "A", "worst": "B"}),
                    "i2": _flat("bw", {"best": "B", "worst": "A"})})
        rows = disp._gather_matrix(["i1", "i2"], {"a": a, "b": b}, "bw")
        metrics = disp._aggregate_matrix(rows, scheme)

        # Item names are categories, not a scale.
        assert metrics["scale"] == "nominal"
        assert "alpha_nominal" in metrics["best"]
        # They agreed on every best and disagreed on one worst, and the report
        # says which -- a single pooled number could not.
        assert metrics["best"]["alpha_nominal"] == pytest.approx(1.0)
        assert metrics["worst"]["alpha_nominal"] < 1.0

    def test_a_nominal_matrix_gets_no_ordinal_metrics(self):
        scheme = {"annotation_type": "bws", "name": "bw"}
        a = _State({"i1": _flat("bw", {"best": "A", "worst": "C"})})
        b = _State({"i1": _flat("bw", {"best": "A", "worst": "B"})})
        rows = disp._gather_matrix(["i1"], {"a": a, "b": b}, "bw")
        metrics = disp._aggregate_matrix(rows, scheme)
        assert "weighted_kappa_linear" not in metrics["best"]


class TestSingleAnnotatorItemsAreNotCountedAsScored:
    """`n_items: 3, n_annotators: 0` reads as data loss, not as 'not yet'."""

    def test_one_annotator_gathers_nothing(self):
        scheme = {"annotation_type": "radio", "name": "r"}
        only = _State({"i1": _flat("r", {"yes": True}),
                       "i2": _flat("r", {"yes": True})})
        rows = disp._gather_labels(["i1", "i2"], {"solo": only}, "r", scheme=scheme)
        assert rows == {}

    def test_the_counts_agree_with_each_other(self):
        scheme = {"annotation_type": "ranking", "name": "priority"}
        only = _State({f"i{i}": _flat("priority", {"rank_order": "A,B"})
                       for i in range(3)})
        rows = disp._gather_labels(
            ["i0", "i1", "i2"], {"solo": only}, "priority", scheme=scheme)
        metrics = disp._aggregate_ranking(rows)
        assert metrics["n_items"] == 0
        assert metrics["n_annotators"] == 0


class TestMetricsForSchemaHonoursTheComputedKind:
    """A report row carries the type, not the mode -- so it must carry the kind."""

    def test_pairwise_scale_lists_continuous_metrics(self):
        listed = disp.metrics_for_schema(
            {"annotation_type": "pairwise", "name": "pw"}, kind="continuous")
        assert "pearson_r" in listed
        assert "percent_agreement" not in listed

    def test_an_unknown_kind_falls_back_to_the_type(self):
        listed = disp.metrics_for_schema(
            {"annotation_type": "radio", "name": "r"}, kind="not-a-kind")
        assert "alpha_nominal" in listed


class TestAutoSelectParentIsHonoured:
    """`auto_select_parent: false` must not select ancestors."""

    def _script(self):
        from potato.server_utils.schemas.hierarchical_multiselect import (
            generate_hierarchical_multiselect_layout)
        html, _ = generate_hierarchical_multiselect_layout({
            "annotation_type": "hierarchical_multiselect",
            "name": "topics", "description": "T",
            "taxonomy": [{"name": "Annotation",
                          "children": [{"name": "Process",
                                        "children": [{"name": "Adjudication"}]}]}],
        })
        return html

    def test_the_ancestor_chain_is_gated_on_the_config(self):
        script = self._script()
        # The block that walks up and checks parents must be inside an
        # autoParent guard -- it used to run unconditionally.
        assert "if (autoParent && cb.checked)" in script
        assert "// Always select ancestor chain when a node is checked" not in script

    def test_a_parent_is_only_taken_when_every_child_is_checked(self):
        script = self._script()
        # The documented meaning of the key: "auto-select parent when ALL
        # children selected". Selecting on any descendant is the bug.
        assert "allChecked" in script
        assert "every(s => s.checked)" in script


class TestLayoutBreakpointsCoverEveryCollapseRule:
    """`layout.columns: 2` collapsed at a hardcoded 768px whatever was configured."""

    def _js(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "static", "annotation.js")) as f:
            return f.read()

    def test_the_two_column_span_is_restated(self):
        js = self._js()
        # styles.css takes span 2 down to span 1 below its own 768px. The
        # injected block has to put it back above the author's mobile threshold,
        # or a two-column span is unreachable in the whole tablet band.
        assert 'data-grid-columns="2"] {\n                        grid-column: span 2 !important;' in js

    def test_the_container_track_count_is_restated(self):
        js = self._js()
        # styles.css sets grid-template-columns: 1fr directly at 768px, and a
        # literal declaration beats the var-based one no matter what
        # --layout-columns computes to.
        setup = js[js.index("setupResponsiveBreakpoints()"):]
        setup = setup[:setup.index("Helper to escape HTML")]
        assert setup.count("repeat(var(--layout-columns, 2), 1fr) !important") >= 2

    def test_styles_css_still_has_the_rules_being_restated(self):
        # If styles.css drops them, the restatements above become dead weight
        # and this test should say so rather than passing quietly.
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "static", "styles.css")) as f:
            css = f.read()
        assert "@media (max-width: 768px)" in css


class TestAdjudicationCanDecideEverySchema:
    """The final label is the deliverable; composite schemes produced none."""

    def _js(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "static",
                               "adjudication-forms.js")) as f:
            return f.read()

    def test_there_is_no_dead_end_for_unknown_types(self):
        js = self._js()
        assert "Form not available for type" not in js
        assert "return renderAdoptForm(schema, annotations, behavioralData, config);" in js

    def test_the_adopt_form_is_collected_into_the_decision(self):
        js = self._js()
        assert ".adj-adopt-options" in js
        # The stored answer, not a radio index the server never saw.
        assert "decisions[schema] = values[idx];" in js

    def test_a_labelled_likert_is_adjudicated_in_its_own_value_space(self):
        js = self._js()
        # A likert with `labels:` renders for the annotator as a radio group
        # storing "Good"; a slider would store 3 and need a mapping nobody wrote.
        assert "if (Array.isArray(schema.labels) && schema.labels.length) {" in js

    def test_the_adopt_list_is_cleared_between_items(self):
        js = self._js()
        reset = js[js.index("function resetColors()"):]
        assert "adoptValues = {};" in reset[:400]


class TestAdjudicationShowsTheItemAsAnnotated:
    def test_internal_fields_are_not_dumped(self):
        from potato.routes import _ADJUDICATION_INTERNAL_FIELDS
        # `displayed_text` is a rendered copy of the text field, so printing it
        # showed the adjudicator the same passage twice under an internal name.
        assert "displayed_text" in _ADJUDICATION_INTERNAL_FIELDS

    def test_the_client_prefers_the_configured_display(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "static", "adjudication.js")) as f:
            js = f.read()
        assert "data.item_display_html" in js
        assert "data.item_internal_fields" in js


class TestFlagLabelsSayWhatTheyMeasure:
    def test_low_agreement_names_its_scope(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "static", "adjudication.js")) as f:
            js = f.read()
        # "low agreement" beside a per-scheme 100% is a contradiction; the flag
        # is about the annotator's record across every item.
        assert "low_agreement: 'low agreement across all items'" in js
        assert "excessive_changes: 'many edits on this item'" in js

    def test_every_flag_type_the_server_emits_has_a_label(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "adjudication.py")) as f:
            server = f.read()
        with open(os.path.join(here, "potato", "static", "adjudication.js")) as f:
            js = f.read()
        emitted = set(re.findall(r'"type":\s*"(\w+)"', server))
        assert emitted, "no flag types found in adjudication.py"
        labels = js[js.index("var FLAG_LABELS"):js.index("function flagLabel")]
        for flag_type in emitted:
            assert flag_type in labels, f"{flag_type} has no human label"


class TestAdjudicatedDecisionsAreExportable:
    def test_the_format_is_registered(self):
        from potato.export.registry import export_registry
        assert export_registry.is_registered("adjudication")

    def test_a_composite_decision_survives_the_export(self, tmp_path):
        from potato.export.base import ExportContext
        from potato.export.adjudication_exporter import AdjudicationExporter

        project = tmp_path / "project"
        (project / "adjudication").mkdir(parents=True)
        (project / "adjudication" / "decisions.json").write_text(json.dumps({
            "decisions": [{
                "instance_id": "t01", "adjudicator_id": "adj", "timestamp": "T",
                "label_decisions": {
                    "decision": "Include",
                    "reasons": {"Intervention": "40", "Population": "60"},
                },
                "span_decisions": [], "source": {"decision": "adjudicator",
                                                 "reasons": "r1"},
                "confidence": "high", "notes": "", "error_taxonomy": [],
                "time_spent_ms": 100,
            }]
        }))

        ctx = ExportContext(
            config={"output_annotation_dir": str(project),
                    "adjudication": {"enabled": True}},
            annotations=[], items={},
            schemas=[{"name": "decision"}, {"name": "reasons"}],
            output_dir=str(project))

        exporter = AdjudicationExporter()
        can, reason = exporter.can_export(ctx)
        assert can, reason

        out = tmp_path / "out"
        result = exporter.export(ctx, str(out))
        assert result.success

        rows = (out / "adjudicated.csv").read_text()
        assert "Include" in rows
        # The composite answer survives whole rather than collapsing to a key.
        assert "Intervention" in rows and "60" in rows
        # And the audit trail is a separate file, not mixed into the dataset.
        assert (out / "adjudication_log.jsonl").exists()

    def test_it_reads_the_resolved_output_dir_not_the_raw_config_value(self, tmp_path):
        """The config value is usually relative; only context.output_dir is resolved.

        Reading the raw value resolved it against the *caller's* working
        directory, so exporting a project from the repo root picked up an
        unrelated ./annotation_output and exported another study's decisions
        under this study's name. Found by running the real CLI, not by this
        suite -- the first version of this test set both paths to tmp_path,
        which is exactly the case that cannot catch it.
        """
        from potato.export.base import ExportContext
        from potato.export.adjudication_exporter import (
            AdjudicationExporter, _decisions_path)

        real = tmp_path / "the-project"
        (real / "adjudication").mkdir(parents=True)
        (real / "adjudication" / "decisions.json").write_text(json.dumps({
            "decisions": [{"instance_id": "mine", "adjudicator_id": "a",
                           "timestamp": "T", "label_decisions": {"s": "v"},
                           "span_decisions": [], "source": {}, "confidence": "high",
                           "notes": "", "error_taxonomy": []}]}))

        ctx = ExportContext(
            config={"output_annotation_dir": "annotation_output",  # relative!
                    "adjudication": {"enabled": True}},
            annotations=[], items={}, schemas=[{"name": "s"}],
            output_dir=str(real))

        assert _decisions_path(ctx).startswith(str(real))
        can, reason = AdjudicationExporter().can_export(ctx)
        assert can, reason

        out = tmp_path / "out"
        AdjudicationExporter().export(ctx, str(out))
        assert "mine" in (out / "adjudicated.csv").read_text()

    def test_the_adopt_list_shows_the_answer_not_the_storage_key(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "static",
                               "adjudication-forms.js")) as f:
            js = f.read()
        # {"selected_labels": "Annotation,People"} must read as the paths alone.
        assert "var PACKED_KEYS" in js
        for key in ("selected_labels", "rank_order", "selection",
                    "scale_value", "_data"):
            assert f"'{key}'" in js[js.index("var PACKED_KEYS"):
                                    js.index("function formatAnswer")]

    def test_it_declines_when_nothing_has_been_adjudicated(self, tmp_path):
        from potato.export.base import ExportContext
        from potato.export.adjudication_exporter import AdjudicationExporter
        ctx = ExportContext(
            config={"output_annotation_dir": str(tmp_path),
                    "adjudication": {"enabled": True}},
            annotations=[], items={}, schemas=[], output_dir=str(tmp_path))
        can, reason = AdjudicationExporter().can_export(ctx)
        assert not can
        assert "decisions" in reason.lower()


class TestWaitingIsDistinguishableFromNothing:
    def test_the_report_carries_the_below_cap_count(self):
        # The empty report and the "one annotator short on every item" report
        # were byte-for-byte identical before this field existed.
        from potato.server_utils.iaa.dispatcher import compute_overlap_iaa
        import inspect
        src = inspect.getsource(compute_overlap_iaa)
        assert '"n_items_below_cap": n_items_below_cap' in src

    def test_the_admin_page_shows_it(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "templates", "admin",
                               "iaa.html")) as f:
            html = f.read()
        assert "report.n_items_below_cap" in html


class TestTheAssistantRowFitsANarrowCell:
    def _css(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, "potato", "static", "styles.css")) as f:
            return f.read()

    def test_the_container_is_the_shell_not_the_form(self):
        """`container-type` on `.annotation-form` breaks the grid.

        It applies `contain: inline-size`, and a span-1 grid item then resolves
        to its contain-intrinsic width -- measured in Chrome at 18px against a
        123px track. The fieldset behaves the same way. Only a plain block
        wrapper, whose width comes from its parent, can carry the container.
        """
        css = self._css()
        assert "@container ai-help-shell (max-width: 260px)" in css
        assert "container-name: ai-help-shell;" in css
        # The form must NOT be a container.
        form_rule = css[css.index(".annotation-form {"):]
        form_rule = form_rule[:form_rule.index("}")]
        assert "container-type" not in form_rule

    def test_the_shell_has_a_definite_width(self):
        """Without one, a size-contained flex item resolves to 0.

        `.annotation-form` is a column flex container. A contained child with no
        definite inline size measured 0, so the query matched on every cell by
        accident rather than by measurement.
        """
        css = self._css()
        shell = css[css.index(".ai-help-shell {"):]
        shell = shell[:shell.index("}")]
        assert "width: 100%" in shell

    def test_the_shell_is_emitted_around_the_row(self):
        from potato.ai.ai_help_wrapper import DynamicAIHelp
        html = DynamicAIHelp.__new__(DynamicAIHelp).get_empty_wrapper()
        assert 'class="ai-help-shell"' in html
        # The row must be INSIDE the shell -- a sibling would not be measured.
        assert '<div class="ai-help-shell"><div class="ai-help' in html

    def test_the_label_is_hidden_not_removed(self):
        css = self._css()
        block = css[css.index("@container ai-help-shell (max-width: 260px)"):]
        # display:none would take the accessible name with it.
        assert "display: none" not in block[:block.index("min-height")]
        assert "clip-path: inset(50%)" in block

    def test_the_icon_only_target_meets_wcag_aa(self):
        """24px is WCAG 2.2 AA (2.5.8). The 44px AAA figure does not fit.

        Three 44px targets need 132px and the row is around 105px, so demanding
        it forced a wrap and put the row back to three lines -- the height
        problem the rule exists to fix.
        """
        css = self._css()
        block = css[css.index("@container ai-help-shell (max-width: 260px)"):]
        assert "min-width: 1.5rem;" in block
        assert "min-height: 1.5rem;" in block
        assert "2.75rem" not in block

    def test_the_button_carries_its_name_as_a_title(self):
        from potato.ai.ai_help_wrapper import DynamicAIHelp
        wrapper = DynamicAIHelp.__new__(DynamicAIHelp)
        prompts = {"radio": {"hint": {"name": "Hint", "img": "/x.png"}}}
        html = wrapper.generate_ai_assistant(prompts, "radio", "hint")
        assert 'title="Hint"' in html
        # The visible label stays in the DOM as the accessible name.
        assert "<span>Hint</span>" in html

    def test_a_name_with_a_quote_cannot_break_the_attribute(self):
        from potato.ai.ai_help_wrapper import DynamicAIHelp
        wrapper = DynamicAIHelp.__new__(DynamicAIHelp)
        prompts = {"radio": {"hint": {"name": 'He said "go"', "img": ""}}}
        html = wrapper.generate_ai_assistant(prompts, "radio", "hint")
        assert 'title="He said &quot;go&quot;"' in html
