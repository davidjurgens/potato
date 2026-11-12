"""Held-out metrics for the structured kinds, against values worked by hand."""

import pytest

from potato.training import structured_metrics as sm
from potato.training.evaluation import score_split


def _spans(*offsets):
    return [{"start": s, "end": e, "label": lab} for s, e, lab in offsets]


def test_coreference_scores_match_the_worked_example():
    # Mentions a..e. Key {a,b,c} {d,e}; response {a,b} {c,d,e}.
    spans = _spans((0, 1, "M"), (2, 3, "M"), (4, 5, "M"), (6, 7, "M"), (8, 9, "M"))
    key = {"spans": spans, "clusters": [{"type": "P", "spans": [0, 1, 2]},
                                        {"type": "P", "spans": [3, 4]}]}
    response = {"spans": spans, "clusters": [{"type": "P", "spans": [0, 1]},
                                             {"type": "P", "spans": [2, 3, 4]}]}
    scores = sm.score_coreference([key], [response])
    assert scores["muc_f1"] == pytest.approx(2 / 3)
    assert scores["b3_f1"] == pytest.approx(11 / 15)
    assert scores["ceafe_f1"] == pytest.approx(0.8)
    assert scores["conll_f1"] == pytest.approx((2 / 3 + 11 / 15 + 0.8) / 3)
    assert sm.score_coreference([key], [key])["conll_f1"] == pytest.approx(1.0)


def test_a_mention_in_no_chain_is_a_singleton():
    spans = _spans((0, 1, "M"), (2, 3, "M"))
    gold = {"spans": spans, "clusters": []}
    merged = {"spans": spans, "clusters": [{"type": "P", "spans": [0, 1]}]}
    scores = sm.score_coreference([gold], [merged])
    # Two singletons against one pair: B-cubed precision 1/2, recall 1.
    assert scores["b3_f1"] == pytest.approx(2 / 3)


def test_hungarian_finds_the_cheapest_assignment():
    cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
    pairs = sorted(sm.hungarian(cost))
    assert sum(cost[i][j] for i, j in pairs) == 5
    assert len(sm.hungarian([[1, 2, 3]])) == 1
    assert sorted(sm.hungarian([[1], [0], [5]])) == [(1, 0)]


def test_relation_scores_compare_offsets_not_positions():
    gold = {"spans": _spans((0, 5, "PER"), (13, 17, "ORG")),
            "links": [{"type": "WORKS_FOR", "spans": [0, 1], "directed": True}]}
    # Same spans in another order, so the positions differ.
    same = {"spans": _spans((13, 17, "ORG"), (0, 5, "PER")),
            "links": [{"type": "WORKS_FOR", "spans": [1, 0], "directed": True}]}
    reversed_link = {"spans": gold["spans"],
                     "links": [{"type": "WORKS_FOR", "spans": [1, 0], "directed": True}]}
    assert sm.score_relations([gold], [same])["f1"] == 1.0
    # Two spans and one link is a tree; with an unlinked item beside it the
    # scheme is not a parse, and reports no UAS.
    unlinked = {"spans": gold["spans"], "links": []}
    assert "uas" not in sm.score_relations([gold, unlinked], [same, unlinked])
    assert sm.score_relations([gold], [reversed_link])["f1"] == 0.0
    assert sm.score_relations([gold], [None])["recall"] == 0.0


def test_dependency_trees_get_uas_and_las():
    tokens = _spans((0, 3, "W"), (4, 8, "W"), (9, 12, "W"))     # "The cat sat"
    gold = {"spans": tokens, "links": [
        {"type": "det", "spans": [1, 0], "directed": True},
        {"type": "nsubj", "spans": [2, 1], "directed": True}]}
    guess = {"spans": tokens, "links": [
        {"type": "det", "spans": [1, 0], "directed": True},
        {"type": "obj", "spans": [2, 1], "directed": True}]}
    scores = sm.score_relations([gold], [guess])
    # Three tokens: "sat" is the root (no head, none predicted), both heads
    # right, one label wrong.
    assert scores["uas"] == 1.0
    assert scores["las"] == pytest.approx(2 / 3)


def test_event_scores():
    spans = _spans((0, 5, "PER"), (6, 12, "TRIGGER"), (13, 17, "ORG"))
    gold = {"spans": spans, "events": [{"type": "HIRE", "trigger": 1, "arguments": [
        {"role": "employee", "span": 0}, {"role": "org", "span": 2}]}]}
    guess = {"spans": spans, "events": [{"type": "HIRE", "trigger": 1, "arguments": [
        {"role": "employee", "span": 0}]}]}
    scores = sm.score_events([gold], [guess])
    assert scores["trigger_f1"] == 1.0
    assert scores["argument_precision"] == 1.0
    assert scores["argument_recall"] == 0.5


def test_ranking_scores():
    gold = [["a", "b", "c"]]
    assert sm.score_rankings(gold, [{"order": ["a", "b", "c"]}])["kendall_tau"] == 1.0
    worst = sm.score_rankings(gold, [{"order": ["c", "b", "a"]}])
    assert worst["kendall_tau"] == -1.0 and worst["top1_accuracy"] == 0.0
    one_swap = sm.score_rankings(gold, [["b", "a", "c"]])
    assert one_swap["kendall_tau"] == pytest.approx(1 / 3)
    assert one_swap["pairwise_accuracy"] == pytest.approx(2 / 3)
    assert sm.score_rankings(gold, [None])["kendall_tau"] == -1.0


def test_bws_and_scale_scores():
    gold = [{"best": "A", "worst": "C"}, {"best": "B", "worst": "A"}]
    scores = sm.score_bws(gold, [{"best": "A", "worst": "C"}, {"best": "C", "worst": "A"}])
    assert scores == {"best_accuracy": 0.5, "worst_accuracy": 1.0,
                      "best_worst_accuracy": 0.75}
    scale = sm.score_scale_preferences([-2.0, 1.0, 0.0], [{"value": -0.5}, -1.0, 0.4])
    assert scale["direction_accuracy"] == 0.5     # the zero is not scored
    assert scale["mae"] == pytest.approx((1.5 + 2.0 + 0.4) / 3)


def test_distribution_scores():
    same = sm.score_distributions([{"a": 0.5, "b": 0.5}], [{"a": 0.5, "b": 0.5}])
    assert same["distribution_agreement"] == pytest.approx(1.0)
    disjoint = sm.score_distributions([{"a": 1.0}], [{"b": 1.0}])
    assert disjoint["jsd"] == pytest.approx(1.0)
    assert disjoint["argmax_accuracy"] == 0.0
    assert sm.score_distributions([{"a": 1.0}], [None])["jsd"] == 1.0


def test_soft_label_scores_and_ece():
    soft = [{"pos": 0.5, "neg": 0.5}, {"pos": 1.0}]
    predicted = [{"label": "pos", "probabilities": {"pos": 0.5, "neg": 0.5}},
                 {"label": "pos", "probabilities": {"pos": 0.9, "neg": 0.1}}]
    scores = sm.soft_label_scores(soft, predicted, ["pos", "pos"])
    assert scores["soft_jsd"] == pytest.approx(sm._jsd({"pos": 1.0}, {"pos": 0.9, "neg": 0.1}) / 2)
    # Two buckets, each right: |0.5 - 1| and |0.9 - 1|, weighted equally.
    assert scores["ece"] == pytest.approx((0.5 + 0.1) / 2)
    assert sm.soft_label_scores(soft, [{"label": "pos"}] * 2, ["pos", "pos"]) == {}


def test_gloss_and_tree_scores():
    gold = {"words": [{"word": "kitabım", "gloss": "book-1SG.POSS"},
                      {"word": "ev", "gloss": "house"}]}
    guess = {"words": [{"gloss": "book-POSS"}, {"gloss": "house"}]}
    scores = sm.score_glosses([gold], [guess])
    assert scores["word_accuracy"] == 0.5
    assert scores["morpheme_accuracy"] == pytest.approx(2 / 3)

    tree = {"path": ["root", "r2"], "nodes": {"r1": {"q": "4"}, "r2": {"q": "2"}}}
    guess = {"path": ["root", "r2"], "nodes": {"r1": {"q": "4"}, "r2": {"q": "3"}}}
    scores = sm.score_trees([tree], [guess])
    assert scores["node_accuracy"] == 0.5 and scores["path_accuracy"] == 1.0


def test_score_split_routes_the_new_kinds_and_their_headlines():
    rows = [{"instance_id": "1", "targets": {"r": ["a", "b", "c"]}}]
    metrics, n = score_split(rows, {("1", "r"): {"order": ["a", "b", "c"]}},
                             "r", "ranking")
    assert n == 1 and metrics["kendall_tau"] == 1.0 and metrics["coverage"] == 1.0
    rows = [{"instance_id": "1", "targets": {"s": "pos"},
             "soft_targets": {"s": {"pos": 1.0}}}]
    metrics, _ = score_split(
        rows, {("1", "s"): {"label": "pos", "probabilities": {"pos": 0.8, "neg": 0.2}}},
        "s", "nominal")
    assert metrics["accuracy"] == 1.0 and metrics["ece"] == pytest.approx(0.2)


def test_a_tie_in_the_gold_ranking_is_not_scored():
    from potato.training.structured_metrics import score_rankings
    # Annotators tied a and b; either order of them is right.
    for order in (["a", "b", "c"], ["b", "a", "c"]):
        scores = score_rankings([["a=b", "c"]], [{"order": order}])
        assert scores["kendall_tau"] == 1.0 and scores["top1_accuracy"] == 1.0
    assert score_rankings([["a=b", "c"]], [{"order": ["c", "a", "b"]}])["kendall_tau"] == -1.0


def test_uas_comes_from_the_training_answers_not_the_split():
    """A held-out split of 2-span, 1-link items is all trees by chance; the
    run decoded pairs because its training answers were not trees, and
    reported UAS anyway."""
    import types
    from potato.training.evaluation import score_predictions
    linked = {"spans": _spans((0, 5, "PER"), (13, 17, "ORG")),
              "links": [{"type": "WORKS_FOR", "spans": [0, 1], "directed": True}]}
    unlinked = dict(linked, links=[])

    def bundle(train):
        rows = {"train": [{"instance_id": str(n), "targets": {"r": t}}
                          for n, t in enumerate(train)],
                "test": [{"instance_id": "t", "targets": {"r": linked}}]}
        return types.SimpleNamespace(read_split=lambda split: iter(rows.get(split, [])))

    schema = types.SimpleNamespace(name="r", kind="relation")
    predictions = {("t", "r"): linked}
    assert "test_uas" not in score_predictions(bundle([linked, unlinked]), predictions,
                                               [schema], splits=("test",))
    assert score_predictions(bundle([linked, linked]), predictions,
                             [schema], splits=("test",))["test_uas"] == 1.0
