"""Legacy config translation, and the jury and static sources it relies on."""

import json
import os
import subprocess
import sys

import pytest
import yaml

from potato.labeling_engine.config import parse_engine_config
from potato.labeling_engine.config.translate import deprecation_warnings, translate
from potato.labeling_engine.items import ItemView
from potato.labeling_engine.runtime import Runner
from potato.labeling_engine.schemes import SchemeSpec
from potato.labeling_engine.sources import build_source
from potato.labeling_engine.store import EngineStore
from potato.persistence import clear_db_cache

SCHEMES = [{"name": "s", "annotation_type": "radio", "labels": ["a", "b"]}]


def _valid(cfg, block):
    parse_engine_config({**cfg, "labeling_engine": {**block, "enabled": True}})


class TestTranslate:

    def test_solo_routing_becomes_a_cascade_with_a_guarantee(self):
        cfg = {"annotation_schemes": SCHEMES, "solo_mode": {
            "enabled": True,
            "thresholds": {"end_human_annotation_agreement": 0.9},
            "confidence_routing": {"enabled": True, "tiers": [
                {"name": "fast", "confidence_threshold": 0.9,
                 "model": {"endpoint_type": "laya", "model": "convaiinnovations/laya",
                           "device": "cpu"}},
                {"name": "strong", "confidence_threshold": 0.5,
                 "model": {"endpoint_type": "vllm", "model": "g",
                           "base_url": "http://x/v1"}}]}}}
        block, notes = translate(cfg)
        assert block["enabled"] is False and block["cascade"] == ["fast", "strong"]
        assert block["sources"][0]["kind"] == "decision"
        assert block["sources"][0]["options"] == {"device": "cpu"}
        [c] = block["contracts"]
        assert c["kind"] == "selective_risk" and c["error"] == pytest.approx(0.1)
        assert block["humans"]["pools"] == ["solo"]
        _valid(cfg, block)

    def test_icl_keeps_its_threshold_as_uncertified_and_adds_a_guarantee(self):
        cfg = {"annotation_schemes": SCHEMES,
               "ai_support": {"enabled": True, "endpoint_type": "ollama",
                              "ai_config": {"model": "llama3.2"}},
               "icl_labeling": {"enabled": True,
                                "llm_labeling": {"confidence_threshold": 0.8},
                                "verification": {"sample_rate": 0.25}}}
        block, notes = translate(cfg)
        kinds = {c["kind"] for c in block["contracts"]}
        assert kinds == {"threshold_legacy", "selective_risk"}
        assert block["humans"]["calibration_rate"] == 0.25
        assert any("without a guarantee" in n for n in notes)
        assert deprecation_warnings(cfg) and "3.0" in deprecation_warnings(cfg)[0]
        _valid(cfg, block)

    def test_judge_alignment_and_pre_annotation(self):
        cfg = {"annotation_schemes": SCHEMES,
               "ai_support": {"enabled": True, "endpoint_type": "openai",
                              "ai_config": {"model": "gpt"}},
               "judge_alignment": {"enabled": True, "inline": {"enabled": True},
                                   "schemas": {"s": {"rubric": "be strict"}}},
               "pre_annotation": {"field": "preds"}}
        block, notes = translate(cfg)
        ids = [s["id"] for s in block["sources"]]
        assert ids[0] == "judge" and block["cascade"][0] == "preannotations"
        assert block["sources"][0]["options"]["rubric"] == "be strict"
        assert any(c["kind"] == "no_worse_than_human" for c in block["contracts"])
        assert any("anchored" in n for n in notes)
        _valid(cfg, block)

    def test_nothing_to_translate(self):
        assert translate({"annotation_schemes": SCHEMES}) == (None, [])

    def test_migrate_config_command(self, tmp_path):
        cfg = {"annotation_schemes": SCHEMES,
               "ai_support": {"enabled": True, "endpoint_type": "ollama",
                              "ai_config": {"model": "llama3.2"}},
               "icl_labeling": {"enabled": True}}
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(cfg))
        out = subprocess.run([sys.executable, "-m", "potato.flask_server", "label",
                              "migrate-config", str(path)], capture_output=True, text=True,
                             cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                                 os.path.dirname(os.path.abspath(__file__))))))
        assert out.returncode == 0, out.stderr
        text = out.stdout
        assert text.startswith("# Translated by")
        assert yaml.safe_load(text)["labeling_engine"]["enabled"] is False


@pytest.fixture
def store(tmp_path):
    clear_db_cache()
    yield EngineStore(str(tmp_path))
    clear_db_cache()


def test_jury_plurality(store, tmp_path):
    app = {"task_dir": str(tmp_path), "annotation_task_name": "j",
           "annotation_schemes": SCHEMES}
    eng = parse_engine_config({**app, "labeling_engine": {"enabled": True, "sources": [
        {"id": "m1", "kind": "fixture", "error_rate": 0.0, "seed": 1},
        {"id": "m2", "kind": "fixture", "error_rate": 0.0, "seed": 2},
        {"id": "m3", "kind": "fixture", "error_rate": 1.0, "seed": 3},
        {"id": "jury", "kind": "jury", "members": ["m1", "m2", "m3"]}],
        "cascade": ["jury"]}})
    src = build_source(eng.source("jury"), app, eng)
    scheme = SchemeSpec.from_scheme(SCHEMES[0])
    items = [ItemView(f"i{k}", "t", data={"gold": "a"}) for k in range(5)]
    s = Runner(store, app, eng).predict(src, scheme, items)
    preds = store.current_predictions("s", s.source_version_id)
    assert all(p.value == "a" and p.raw_conf == pytest.approx(2 / 3) for p in preds.values())
    # Members' own predictions are kept too.
    assert store.prediction_count() == 5 * 4


def test_static_from_field_and_file(store, tmp_path):
    app = {"task_dir": str(tmp_path), "annotation_task_name": "st",
           "annotation_schemes": SCHEMES}
    (tmp_path / "preds.jsonl").write_text(
        json.dumps({"id": "i1", "schema": "s", "label": "B", "confidence": 0.7}) + "\n")
    eng = parse_engine_config({**app, "labeling_engine": {"enabled": True, "sources": [
        {"id": "f", "kind": "static", "field": "preds"},
        {"id": "p", "kind": "static", "predictions_file": "preds.jsonl"}]}})
    scheme = SchemeSpec.from_scheme(SCHEMES[0])
    items = [ItemView("i1", "", data={"preds": {"s": {"label": "a", "confidence": 0.9}}}),
             ItemView("i2", "", data={})]
    fs = Runner(store, app, eng).predict(build_source(eng.source("f"), app, eng), scheme, items)
    got = store.current_predictions("s", fs.source_version_id)
    assert (got["i1"].value, got["i1"].raw_conf) == ("a", 0.9) and got["i2"].status == "abstain"
    ps = Runner(store, app, eng).predict(build_source(eng.source("p"), app, eng), scheme, items)
    got = store.current_predictions("s", ps.source_version_id)
    assert (got["i1"].value, got["i1"].raw_conf) == ("b", 0.7)


def test_static_field_with_a_bare_label(store, tmp_path):
    # One scheme: "pred": "a" can only mean that scheme's label.
    app = {"task_dir": str(tmp_path), "annotation_task_name": "st1",
           "annotation_schemes": SCHEMES[:1]}
    eng = parse_engine_config({**app, "labeling_engine": {"enabled": True, "sources": [
        {"id": "f", "kind": "static", "field": "pred"}]}})
    scheme = SchemeSpec.from_scheme(SCHEMES[0])
    items = [ItemView(f"i{k}", "", data={"pred": "a"}) for k in range(3)]
    fs = Runner(store, app, eng).predict(build_source(eng.source("f"), app, eng), scheme, items)
    got = store.current_predictions("s", fs.source_version_id)
    assert {p.value for p in got.values()} == {"a"}


def test_static_field_of_the_wrong_shape_fails_loudly(store, tmp_path):
    two = SCHEMES[:1] + [dict(SCHEMES[0], name="s2")]
    app = {"task_dir": str(tmp_path), "annotation_task_name": "st2",
           "annotation_schemes": two}
    eng = parse_engine_config({**app, "labeling_engine": {"enabled": True, "sources": [
        {"id": "f", "kind": "static", "field": "pred"}]}})
    scheme = SchemeSpec.from_scheme(two[0])
    items = [ItemView(f"i{k}", "", data={"pred": "a"}) for k in range(3)]
    run = Runner(store, app, eng).predict(build_source(eng.source("f"), app, eng),
                                          scheme, items)
    # The run fails with the reason, instead of 3 silent abstains.
    assert run.status == "failed" and "field 'pred' holds str" in run.message
    assert store.prediction_count() == 0


def test_an_answer_outside_the_scheme_is_an_error_not_a_label(store, tmp_path):
    """Found by potato-skill (F4): a static column with "banana" in it, or a
    list on a radio scheme, was predicted ok and resolved auto/accepted
    whenever the rest of the column was right."""
    app = {"task_dir": str(tmp_path), "annotation_task_name": "st3",
           "annotation_schemes": SCHEMES[:1]}
    eng = parse_engine_config({**app, "labeling_engine": {"enabled": True, "sources": [
        {"id": "f", "kind": "static", "field": "pred"}]}})
    scheme = SchemeSpec.from_scheme(SCHEMES[0])
    items = [ItemView("i0", "", data={"pred": "banana"}),
             ItemView("i1", "", data={"pred": ["a"]}),
             ItemView("i2", "", data={"pred": " A "})]
    run = Runner(store, app, eng).predict(build_source(eng.source("f"), app, eng),
                                          scheme, items)
    got = store.current_predictions("s", run.source_version_id)
    assert [got[i].status for i in ("i0", "i1", "i2")] == ["error", "error", "ok"]
    assert got["i2"].value == "a" and got["i0"].value is None
    assert run.n_error == 2 and "banana" in run.message


def test_a_bad_value_in_a_mostly_right_column_is_never_accepted(tmp_path):
    from potato.labeling_engine.service import Engine
    from .test_engine_service import _items
    clear_db_cache()
    items = _items(600)
    for it in items:
        it.data["pred"] = it.data["gold"]
    items[5].data["pred"] = "banana"
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "f4",
           "annotation_schemes": [{"name": "sentiment", "annotation_type": "radio",
                                   "labels": ["positive", "negative", "neutral"]}],
           "labeling_engine": {"enabled": True,
                               "sources": [{"id": "col", "kind": "static", "field": "pred",
                                            "options": {"default_confidence": 0.9}}],
                               "contracts": [{"id": "acc", "kind": "selective_risk",
                                              "schema": "sentiment", "error": 0.1}]}}
    eng = Engine(cfg)
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items if i.item_id != items[5].item_id],
                         rate=0.3)
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in eng.store.requests(status=["open"]):
        eng.record_human_label(r.item_id, r.schema, gold[r.item_id], "ann", request_id=r.id)
    assert eng.certify(scheme)["acc"]["status"] == "met"
    eng.resolve(scheme)
    res = {r.item_id: r for r in eng.store.resolved(schema="sentiment")}
    bad = res.get(items[5].item_id)
    assert bad is None or not (bad.origin == "auto" and bad.status == "accepted")
    assert sum(1 for r in res.values() if r.origin == "auto") > 300
    clear_db_cache()


def test_judge_calibration_keeps_its_prompt_schemas_and_sample_size():
    """Found by potato-skill (B15): all three were dropped."""
    cfg = {"annotation_schemes": SCHEMES,
           "judge_calibration": {"enabled": True, "prompt": "Grade it: {text}",
                                 "schemas": ["s"], "k_samples": 3,
                                 # Where the shipped example and the judge
                                 # calibration docs put it (potato-skill B16).
                                 "sampling": {"strategy": "random", "sample_size": 120},
                                 "models": [{"endpoint_type": "openai", "model": "m"}]}}
    block, notes = translate(cfg)
    [judge] = [s for s in block["sources"] if s["id"] == "judge0"]
    assert judge["prompt"] == "Grade it: {text}" and judge["schemas"] == ["s"]
    assert judge["confidence"] == {"method": "k_sample", "samples": 3}
    assert block["budgets"]["human_labels"] == 120
    assert any("sample_size of 120" in n for n in notes)


def test_pre_annotation_is_not_flagged_for_removal():
    """It prefills an editable starting point, which the engine's static source
    does not do, and every importer writes it; validate flagged every import."""
    cfg = {"pre_annotation": {"enabled": True, "field": "predictions",
                              "allow_modification": True}}
    assert deprecation_warnings(cfg) == []
    # migrate-config still offers the translation.
    block, _notes = translate(cfg)
    assert block and any(s["kind"] == "static" for s in block["sources"])
