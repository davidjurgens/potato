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
