"""
Published gold: machine raters stay out of the vote, adjudication wins, and
labeling-engine labels arrive with their source.
"""

from potato.publish.bundle import build_gold_rows


def _ann(user, iid, label, origin=None):
    a = {"instance_id": iid, "user_id": user, "labels": {"s": {label: True}}}
    if origin:
        a["_origin"] = origin
    return a


def test_excluded_raters_do_not_vote():
    anns = [_ann("alice", "i1", "pos"), _ann("tool1", "i1", "neg"),
            _ann("tool2", "i1", "neg")]
    [row] = build_gold_rows(anns, schemas=[{"name": "s", "annotation_type": "radio"}],
                            exclude_users={"tool1", "tool2"})
    assert row["s"] == "pos" and row["n_annotators"] == 1


def test_overrides_win_and_are_labeled():
    anns = [_ann("alice", "i1", "pos"), _ann("bob", "i1", "pos")]
    rows = build_gold_rows(anns, schemas=[{"name": "s", "annotation_type": "radio"}],
                           overrides={"i1": {"s": ("neg", "adjudicated")},
                                      "i2": {"s": ("pos", "machine (certified)")}})
    by = {r["instance_id"]: r for r in rows}
    assert by["i1"]["s"] == "neg" and by["i1"]["gold_source"] == {"s": "adjudicated"}
    # An item no person labeled appears with the engine's certified label.
    assert by["i2"]["s"] == "pos" and by["i2"]["n_annotators"] == 0
    assert by["i2"]["gold_source"] == {"s": "machine (certified)"}


def test_plain_studies_are_unchanged():
    anns = [_ann("alice", "i1", "pos"), _ann("bob", "i1", "pos"), _ann("cat", "i1", "neg")]
    [row] = build_gold_rows(anns, schemas=[{"name": "s", "annotation_type": "radio"}])
    assert row["s"] == "pos" and "gold_source" not in row
