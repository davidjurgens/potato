"""The reliability export: alpha per question at the right level, a seeded
bootstrap interval, percent agreement, and only multiply-coded units."""

import csv
import os

import pytest

from potato.export.base import ExportContext
from potato.export.reliability_exporter import ReliabilityExporter
from potato.server_utils.iaa.alpha import krippendorff_alpha
from tests.helpers.test_utils import create_test_directory

SCHEMES = [{"name": "topic", "annotation_type": "radio", "labels": ["a", "b", "c"]},
           {"name": "tone", "annotation_type": "likert", "size": 5}]


def _ann(user, item, topic, tone):
    return {"user_id": user, "instance_id": item,
            "labels": {"topic": {topic: topic}, "tone": {"scale": str(tone)}}}


def _ctx(out):
    anns = []
    topics = ["a", "b", "c", "a", "b", "c", "a", "b"]
    for i, t in enumerate(topics):
        anns.append(_ann("x", f"i{i}", t, i % 5 + 1))
        anns.append(_ann("y", f"i{i}", t if i != 3 else "c", i % 5 + 1))
    anns.append(_ann("x", "solo", "a", 1))     # coded once: not a unit
    return ExportContext(config={}, annotations=anns, items={}, schemas=SCHEMES, output_dir=out)


def test_table():
    out = create_test_directory("reliability_export")
    res = ReliabilityExporter().export(_ctx(out), out, {"bootstrap": 200})
    assert res.success
    rows = {r["schema"]: r for r in csv.DictReader(open(os.path.join(out, "reliability.csv")))}
    t = rows["topic"]
    assert t["level"] == "nominal" and t["units"] == "8" and t["coders"] == "2"
    assert float(t["percent_agreement"]) == pytest.approx(87.5)
    long = []
    for i, top in enumerate(["a", "b", "c", "a", "b", "c", "a", "b"]):
        long += [("x", f"i{i}", top), ("y", f"i{i}", top if i != 3 else "c")]
    assert float(t["alpha"]) == pytest.approx(round(krippendorff_alpha(long, "nominal"), 3))
    assert float(t["ci95_low"]) <= float(t["alpha"]) <= float(t["ci95_high"])
    assert rows["tone"]["level"] == "ordinal" and float(rows["tone"]["alpha"]) == pytest.approx(1.0)
    md = open(os.path.join(out, "reliability.md")).read()
    assert "| topic | nominal |" in md


def test_bootstrap_is_reproducible():
    a = create_test_directory("reliability_seed_a")
    b = create_test_directory("reliability_seed_b")
    ReliabilityExporter().export(_ctx(a), a, {"bootstrap": 100})
    ReliabilityExporter().export(_ctx(b), b, {"bootstrap": 100})
    assert open(os.path.join(a, "reliability.csv")).read() == open(os.path.join(b, "reliability.csv")).read()


def test_hierarchical_multiselect_is_scored_as_sets():
    """A codebook question (hierarchical_multiselect) stores one comma-joined
    value; the table must score it, at the MASI level."""
    import csv
    import os
    from potato.export.base import ExportContext
    from potato.export.reliability_exporter import ReliabilityExporter
    from tests.helpers.test_utils import create_test_directory
    scheme = {"annotation_type": "hierarchical_multiselect", "name": "topic"}
    codes = {("i1", "a"): "Taxes", ("i1", "b"): "Taxes", ("i2", "a"): "Climate,Taxes",
             ("i2", "b"): "Taxes,Climate", ("i3", "a"): "Hospitals", ("i3", "b"): "Pollution"}
    anns = [{"instance_id": i, "user_id": u, "labels": {"topic": {"selected_labels": v}}}
            for (i, u), v in codes.items()]
    out = create_test_directory("reliability_hier")
    ctx = ExportContext(config={}, annotations=anns, items={}, schemas=[scheme], output_dir=out)
    assert ReliabilityExporter().export(ctx, out, {"bootstrap": 0}).success
    row = next(csv.DictReader(open(os.path.join(out, "reliability.csv"))))
    assert row["level"] == "masi" and row["units"] == "3"
    # Order inside the stored value does not matter: i2 agrees.
    assert float(row["percent_agreement"]) == pytest.approx(200 / 3, abs=0.01)


def test_degenerate_resamples_are_counted_not_logged(caplog):
    """potato-skill, 2.12.0 pack notes (P5): a 3-item study logged about 300
    "krippendorff_alpha failed: float division by zero" warnings, one per
    resample whose values happened to be all the same."""
    import logging
    out = create_test_directory("reliability_degenerate")
    anns = []
    for i, t in enumerate(["a", "a", "b"]):
        anns.append(_ann("x", f"i{i}", t, 1))
        anns.append(_ann("y", f"i{i}", t if i else "b", 1))
    ctx = ExportContext(config={}, annotations=anns, items={}, schemas=SCHEMES[:1], output_dir=out)
    with caplog.at_level(logging.WARNING):
        res = ReliabilityExporter().export(ctx, out, {"bootstrap": 300})
    assert res.success
    assert not [r for r in caplog.records if "krippendorff_alpha failed" in r.getMessage()]
    assert len(res.warnings) == 1 and "undefined (no variation)" in res.warnings[0]
    assert "bootstrap resamples" in open(os.path.join(out, "reliability.md")).read()


# -- span schemes --------------------------------------------------------------
# A QDA project coded only by highlighting used to get no rows at all.

SPAN = [{"name": "codes", "annotation_type": "span", "labels": ["joy", "fear"]}]
TEXTS = {"d1": "I was happy, then scared.", "d2": "Nothing happened here.",
         "d3": "Fear and joy together."}


def _span_ann(user, item, spans):
    return {"user_id": user, "instance_id": item, "labels": {},
            "spans": {"codes": [{"start": s, "end": e, "name": n} for s, e, n in spans]}}


def _span_ctx(out, anns):
    items = {k: {"id": k, "text": v} for k, v in TEXTS.items()}
    return ExportContext(config={"item_properties": {"text_key": "text"}}, annotations=anns,
                         items=items, schemas=SPAN, output_dir=out)


SPAN_ANNS = [
    _span_ann("x", "d1", [(6, 11, "joy"), (18, 24, "fear")]),
    _span_ann("y", "d1", [(6, 11, "joy"), (17, 24, "fear")]),     # one character wider
    _span_ann("x", "d2", []),                                     # read, marked nothing
    _span_ann("y", "d2", [(0, 7, "fear")]),
    _span_ann("x", "d3", [(0, 4, "fear"), (9, 12, "joy")]),
    _span_ann("y", "d3", [(0, 4, "fear"), (9, 12, "fear")]),     # same place, other code
    _span_ann("x", "solo", [(0, 3, "joy")]),                      # one coder: not a unit
]


def _reference_alpha(anns):
    """Long-format nominal alpha with one unit per (item, character)."""
    from potato.server_utils.iaa.span import spans_to_bio
    long = []
    for a in anns:
        if a["instance_id"] not in TEXTS:
            continue
        spans = [(s["start"], s["end"], s["name"]) for s in a["spans"]["codes"]]
        for pos, tag in enumerate(spans_to_bio(spans, len(TEXTS[a["instance_id"]]))):
            long.append((a["user_id"], f"{a['instance_id']}#{pos}",
                         "O" if tag == "O" else tag.split("-", 1)[1]))
    return krippendorff_alpha(long, "nominal")


def test_span_schemes_get_a_positional_row():
    out = create_test_directory("reliability_span")
    res = ReliabilityExporter().export(_span_ctx(out, SPAN_ANNS), out, {"bootstrap": 200})
    assert res.success
    row = {r["schema"]: r for r in csv.DictReader(open(os.path.join(out, "reliability.csv")))}["codes"]
    assert row["level"] == "positional"
    assert row["units"] == "3" and row["coders"] == "2"
    assert float(row["alpha"]) == pytest.approx(round(_reference_alpha(SPAN_ANNS), 3))
    assert float(row["ci95_low"]) <= float(row["alpha"]) <= float(row["ci95_high"])
    chars = sum(len(t) for t in TEXTS.values())
    assert row["pairable_values"] == str(2 * chars)
    # Disagreeing positions: 1 (d1 boundary) + 7 (d2) + 3 (d3 code).
    assert float(row["percent_agreement"]) == pytest.approx(round(100 * (chars - 11) / chars, 3))
    assert "| codes | positional |" in open(os.path.join(out, "reliability.md")).read()


def test_one_item_matches_the_per_item_coefficient():
    from potato.export.reliability_exporter import (
        _alpha_from_coincidences, _span_coincidences)
    from potato.server_utils.iaa.span import positional_alpha
    spans = {"x": [(6, 11, "joy"), (18, 24, "fear")], "y": [(6, 11, "joy"), (17, 24, "fear")]}
    table = _span_coincidences({"length": len(TEXTS["d1"]), "coders": spans})[0]
    assert _alpha_from_coincidences(table) == pytest.approx(
        positional_alpha(spans, len(TEXTS["d1"])))


def test_span_spans_on_another_field_are_their_own_unit():
    out = create_test_directory("reliability_span_fields")
    anns = [
        {"user_id": u, "instance_id": "d1", "labels": {}, "spans": {"codes": [
            {"start": 0, "end": 3, "name": "joy", "target_field": "title"},
            {"start": 6, "end": 11, "name": "joy"}]}}
        for u in ("x", "y")]
    ctx = _span_ctx(out, anns)
    ctx.items["d1"]["title"] = "Joy!"
    ReliabilityExporter().export(ctx, out, {"bootstrap": 0})
    row = next(csv.DictReader(open(os.path.join(out, "reliability.csv"))))
    assert row["units"] == "2"
    assert row["pairable_values"] == str(2 * (len("Joy!") + len(TEXTS["d1"])))


def test_a_span_past_the_text_is_named():
    out = create_test_directory("reliability_span_past")
    too_long = len(TEXTS["d1"]) + 5
    anns = [{"user_id": u, "instance_id": "d1", "labels": {}, "spans": {"codes": [
        {"start": 6, "end": too_long if u == "x" else 11, "name": "joy"}]}} for u in ("x", "y")]
    res = ReliabilityExporter().export(_span_ctx(out, anns), out, {"bootstrap": 0})
    (note,) = [w for w in res.warnings if "past the" in w]
    assert note.startswith("codes: 1 span(s)") and "d1" in note
    clean = ReliabilityExporter().export(_span_ctx(out, SPAN_ANNS), out, {"bootstrap": 0})
    assert not any("past the" in w for w in clean.warnings)
