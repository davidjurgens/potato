"""
Model-output review: worst-first, and the items the model said nothing about.

Potato had every part of the model-prelabel-then-human-QC pipeline and not the
workflow. Adjudication compared human to human; nothing compared human to
model.

The asymmetry these tests exist to protect is the one review UIs get wrong.
A wrong prediction is visible -- it is right there, wrong. A *missing* one is
invisible: the reviewer sees an empty item and moves on. And a
confidence-ordered queue can never surface a missing prediction, because an
item with no prediction has no confidence to be low. So false negatives are
the failure class that survives review, and they only exist if you go looking.
"""

from __future__ import annotations

import json

import pytest

from potato import model_review as mr


def item(**predictions):
    return {"predictions": dict(predictions)} if predictions else {}


def summarize(instance_id, data, schemes=("boxes", "tone")):
    return mr.summarize_predictions(instance_id, data, "predictions", schemes)


# ------------------------------------------------------------------ reading


class TestReadingPredictions:
    def test_a_list_of_objects_counts_each_one(self):
        s = summarize("i1", item(boxes=[{"label": "cat"}, {"label": "dog"}]))
        assert s.n_predictions == 2
        assert not s.empty

    def test_an_empty_list_is_a_real_answer_not_missing_data(self):
        """
        "The model looked and found nothing" is exactly what puts an item in
        the false-negative pool. Skipping it would hide the pool entirely.
        """
        s = summarize("i1", item(boxes=[]))
        assert s.n_predictions == 0
        assert s.empty is True

    def test_no_predictions_key_at_all_is_empty(self):
        assert summarize("i1", {}).empty is True
        assert summarize("i1", {"predictions": None}).empty is True

    def test_a_bare_label_is_one_assertion(self):
        assert summarize("i1", item(tone="positive")).n_predictions == 1

    def test_a_json_string_blob_is_parsed(self):
        """Blob schemas store their objects as a JSON string."""
        s = summarize("i1", item(boxes=json.dumps([{"label": "a"}, {"label": "b"}])))
        assert s.n_predictions == 2

    def test_confidence_is_read_from_any_of_its_names(self):
        for key in mr.CONFIDENCE_KEYS:
            s = summarize("i1", item(boxes=[{key: 0.25}]))
            assert s.min_confidence == pytest.approx(0.25), key

    def test_the_minimum_confidence_is_what_ranks_the_item(self):
        """
        One bad box makes an item worth reviewing, even beside nine good ones.
        A mean would average that signal away.
        """
        s = summarize("i1", item(boxes=[{"confidence": 0.9},
                                        {"confidence": 0.2},
                                        {"confidence": 0.95}]))
        assert s.min_confidence == pytest.approx(0.2)
        assert s.mean_confidence == pytest.approx(0.6833, abs=1e-3)

    def test_predictions_without_confidence_report_none_not_zero(self):
        s = summarize("i1", item(boxes=[{"label": "cat"}]))
        assert s.n_predictions == 1
        assert s.min_confidence is None

    def test_a_scheme_the_project_does_not_configure_is_ignored(self):
        """
        Otherwise a stray key under `predictions` counts as a prediction and
        quietly keeps the item out of the false-negative pool.
        """
        s = mr.summarize_predictions("i1", item(ghost=[{"label": "x"}]),
                                     "predictions", ["boxes"])
        assert s.empty is True

    def test_a_boolean_is_not_a_confidence(self):
        s = summarize("i1", item(boxes=[{"confidence": True}]))
        assert s.min_confidence is None


# ------------------------------------------------------------------- queues


def summaries(spec):
    """spec: {instance_id: min_confidence or None or 'empty'}"""
    out = []
    for iid, conf in spec.items():
        if conf == "empty":
            out.append(summarize(iid, {}))
        elif conf is None:
            out.append(summarize(iid, item(boxes=[{"label": "x"}])))
        else:
            out.append(summarize(iid, item(boxes=[{"confidence": conf}])))
    return out


class TestReviewOrder:
    def test_least_confident_first(self):
        order = mr.review_order(summaries({"a": 0.9, "b": 0.1, "c": 0.5}))
        assert order == ["b", "c", "a"]

    def test_items_with_no_prediction_are_not_in_the_queue(self):
        """
        They have no confidence to rank, and reviewing them is a different
        job with a different purpose.
        """
        order = mr.review_order(summaries({"a": 0.5, "gap": "empty"}))
        assert order == ["a"]

    def test_predictions_without_confidence_sort_last(self):
        """
        A model that does not report confidence is not a model that is
        unsure. Treating None as 0 would fill the worst-first queue with
        items nobody has a reason to doubt.
        """
        order = mr.review_order(summaries({"quiet": None, "bad": 0.05,
                                           "good": 0.99}))
        assert order == ["bad", "good", "quiet"]

    def test_ties_break_deterministically(self):
        first = mr.review_order(summaries({"b": 0.5, "a": 0.5, "c": 0.5}))
        assert first == ["a", "b", "c"]

    def test_the_worst_fraction_is_the_head_of_the_queue(self):
        spec = {f"i{n}": n / 10 for n in range(10)}
        worst = mr.worst_fraction(summaries(spec), fraction=0.2)
        assert worst == ["i0", "i1"]

    def test_a_tiny_project_still_gets_one_item(self):
        """A 20% slice of three items rounds to one, not zero."""
        assert len(mr.worst_fraction(summaries({"a": 0.1, "b": 0.5,
                                                "c": 0.9}), 0.2)) == 1

    def test_an_empty_project_yields_an_empty_queue(self):
        assert mr.review_order([]) == []
        assert mr.worst_fraction([]) == []


class TestFalseNegativePool:
    def test_only_the_items_the_model_said_nothing_about(self):
        pool = mr.empty_prediction_ids(
            summaries({"a": 0.5, "gap1": "empty", "gap2": "empty"}))
        assert pool == ["gap1", "gap2"]

    def test_the_pool_and_the_queue_do_not_overlap(self):
        """
        The whole point: these are two disjoint review jobs, and an item in
        both would be double-counted in the metrics.
        """
        s = summaries({"a": 0.5, "gap": "empty"})
        assert not set(mr.review_order(s)) & set(mr.empty_prediction_ids(s))


# ---------------------------------------------------------------- verdicts


def verdicts(*specs):
    return [mr.ReviewVerdict(instance_id=iid, reviewer="alice", verdict=v)
            for iid, v in specs]


class TestMetrics:
    def test_precision_is_the_accepted_share(self):
        m = mr.review_metrics(verdicts(("a", "accept"), ("b", "accept"),
                                       ("c", "reject"), ("d", "correct")))
        assert m["precision"] == pytest.approx(0.5)
        assert m["n_reviewed"] == 4

    def test_a_corrected_prelabel_is_not_a_true_positive(self):
        """
        It was partly wrong. Counting corrections as correct lets a model
        that is always nearly-right score perfect precision.
        """
        m = mr.review_metrics(verdicts(("a", "correct")))
        assert m["precision"] == pytest.approx(0.0)

    def test_a_reviewer_changing_their_mind_is_counted_once(self):
        m = mr.review_metrics([
            mr.ReviewVerdict("a", "alice", "accept"),
            mr.ReviewVerdict("a", "alice", "reject"),
        ])
        assert m["n_reviewed"] == 1
        assert m["counts"]["reject"] == 1
        assert m["counts"]["accept"] == 0

    def test_recall_is_none_until_the_empty_pool_is_sampled(self):
        """
        A recall computed from a denominator nobody checked is a number that
        looks like evidence and is not.
        """
        m = mr.review_metrics(verdicts(("a", "accept")))
        assert m["recall"] is None
        assert "not reviewed" in m["recall_note"]

    def test_recall_falls_when_the_model_missed_things(self):
        clean = mr.review_metrics(verdicts(("a", "accept"), ("b", "accept")),
                                  reviewed_empty_ids=["g1", "g2"],
                                  found_in_empty_ids=[])
        missed = mr.review_metrics(verdicts(("a", "accept"), ("b", "accept")),
                                   reviewed_empty_ids=["g1", "g2"],
                                   found_in_empty_ids=["g1", "g2"])
        assert clean["recall"] == pytest.approx(1.0)
        assert missed["recall"] == pytest.approx(0.5)
        assert missed["n_false_negatives"] == 2

    def test_a_false_negative_outside_the_sample_is_not_counted(self):
        """
        Only items a human actually opened are evidence about what was
        missed; anything else inflates or deflates recall by assumption.
        """
        m = mr.review_metrics(verdicts(("a", "accept")),
                              reviewed_empty_ids=["g1"],
                              found_in_empty_ids=["g1", "never_opened"])
        assert m["n_false_negatives"] == 1

    def test_nothing_reviewed_reports_none_not_zero(self):
        m = mr.review_metrics([])
        assert m["precision"] is None
        assert m["n_reviewed"] == 0


class TestVerdictStorage:
    @pytest.fixture
    def config(self, tmp_path):
        return {"task_dir": str(tmp_path), "annotation_task_name": "proj"}

    def test_a_verdict_round_trips(self, config):
        mr.record_verdict(config, mr.ReviewVerdict("i1", "alice", "accept",
                                                   schema_name="boxes"))
        loaded = mr.load_verdicts(config)
        assert len(loaded) == 1
        assert (loaded[0].instance_id, loaded[0].verdict) == ("i1", "accept")

    def test_re_reviewing_replaces_rather_than_appends(self, config):
        mr.record_verdict(config, mr.ReviewVerdict("i1", "alice", "accept"))
        mr.record_verdict(config, mr.ReviewVerdict("i1", "alice", "reject"))
        loaded = mr.load_verdicts(config)
        assert len(loaded) == 1
        assert loaded[0].verdict == "reject"

    def test_two_reviewers_are_kept_apart(self, config):
        mr.record_verdict(config, mr.ReviewVerdict("i1", "alice", "accept"))
        mr.record_verdict(config, mr.ReviewVerdict("i1", "bob", "reject"))
        assert len(mr.load_verdicts(config)) == 2

    def test_an_unknown_verdict_is_refused(self, config):
        """
        Storing a typo silently would make the precision denominator wrong in
        a way nothing surfaces.
        """
        with pytest.raises(ValueError, match="accept"):
            mr.record_verdict(config, mr.ReviewVerdict("i1", "alice", "maybe"))
        assert mr.load_verdicts(config) == []

    def test_an_unreadable_database_returns_nothing_rather_than_raising(self):
        assert mr.load_verdicts({"task_dir": "/nonexistent/nowhere"}) == []


# --------------------------------------------------------- project summary


class FakeItem:
    def __init__(self, data):
        self._data = data

    def get_data(self):
        return self._data


class FakeISM:
    def __init__(self, items):
        self.items = items

    def iter_items(self):
        return list(self.items.items())


class TestProjectSummary:
    @pytest.fixture
    def config(self, tmp_path):
        return {
            "task_dir": str(tmp_path),
            "annotation_task_name": "proj",
            "pre_annotation": {"enabled": True, "field": "predictions"},
            "annotation_schemes": [
                {"annotation_type": "image_annotation", "name": "boxes",
                 "description": "d"}],
        }

    @pytest.fixture
    def ism(self):
        return FakeISM({
            "sure": FakeItem(item(boxes=[{"confidence": 0.95}])),
            "unsure": FakeItem(item(boxes=[{"confidence": 0.10}])),
            "gap": FakeItem(item(boxes=[])),
        })

    def test_the_queue_and_the_pool_are_both_reported(self, ism, config):
        report = mr.summarize_project(ism, config)
        assert report["queue"] == ["unsure", "sure"]
        assert report["empty_prediction_ids"] == ["gap"]
        assert report["n_prelabelled"] == 2
        assert report["n_items"] == 3

    def test_precision_comes_from_recorded_verdicts(self, ism, config):
        mr.record_verdict(config, mr.ReviewVerdict("sure", "alice", "accept"))
        mr.record_verdict(config, mr.ReviewVerdict("unsure", "alice", "reject"))
        report = mr.summarize_project(ism, config)
        assert report["metrics"]["precision"] == pytest.approx(0.5)

    def test_a_verdict_on_an_empty_item_becomes_a_false_negative(self, ism, config):
        """
        There was no prelabel to accept, so a verdict there can only mean the
        reviewer found something the model had not.
        """
        mr.record_verdict(config, mr.ReviewVerdict("sure", "alice", "accept"))
        mr.record_verdict(config, mr.ReviewVerdict("gap", "alice", "correct"))
        report = mr.summarize_project(ism, config)
        assert report["metrics"]["n_empty_reviewed"] == 1
        assert report["metrics"]["n_false_negatives"] == 1
        assert report["metrics"]["recall"] is not None

    def test_empty_verdicts_do_not_pollute_precision(self, ism, config):
        """
        The precision denominator is prelabelled items only. Counting an
        empty-item verdict there would penalise the model for a prediction it
        never made.
        """
        mr.record_verdict(config, mr.ReviewVerdict("sure", "alice", "accept"))
        mr.record_verdict(config, mr.ReviewVerdict("gap", "alice", "correct"))
        report = mr.summarize_project(ism, config)
        assert report["metrics"]["n_reviewed"] == 1
        assert report["metrics"]["precision"] == pytest.approx(1.0)


# ------------------------------------------------------------ registrations


class TestStrategyRegistration:
    def test_the_strategy_is_a_valid_config_value(self):
        """
        Per project memory: a new assignment strategy needs three
        registrations plus a has_unlabeled_items_for_user branch, or
        /annotate redirect-loops.
        """
        from potato.server_utils.config_module import _VALID_ASSIGNMENT_STRATEGIES

        assert "model_review" in _VALID_ASSIGNMENT_STRATEGIES

    def test_the_enum_member_exists(self):
        from potato.item_state_management import AssignmentStrategy

        assert AssignmentStrategy.fromstr("model_review") is \
            AssignmentStrategy.MODEL_REVIEW

    def test_it_has_an_availability_branch(self):
        """
        Without one the generic loop reports items as available that the
        strategy then refuses to serve, and /annotate ping-pongs between
        "you have work" and "there is none".
        """
        import inspect

        from potato.item_state_management import ItemStateManager

        source = inspect.getsource(ItemStateManager.has_unlabeled_items_for_user)
        assert "MODEL_REVIEW" in source

    def test_availability_and_assignment_share_one_candidate_list(self):
        """Two implementations of "what is available" is how they diverge."""
        import inspect

        from potato.item_state_management import ItemStateManager

        # `_assign_pass`, not `_assign_instances_to_user_inner`: the latter is
        # now the wrapper that runs the pass a second time with holds relaxed,
        # and the strategy branches live in the pass.
        for method in (ItemStateManager.has_unlabeled_items_for_user,
                       ItemStateManager._assign_pass):
            assert "_model_review_candidates" in inspect.getsource(method)

    def test_fromstr_covers_every_enum_member(self):
        """
        The registration point nothing forces you to remember. It used to be a
        hand-written if/elif chain, so a strategy added to the enum, the
        config whitelist and both assignment branches still raised "Unknown
        phase" the first time a real config used it.
        """
        from potato.item_state_management import AssignmentStrategy

        for strategy in AssignmentStrategy:
            assert AssignmentStrategy.fromstr(strategy.value) is strategy

    def test_every_valid_config_value_resolves(self):
        from potato.item_state_management import AssignmentStrategy
        from potato.server_utils.config_module import _VALID_ASSIGNMENT_STRATEGIES

        for name in _VALID_ASSIGNMENT_STRATEGIES:
            assert AssignmentStrategy.fromstr(name) is not None

    def test_an_unknown_strategy_still_raises(self):
        from potato.item_state_management import AssignmentStrategy

        with pytest.raises(ValueError, match="Unknown"):
            AssignmentStrategy.fromstr("not_a_strategy")


class TestBuiltinSlice:
    def test_the_false_negative_slice_ships_without_being_saved(self):
        from potato.curation.slices import SliceStore

        store = SliceStore()
        assert "model-found-nothing" in {s.name for s in store.list_all()}
        assert store.get("model-found-nothing") is not None

    def test_it_is_not_listed_as_something_the_project_saved(self):
        """
        `list()` means "what you saved". Including a slice nobody created
        would make delete on it a no-op and the UI's "your slices" a lie.
        """
        from potato.curation.slices import SliceStore

        store = SliceStore()
        assert store.list() == []
        assert store.is_builtin("model-found-nothing") is True

    def test_it_filters_on_the_derived_prediction_count(self):
        from potato.curation.slices import SliceStore

        slc = SliceStore().get("model-found-nothing")
        assert slc.metadata_filter == [{"field": "_n_predictions", "equals": 0}]

    def test_a_saved_slice_of_the_same_name_shadows_it(self):
        from potato.curation.slices import Slice, SliceStore

        store = SliceStore()
        store.save(Slice(name="model-found-nothing", query="mine"))
        matching = [s for s in store.list_all()
                    if s.name == "model-found-nothing"]
        assert len(matching) == 1
        assert matching[0].query == "mine"
        assert store.is_builtin("model-found-nothing") is False

    def test_the_filter_actually_selects_empty_items(self):
        from potato.curation.slices import SliceStore
        from potato.server_utils.conditions import matches_all

        slc = SliceStore().get("model-found-nothing")
        assert matches_all(slc.metadata_filter, {"_n_predictions": 0})
        assert not matches_all(slc.metadata_filter, {"_n_predictions": 3})
