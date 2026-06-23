"""Unit tests for cross-annotator annotation aggregation."""

from potato.eval_datasets.annotation_aggregation import aggregate_instance_annotations


def _fake_getter(store):
    """store: {(user, iid): {scheme: {label: value}}}"""
    return lambda user, iid: store.get((user, iid), {})


def test_majority_vote_single_scheme():
    store = {
        ("u1", "i1"): {"sentiment": {"positive": True}},
        ("u2", "i1"): {"sentiment": {"positive": True}},
        ("u3", "i1"): {"sentiment": {"negative": True}},
    }
    ref, meta = aggregate_instance_annotations("i1", ["u1", "u2", "u3"], _fake_getter(store))
    assert ref == {"sentiment": {"positive": True}}
    assert meta["num_annotators"] == 3
    assert meta["votes"]["sentiment"]["winner_votes"] == 2
    assert meta["votes"]["sentiment"]["total"] == 3
    assert meta["votes"]["sentiment"]["agreement"] == round(2 / 3, 4)


def test_unanimous_agreement_is_one():
    store = {
        ("u1", "i1"): {"q": {"yes": True}},
        ("u2", "i1"): {"q": {"yes": True}},
    }
    ref, meta = aggregate_instance_annotations("i1", ["u1", "u2"], _fake_getter(store))
    assert ref == {"q": {"yes": True}}
    assert meta["votes"]["q"]["agreement"] == 1.0


def test_no_annotations_returns_none():
    ref, meta = aggregate_instance_annotations("i1", ["u1"], _fake_getter({}))
    assert ref is None
    assert meta["num_annotators"] == 0


def test_multiple_schemes_aggregated_independently():
    store = {
        ("u1", "i1"): {"a": {"x": True}, "b": {"p": True}},
        ("u2", "i1"): {"a": {"x": True}, "b": {"q": True}},
    }
    ref, meta = aggregate_instance_annotations("i1", ["u1", "u2"], _fake_getter(store))
    assert ref["a"] == {"x": True}        # unanimous
    assert ref["b"] in ({"p": True}, {"q": True})  # tie -> first seen
    assert meta["votes"]["a"]["agreement"] == 1.0
    assert meta["votes"]["b"]["winner_votes"] == 1


def test_non_dict_value_wrapped():
    store = {("u1", "i1"): {"rating": 4}}
    ref, meta = aggregate_instance_annotations("i1", ["u1"], _fake_getter(store))
    assert ref == {"rating": {"_value": 4}}
