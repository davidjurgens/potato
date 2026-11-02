"""``assignment_strategy: llm_confidence`` serves the model's doubtful items first.

It was in the enum, accepted by the validator and documented as a strategy,
and it assigned at random. It now reads the prelabels in item data, the ones
model-training write-back publishes, and serves the least confident first.
Unlike ``model_review`` it leaves nothing out: items with no prelabel come
last, so the study still finishes.
"""

import pytest

from potato.item_state_management import init_item_state_manager
from potato.user_state_management import InMemoryUserState

SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
            "description": "?", "labels": ["pos", "neg"]}]


def _manager(items, extra=None):
    import potato.item_state_management as mod

    mod.ITEM_STATE_MANAGER = None
    config = {"assignment_strategy": "llm_confidence",
              "max_annotations_per_item": -1,
              "annotation_schemes": SCHEMES}
    config.update(extra or {})
    ism = init_item_state_manager(config)
    ism.add_items(items)
    return ism


def _item(iid, confidence=None, field="predictions", predicted=True):
    data = {"id": iid, "text": "item %s" % iid}
    if predicted:
        payload = {"label": "pos"}
        if confidence is not None:
            payload["confidence"] = confidence
        data[field] = {"sentiment": payload}
    return data


def _served_order(ism, n):
    user = InMemoryUserState("u1", max_assignments=n)
    for _ in range(n + 2):
        ism.assign_instances_to_user(user)
    # The order the annotator sees; get_assigned_instance_ids() is a set.
    return list(user.instance_id_ordering)


def test_least_confident_first_then_unscored_then_unpredicted():
    items = {
        "a": _item("a", predicted=False),
        "b": _item("b", 0.9),
        "c": _item("c"),                 # a prelabel with no confidence
        "d": _item("d", 0.2),
        "e": _item("e", 0.55),
        "f": _item("f", predicted=False),
    }
    ism = _manager(items)
    assert _served_order(ism, 6) == ["d", "e", "b", "c", "a", "f"]


def test_it_is_not_random():
    """The old fallback shuffled with the seeded RNG; two seeds gave two
    orders. The ranking does not depend on the seed."""
    orders = set()
    for seed in (1, 2, 3):
        items = {str(i): _item(str(i), round(1 - i / 10, 2)) for i in range(8)}
        ism = _manager(items, {"random_seed": seed})
        orders.add(tuple(_served_order(ism, 8)))
    assert orders == {tuple(str(i) for i in reversed(range(8)))}


def test_a_new_prelabel_reorders_the_rest_of_the_queue():
    items = {"a": _item("a", 0.5), "b": _item("b", 0.6), "c": _item("c", 0.7)}
    ism = _manager(items)
    user = InMemoryUserState("u1", max_assignments=1)
    ism.assign_instances_to_user(user)
    assert user.instance_id_ordering == ["a"]

    ism.set_prediction("c", "sentiment", {"label": "neg", "confidence": 0.1})
    other = InMemoryUserState("u2", max_assignments=1)
    ism.assign_instances_to_user(other)
    assert other.instance_id_ordering == ["c"]


def test_items_with_no_prelabel_still_count_as_work():
    """model_review leaves these out; llm_confidence must not, or a study
    with partial predictions ends with items nobody was given."""
    ism = _manager({"a": _item("a", predicted=False)})
    user = InMemoryUserState("u1", max_assignments=5)
    assert ism.has_unlabeled_items_for_user(user)
    assert _served_order(ism, 5) == ["a"]


def test_reads_the_write_back_field():
    """With write-back publishing to another field and no pre_annotation
    block, the field the annotation page reads is the write-back one."""
    items = {"a": _item("a", 0.9, field="model_out"),
             "b": _item("b", 0.1, field="model_out")}
    ism = _manager(items, {"model_training": {
        "enabled": True,
        "writeback": {"schemas": ["sentiment"], "field": "model_out"}}})
    assert _served_order(ism, 2) == ["b", "a"]


@pytest.mark.parametrize("config, expected", [
    ({}, "predictions"),
    ({"pre_annotation": {"enabled": True, "field": "pre"}}, "pre"),
    ({"model_training": {"enabled": True,
                         "writeback": {"schemas": ["s"], "field": "wb"}}}, "wb"),
    # An enabled pre_annotation block wins, as it does on the annotation page.
    ({"pre_annotation": {"enabled": True, "field": "pre"},
      "model_training": {"enabled": True,
                         "writeback": {"schemas": ["s"], "field": "wb"}}}, "pre"),
    # Write-back that publishes nothing does not move the field.
    ({"model_training": {"enabled": True, "writeback": {"field": "wb"}}},
     "predictions"),
])
def test_prediction_field_matches_the_annotation_page(config, expected):
    from potato.model_review import prediction_field
    from potato.quality_control import QualityControlManager

    assert prediction_field(config) == expected
    qc = QualityControlManager(dict(config, annotation_schemes=SCHEMES), ".")
    if qc.qc_config.pre_annotation_enabled:
        assert qc.qc_config.pre_annotation_field == expected


def test_the_review_queue_reads_the_write_back_field():
    """The model-review report read pre_annotation.field alone, so with
    write-back publishing to another field its queue was empty while
    annotators saw the prelabels."""
    from potato import model_review

    config = {"annotation_schemes": SCHEMES, "task_dir": ".",
              "model_training": {"enabled": True, "writeback": {
                  "schemas": ["sentiment"], "field": "model_out"}}}
    items = {"a": _item("a", 0.9, field="model_out"),
             "b": _item("b", 0.1, field="model_out")}
    ism = _manager(items, config)
    report = model_review.summarize_project(ism, config)
    assert report["queue"] == ["b", "a"]
    assert report["n_prelabelled"] == 2


def test_a_nan_confidence_counts_as_no_confidence():
    # pandas and json.dumps both write NaN. It compares false with
    # everything, so left in, one NaN scrambles the whole sort (audit 99
    # served 0.1, 0.2, 0.9, NaN, 0.2, 0.5, ...).
    nan = float("nan")
    items = {"i01": _item("i01", 0.9), "i02": _item("i02", 0.2),
             "i06": _item("i06", nan), "i08": _item("i08", 0.25),
             "i10": _item("i10", 0.1), "i12": _item("i12", 0.95),
             "i13": _item("i13", 0.5), "i14": _item("i14", nan),
             "i15": _item("i15", "0.05")}  # a string, as a CSV gives it
    ism = _manager(items)
    assert _served_order(ism, 9) == ["i15", "i10", "i02", "i08", "i13",
                                     "i01", "i12", "i06", "i14"]


def test_the_review_queue_ignores_nan_too():
    from potato.model_review import review_order, summarize_predictions
    nan = float("nan")
    summaries = [summarize_predictions(iid, {"predictions": {"sentiment": {
        "label": "pos", "confidence": c}}}, "predictions", ["sentiment"])
        for iid, c in (("a", 0.9), ("b", nan), ("c", 0.3), ("d", 0.6))]
    assert review_order(summaries) == ["c", "d", "a", "b"]
