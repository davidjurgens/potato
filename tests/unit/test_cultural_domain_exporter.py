"""
The ``cultural_domain`` exporter on records shaped the way Potato stores
them: hidden-input JSON under ``labels[schema][schema]`` on items, and
``phase_responses`` rows for phase pages (radio: label name = value = the
option).
"""

import csv
import json
import os

import pytest

from potato.export.base import ExportContext
from potato.export.cultural_domain_exporter import CulturalDomainExporter
from potato.export.registry import export_registry
from tests.helpers.test_utils import create_test_directory


def _blob(name, value):
    return {name: {name: json.dumps(value)}}


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _matrix(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[0][1:]
    return {(r[0], c): r[k + 1] for r in rows[1:] for k, c in enumerate(header)}


@pytest.fixture
def context(tmp_path):
    (tmp_path / "syn.csv").write_text("variant,canonical\napples,apple\n")
    config = {"task_dir": str(tmp_path),
              "phases": {"order": ["pre", "annotation", "post"],
                         "pre": {"type": "prestudy", "annotation_schemes": [
                             {"annotation_type": "free_list", "name": "fruit", "description": "d",
                              "normalize": True}]},
                         "post": {"type": "poststudy", "annotation_schemes": [
                             {"annotation_type": "radio", "name": f"q{k}", "description": "d",
                              "labels": ["True", "False"]} for k in range(6)]}}}
    schemas = [
        {"annotation_type": "card_sort", "name": "piles", "description": "d", "mode": "open",
         "items_field": "items"},
        {"annotation_type": "triad_test", "name": "triads", "description": "d", "items_field": "items"},
        {"annotation_type": "multiselect", "name": "multi", "description": "d", "labels": ["a", "b"]},
    ]
    items = {"set1": {"id": "set1", "items": ["apple", "lemon", "lime", "pear"]}}
    piles = {"u1": {"sweet": ["apple", "pear"], "sour": ["lemon", "lime"]},
             "u2": {"one": ["apple", "pear", "lemon"], "two": ["lime"]}}
    triads = {"u1": [["apple", "lemon", "lime", "apple"], ["pear", "apple", "lime", "lime"]],
              "u2": [["lime", "apple", "lemon", "apple"], ["pear", "apple", "lime", None]]}
    annotations = []
    for u in ("u1", "u2"):
        labels = {}
        labels.update(_blob("piles", piles[u]))
        labels.update(_blob("triads", {"design": "sample", "triads": triads[u]}))
        annotations.append({"user_id": u, "instance_id": "set1", "labels": labels})
    lists = {"u1": ["Apples", "banana", "apple"], "u2": ["banana", " Apple"], "u3": ["apple", "date"]}
    phase = []
    for u, lst in lists.items():
        phase.append({"user_id": u, "phase": "pre", "page": "pre", "schema": "fruit",
                      "label_name": "fruit",
                      "value": json.dumps({"items": lst, "timings_ms": [1000 * (k + 1) for k in range(len(lst))]})})
    # Consensus: u1-u3 answer True to everything, u4 the opposite.
    for u in ("u1", "u2", "u3", "u4"):
        for k in range(6):
            ans = "True" if (u != "u4") == (k != 5) else "False"
            phase.append({"user_id": u, "phase": "post", "page": "post", "schema": f"q{k}",
                          "label_name": ans, "value": ans})
    return ExportContext(config=config, annotations=annotations, items=items, schemas=schemas,
                         output_dir=str(tmp_path), phase_responses=phase)


def test_registered_and_exportable(context):
    assert "cultural_domain" in export_registry.get_supported_formats()
    ok, reason = CulturalDomainExporter().can_export(context)
    assert ok, reason


def test_free_lists_normalized_with_synonyms(context):
    out = create_test_directory("cultural_domain_export_fl")
    result = CulturalDomainExporter().export(context, out, {"synonyms": "syn.csv"})
    assert result.success, result.errors
    rows = _read(os.path.join(out, "freelist_items.csv"))
    u1 = [(r["item"], r["typed"], r["rank"], r["list_length"], r["time_ms"]) for r in rows if r["user_id"] == "u1"]
    # "apple" repeats "Apples" once mapped; the repeat is dropped.
    assert u1 == [("apple", "Apples", "1", "2", "1000"), ("banana", "banana", "2", "2", "2000")]
    sal = {r["item"]: r for r in _read(os.path.join(out, "salience.csv"))}
    # apple: ranks 1, 2, 1 in lists of 2, 2, 2 -> S = (1 + 1/2 + 1)/3
    assert float(sal["apple"]["smith_s"]) == pytest.approx(2.5 / 3, abs=1e-6)
    assert sal["apple"]["frequency"] == "3" and sal["apple"]["n_lists"] == "3"
    assert float(sal["apple"]["sutrop_csi"]) == pytest.approx(3 / (3 * 4 / 3), abs=1e-6)


def test_normalize_option_overrides_the_scheme(context):
    out = create_test_directory("cultural_domain_export_raw")
    CulturalDomainExporter().export(context, out, {"normalize": "false"})
    items = {r["item"] for r in _read(os.path.join(out, "salience.csv"))}
    assert {"Apples", "apple", " Apple"} <= items


def test_pile_sort_and_triad_matrices(context):
    out = create_test_directory("cultural_domain_export_mats")
    CulturalDomainExporter().export(context, out, {})
    co = _matrix(os.path.join(out, "pilesort_cooccurrence_piles_set1.csv"))
    assert float(co[("apple", "pear")]) == 1.0
    assert float(co[("lemon", "lime")]) == 0.5
    assert float(co[("apple", "lemon")]) == 0.5
    inf = _matrix(os.path.join(out, "pilesort_informants_piles_set1.csv"))
    assert float(inf[("u1", "u2")]) == pytest.approx(0.5)
    pairs = _read(os.path.join(out, "pilesort_pairs.csv"))
    assert len(pairs) == 2 * 6
    sim = _matrix(os.path.join(out, "triads_similarity_triads_set1.csv"))
    # lemon-lime left together twice in the two triads holding both.
    assert float(sim[("lemon", "lime")]) == 1.0
    # apple-pear: shown together once (u1's 2nd triad), odd was lime -> similar.
    assert float(sim[("apple", "pear")]) == 1.0
    assert float(sim[("apple", "lime")]) == 0.0
    answered = _read(os.path.join(out, "triads_answers.csv"))
    assert len(answered) == 3          # the unanswered triad is left out


def test_consensus_files(context):
    out = create_test_directory("cultural_domain_export_cc")
    result = CulturalDomainExporter().export(
        context, out, {"consensus_schemes": "q0,q1,q2,q3,q4,q5,multi"})
    inf = {r["user_id"]: r for r in _read(os.path.join(out, "consensus_informants.csv"))}
    assert set(inf) == {"u1", "u2", "u3", "u4"}
    assert inf["u4"]["negative"] == "1" and float(inf["u4"]["competence"]) < 0
    assert all(float(inf[u]["competence"]) > 0.5 for u in ("u1", "u2", "u3"))
    answers = {r["question"]: r for r in _read(os.path.join(out, "consensus_answers.csv"))}
    assert answers["q0"]["answer"] == "True" and answers["q5"]["answer"] == "False"
    assert answers["q0"]["n_options"] == "2"
    with open(os.path.join(out, "consensus_summary.json")) as f:
        summary = json.load(f)
    assert summary["n_informants"] == 4 and summary["n_questions"] == 6
    assert summary["negative_competence"] == ["u4"]
    assert "rule of thumb" in summary["ratio_rule_of_thumb"]
    assert any("multi is a multiselect" in w for w in result.warnings)


@pytest.mark.parametrize("max_items, limit", [(None, None), (4, 4)])
def test_a_list_longer_than_the_page_allows_is_cut_and_warned(context, max_items, limit):
    from potato.server_utils.schemas.free_list import MAX_ITEM_LENGTH, MAX_LIST_ITEMS
    limit = limit or MAX_LIST_ITEMS
    fruit = context.config["phases"]["pre"]["annotation_schemes"][0]
    if max_items:
        fruit["max_items"] = max_items
    long_list = ["x" * 5000] + [f"fruit{k}" for k in range(1, 500)]
    context.phase_responses.append({"user_id": "u9", "phase": "pre", "page": "pre", "schema": "fruit",
                                    "label_name": "fruit", "value": json.dumps({"items": long_list})})
    out = create_test_directory("cultural_domain_export_long")
    result = CulturalDomainExporter().export(context, out)
    rows = [r for r in _read(os.path.join(out, "freelist_items.csv")) if r["user_id"] == "u9"]
    assert len(rows) == limit and rows[-1]["item"] == f"fruit{limit - 1}"
    assert len(rows[0]["typed"]) == MAX_ITEM_LENGTH
    assert any(f"more than {limit} items" in w for w in result.warnings), result.warnings



# Pre-release: the exporter said it could export any project with a radio,
# select or likert question, then wrote nothing and reported success.

def _radio_only(tmp_path, with_answers=True):
    schemas = [{"annotation_type": "radio", "name": f"q{k}", "description": "d",
                "labels": ["True", "False"]} for k in range(4)]
    anns = []
    if with_answers:
        for u in ("u1", "u2", "u3"):
            anns.append({"user_id": u, "instance_id": "i1",
                         "labels": {f"q{k}": {"True": "True"} for k in range(4)}})
    return ExportContext(config={"task_dir": str(tmp_path)}, annotations=anns, items={},
                         schemas=schemas, output_dir=str(tmp_path))


def test_radio_only_project_without_consensus_schemes_fails_clearly(tmp_path):
    context = _radio_only(tmp_path)
    out = create_test_directory("cultural_domain_export_radio_only")
    result = export_registry.export("cultural_domain", context, out, {})
    assert not result.success and not result.files_written
    assert any("consensus_schemes" in e for e in result.errors), result.errors


def test_radio_only_project_with_consensus_schemes_exports(tmp_path):
    context = _radio_only(tmp_path)
    out = create_test_directory("cultural_domain_export_radio_cc")
    result = export_registry.export("cultural_domain", context, out,
                                    {"consensus_schemes": "q0,q1,q2,q3"})
    assert result.success, result.errors
    assert any(f.endswith("consensus_answers.csv") for f in result.files_written)


def test_not_available_without_answers_to_its_schemes(tmp_path):
    schemas = [{"annotation_type": "free_list", "name": "fruit", "description": "d"},
               {"annotation_type": "multiselect", "name": "multi", "description": "d",
                "labels": ["a", "b"]}]
    anns = [{"user_id": "u1", "instance_id": "i1", "labels": {"multi": {"a": "true"}}}]
    context = ExportContext(config={"task_dir": str(tmp_path)}, annotations=anns, items={},
                            schemas=schemas, output_dir=str(tmp_path))
    ok, reason = CulturalDomainExporter().can_export(context)
    assert not ok and "No answers" in reason
    assert CulturalDomainExporter().can_export(_radio_only(tmp_path, with_answers=False))[0] is False
