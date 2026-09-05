"""
Regressions for the defects audit 12 found.

Each test names the symptom an annotator or a researcher saw, not the function
that produced it, because the function is what moves.
"""

import json
import os
import tempfile

import pytest


# --------------------------------------------------------------------------
# 1. The AI assistant answered about a different item
# --------------------------------------------------------------------------

class TestAiHelpAddressesTheVisibleItem:
    """`get_ai_help` is called with an instance id, not a queue position.

    Under any strategy that reorders (random, active_learning, ...) the
    annotator's position and the corpus position are different items from the
    first item on, and the AI cache resolved the position against the corpus.
    """

    def test_ai_cache_resolves_by_instance_id(self, monkeypatch):
        from potato.ai import ai_cache

        class FakeItem:
            def __init__(self, iid, text):
                self._iid, self._text = iid, text

            def get_data(self):
                return {"id": self._iid, "text": self._text}

        corpus = {"r1": FakeItem("r1", "The soup was cold."),
                  "r2": FakeItem("r2", "Best pastry in this city.")}

        class FakeISM:
            def find_item(self, iid):
                return corpus.get(iid)

            def items(self):
                return [corpus["r1"], corpus["r2"]]

            def get_instance_ids(self):
                return ["r1", "r2"]

        monkeypatch.setattr(ai_cache, "get_item_state_manager", lambda: FakeISM())
        monkeypatch.setattr(ai_cache, "config", {"item_properties": {"text_key": "text"}})

        assert ai_cache._get_instance_text("r2") == "Best pastry in this city."
        assert ai_cache._get_instance_text("r1") == "The soup was cold."
        # An int is still resolved positionally, for the prefetch walk.
        assert ai_cache._get_instance_text(0) == "The soup was cold."

    def test_route_passes_the_id_not_the_index(self):
        """The route reads `get_current_instance_id`, whose value is the item."""
        import inspect
        from potato import routes

        src = inspect.getsource(routes.get_ai_suggestion)
        code = "\n".join(line for line in src.splitlines()
                         if not line.lstrip().startswith("#"))
        assert "get_current_instance_id()" in code
        assert "get_current_instance_index()" not in code


# --------------------------------------------------------------------------
# 2. A `document` display field executed script from the data file
# --------------------------------------------------------------------------

class TestDocumentDisplayEscapesCorpusHtml:
    PAYLOAD = ('<b>BOLD FROM DATA</b> and '
               '<img src=x onerror="window.__potato_probe=\'fired\'">')

    def test_span_mode_strips_handlers(self):
        from potato.server_utils.displays.document_display import DocumentDisplay

        html = DocumentDisplay().render(
            {"key": "excerpt", "type": "document", "span_target": True},
            self.PAYLOAD)
        assert "onerror" not in html
        assert "__potato_probe" not in html
        # Legitimate formatting from the corpus still renders.
        assert "<b>BOLD FROM DATA</b>" in html

    def test_bbox_mode_strips_handlers(self):
        from potato.server_utils.displays.document_display import DocumentDisplay

        html = DocumentDisplay().render(
            {"key": "excerpt", "type": "document",
             "display_options": {"annotation_mode": "bounding_box"}},
            self.PAYLOAD)
        assert "onerror" not in html

    def test_pipeline_html_is_also_filtered(self):
        """A converted DOCX is only as trustworthy as the file it came from."""
        from potato.server_utils.displays.document_display import DocumentDisplay

        html = DocumentDisplay().render(
            {"key": "doc", "type": "document"},
            {"rendered_html": '<p onclick="steal()">hi</p><script>x()</script>',
             "metadata": {}, "text": "hi"})
        assert "onclick" not in html
        assert "<script>" not in html


# --------------------------------------------------------------------------
# 3. The adjudication queue scored every composite scheme 100%
# --------------------------------------------------------------------------

class TestCompositeAnswersCompareByWhatWasAnswered:

    @pytest.mark.parametrize("scheme,a,b", [
        ({"name": "reasons", "annotation_type": "constant_sum",
          "labels": ["Intervention", "Outcome", "Population"]},
         {"Intervention": "30", "Outcome": "20", "Population": "50"},
         {"Intervention": "20", "Outcome": "20", "Population": "60"}),
        ({"name": "design", "annotation_type": "soft_label",
          "labels": ["A", "B"]},
         {"A": "0.7", "B": "0.3"}, {"A": "0.2", "B": "0.8"}),
        ({"name": "topics", "annotation_type": "hierarchical_multiselect"},
         {"selected_labels": "Annotation,People,Crowdworkers"},
         {"selected_labels": "Annotation,People,Experts"}),
        ({"name": "order", "annotation_type": "ranking"},
         {"rank_order": "Cost,Agreement"}, {"rank_order": "Agreement,Cost"}),
    ])
    def test_two_different_answers_are_not_equal(self, scheme, a, b):
        from potato.server_utils import annotation_values

        assert (annotation_values.comparable_value(scheme, a)
                != annotation_values.comparable_value(scheme, b))

    @pytest.mark.parametrize("scheme,value", [
        ({"name": "d", "annotation_type": "radio"}, {"Include": "Include"}),
        ({"name": "q", "annotation_type": "likert"}, {"3": "3"}),
        ({"name": "m", "annotation_type": "multiselect"}, {"a": True, "b": True}),
    ])
    def test_key_is_the_answer_types_are_unchanged(self, scheme, value):
        from potato.server_utils import annotation_values

        assert (annotation_values.comparable_value(scheme, value)
                == frozenset(annotation_values.selected_labels(value)))

    def test_adjudication_agreement_separates_distributions(self):
        from potato.adjudication import AdjudicationManager

        mgr = AdjudicationManager.__new__(AdjudicationManager)
        mgr.config = {"annotation_schemes": [
            {"name": "reasons", "annotation_type": "constant_sum",
             "labels": ["Intervention", "Outcome", "Population"]}]}
        item_annotations = {
            "u1": {"reasons": {"Intervention": "30", "Outcome": "20",
                               "Population": "50"}},
            "u2": {"reasons": {"Intervention": "20", "Outcome": "20",
                               "Population": "60"}},
            "u3": {"reasons": {"Intervention": "25", "Outcome": "20",
                               "Population": "55"}},
        }
        scores = mgr._compute_agreement(item_annotations, ["reasons"])
        assert scores["reasons"] == 0.0, scores


# --------------------------------------------------------------------------
# 4. Uncertainty sampling threw on every active-learning run
# --------------------------------------------------------------------------

class TestQueryStrategiesRankRatherThanFallBack:

    @staticmethod
    def _fitted_pipeline():
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline

        texts = ["good great excellent", "bad awful terrible",
                 "good nice fine", "bad poor lousy",
                 "excellent superb", "terrible horrid"]
        labels = ["pos", "neg", "pos", "neg", "pos", "neg"]
        pipe = Pipeline([("vectorizer", TfidfVectorizer()),
                         ("classifier", LogisticRegression())])
        pipe.fit(texts, labels)
        return pipe, texts

    def test_uncertainty_ranks_the_ambiguous_item_first(self):
        from potato.active_learning_manager import UncertaintySampling

        pipe, annotated = self._fitted_pipeline()
        vec = pipe.named_steps["vectorizer"]
        unlabeled = ["good excellent great", "terrible awful", "good bad"]

        ranked = UncertaintySampling().rank(unlabeled, pipe, vec, annotated)
        scores = [s for _, s in ranked]

        # The failure mode was a uniform 0.5 for every instance -- the
        # except-branch's constant, not a ranking.
        assert len(set(round(float(s), 6) for s in scores)) > 1
        assert ranked[0][0] == 2  # "good bad" is the ambiguous one

    def test_badge_and_bald_do_not_double_vectorize(self):
        from potato.active_learning_manager import BadgeStrategy, BaldStrategy

        pipe, annotated = self._fitted_pipeline()
        vec = pipe.named_steps["vectorizer"]
        unlabeled = ["good excellent great", "terrible awful", "good bad"]

        for strategy in (BadgeStrategy(), BaldStrategy()):
            ranked = strategy.rank(unlabeled, pipe, vec, annotated)
            scores = [round(float(s), 6) for _, s in ranked]
            assert scores != [0.5, 0.5, 0.5], type(strategy).__name__


# --------------------------------------------------------------------------
# 5. active_learning estimator names
# --------------------------------------------------------------------------

class TestEstimatorNames:

    def test_short_names_resolve(self):
        from potato.active_learning_manager import ActiveLearningConfig

        cfg = ActiveLearningConfig(classifier_name="logistic",
                                   vectorizer_name="tfidf")
        assert cfg.classifier_name == "sklearn.linear_model.LogisticRegression"
        assert (cfg.vectorizer_name
                == "sklearn.feature_extraction.text.TfidfVectorizer")

    def test_a_name_nothing_can_build_is_a_config_error(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_active_learning_config)

        with pytest.raises(ConfigValidationError) as excinfo:
            validate_active_learning_config({"active_learning": {
                "enabled": True, "classifier": {"name": "magic_forest"}}})
        # The error names what IS accepted, like the display_options one does.
        assert "logistic" in str(excinfo.value)

    def test_documented_names_validate(self):
        from potato.server_utils.config_module import validate_active_learning_config

        validate_active_learning_config({"active_learning": {
            "enabled": True,
            "classifier": {"name": "sklearn.svm.SVC"},
            "vectorizer": {"name": "sentence-transformers"}}})


# --------------------------------------------------------------------------
# 6. The AI blocks' sub-keys are documented and validated
# --------------------------------------------------------------------------

class TestAiBlockKeysAreDocumentedAndChecked:

    def test_active_learning_sub_keys_have_docs(self):
        from potato.server_utils.config_key_docs import get_key_doc
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

        for sub in KNOWN_CONFIG_KEYS["active_learning"]:
            assert get_key_doc(f"active_learning.{sub}") is not None, sub

    def test_icl_labeling_sub_keys_are_known(self):
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

        known = KNOWN_CONFIG_KEYS["icl_labeling"]
        assert isinstance(known, dict)
        assert "example_selection" in known
        assert "min_annotators_per_instance" in known["example_selection"]

    def test_a_made_up_icl_key_is_reported(self, caplog):
        import logging

        from potato.server_utils.config_module import validate_unknown_keys

        with caplog.at_level(logging.WARNING,
                             logger="potato.server_utils.config_module"):
            validate_unknown_keys({
                "icl_labeling": {"enabled": True, "min_confidence": 0.7}})
        assert any("min_confidence" in r.getMessage()
                   for r in caplog.records), caplog.text


# --------------------------------------------------------------------------
# 8/9. The codebook and quotation exports
# --------------------------------------------------------------------------

def _span(schema, name, start, end, field="text"):
    return {"schema": schema, "name": name, "start": start, "end": end,
            "target_field": field}


class TestQualitativeExports:

    def _context(self, tmpdir):
        from potato.export.base import ExportContext

        schemas = [{"name": "codes", "annotation_type": "span",
                    "labels": [{"name": "Boundary erosion"}]}]
        items = {"e01": {"id": "e01",
                         "text": "the calendar ate everything. I said so."}}
        annotations = [{
            "instance_id": "e01", "user_id": "c1@x.com",
            "labels": {}, "spans": {
                "codes": [_span("codes", "Boundary erosion", 0, 27)]},
        }]
        return ExportContext(config={"task_dir": tmpdir,
                                     "item_properties": {"text_key": "text"}},
                             annotations=annotations, items=items,
                             schemas=schemas, output_dir=tmpdir)

    def test_quotation_report_carries_the_code_and_the_words(self):
        import csv

        from potato.export.quotation_report_exporter import QuotationReportExporter

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._context(tmpdir)
            QuotationReportExporter().export(ctx, tmpdir)
            with open(os.path.join(tmpdir, "quotations.csv")) as f:
                rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]["code"] == "Boundary erosion"
        assert rows[0]["text"] == "the calendar ate everything"

    def test_codebook_counts_span_uses(self):
        import csv

        from potato.export.codebook_exporter import CodebookExporter

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._context(tmpdir)
            CodebookExporter().export(ctx, tmpdir)
            with open(os.path.join(tmpdir, "codebook.csv")) as f:
                rows = list(csv.DictReader(f))

        by_code = {r["code"]: r for r in rows}
        assert by_code["Boundary erosion"]["n_uses"] == "1"


# --------------------------------------------------------------------------
# 11. The second annotator's progress counter read N/N
# --------------------------------------------------------------------------

class TestProgressDenominatorCountsOwnAssignments:

    def test_a_held_item_is_still_work_to_do(self):
        from potato.item_state_management import ItemStateManager

        class FakeUserState:
            def __init__(self, assigned, annotated):
                self._assigned, self._annotated = set(assigned), set(annotated)

            def get_assigned_instance_ids(self):
                return set(self._assigned)

            def has_annotated(self, iid):
                return iid in self._annotated

        mgr = ItemStateManager.__new__(ItemStateManager)
        mgr.remaining_instance_ids = ["i%d" % n for n in range(6)]
        # Every item is saturated: two annotators hold all six.
        mgr._item_is_saturated = lambda iid: True

        second = FakeUserState(mgr.remaining_instance_ids, {"i0"})
        pending = mgr.get_progress_pending_ids_for_user(second)

        assert len(pending) == 5
        assert "i0" not in pending
