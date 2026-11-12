"""The certificate and the engine exporter, on a fixture-source study."""

import json
import os
import random

import pytest

from potato.export.base import ExportContext
from potato.export.registry import export_registry
from potato.labeling_engine.certificate import build_certificate, render_markdown
from potato.labeling_engine.items import ItemView
from potato.labeling_engine.service import Engine
from potato.persistence import clear_db_cache

LABELS = ["positive", "negative"]


@pytest.fixture
def study(tmp_path):
    clear_db_cache()
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "cert",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                   "labels": LABELS}],
           "labeling_engine": {"enabled": True,
                               "sources": [{"id": "fx", "kind": "fixture",
                                            "error_rate": 0.1,
                                            "options": {"separability": 0.8}}],
                               "contracts": [
                                   {"id": "acc", "kind": "selective_risk", "schema": "s",
                                    "error": 0.15},
                                   {"id": "prev", "kind": "ppi", "schema": "s"}]}}
    eng = Engine(cfg)
    rng = random.Random(0)
    items = [ItemView(f"i{k}", f"t{k}", data={"gold": rng.choice(LABELS)})
             for k in range(1500)]
    scheme = eng.scheme("s")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.15)
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in eng.store.requests(status=["open"]):
        eng.record_human_label(r.item_id, "s", gold[r.item_id], "ann", request_id=r.id)
    eng.certify(scheme)
    eng.resolve(scheme)
    yield cfg, eng
    clear_db_cache()


def test_certificate_covers_contracts_cascade_and_hashes(study):
    cfg, eng = study
    cert = build_certificate(eng)
    sec = cert["schemes"]["s"]
    assert sec["contracts"]["acc"]["status"] == "met"
    assert sec["cascade"][0]["source"] == "fx" and sec["cascade"][0]["version"]
    assert sec["delivered"]["auto:accepted"] > 0
    assert sec["human_requests"]["calibration"]["done"] > 0
    assert sec["sampling_designs"][0]["kind"] == "bernoulli"
    assert len(cert["dataset_hash"]) == 64 and len(cert["call_log_digest"]) == 64
    assert cert["certificate_id"] and eng.store.latest_certificate().id == cert["certificate_id"]
    md = render_markdown(cert)
    assert "| acc | selective_risk | met |" in md


def test_certificate_hash_changes_when_labels_change(study):
    cfg, eng = study
    a = build_certificate(eng, save=False)
    labs = eng.store.resolved(schema="s")
    labs[0].value = "negative" if labs[0].value == "positive" else "positive"
    eng.store.set_resolved([labs[0]])
    b = build_certificate(eng, save=False)
    assert a["dataset_hash"] != b["dataset_hash"]
    assert a["content_sha256"] != b["content_sha256"]


def test_engine_exporter_writes_every_item_with_provenance(study, tmp_path):
    cfg, eng = study
    out = tmp_path / "export"
    ctx = ExportContext(config=cfg, annotations=[], items={}, schemas=cfg["annotation_schemes"],
                        output_dir=str(tmp_path))
    res = export_registry.export("labeling_engine", ctx, str(out))
    assert res.success, res.errors
    rows = [json.loads(l) for l in open(out / "labels.jsonl")]
    assert len(rows) == 1500
    auto = [r for r in rows if r["label_origin"] == "auto"]
    assert auto and all(r["source"] == "fx" and r["confidence"] is not None
                        and r["contract_version"] for r in auto)
    human = [r for r in rows if r["label_origin"] == "human"]
    assert human and all(r["request_ids"] for r in human)
    for name in ("labels.csv", "certificate.json", "certificate.md", "certificate.html",
                 "README.md", "model_calls.jsonl"):
        assert os.path.exists(out / name), name
    assert open(out / "README.md").read().startswith("---\n")


def test_human_exports_say_which_engine_request_a_label_answered(study, tmp_path):
    from potato.export.cli import _add_engine_provenance
    from potato.export.tabular_exporter import _flatten_annotation
    from potato.export.origin_columns import engine_in_use
    cfg, eng = study
    done = eng.store.requests(status=["done"])[0]
    anns = [{"instance_id": done.item_id, "user_id": "ann", "labels": {}},
            {"instance_id": "not-asked", "user_id": "someone", "labels": {}}]
    _add_engine_provenance(anns, cfg)
    assert anns[0]["_engine"]["s"]["purpose"] == "calibration"
    assert anns[0]["_engine"]["s"]["inclusion_prob"] == pytest.approx(0.15)
    assert "_engine" not in anns[1]
    assert engine_in_use(anns)
    row = _flatten_annotation(anns[0], with_engine=True)
    assert row["engine_purpose"] == "calibration" and '"blind"' in row["engine_request"]
    assert _flatten_annotation(anns[1], with_engine=True)["engine_purpose"] == ""


def test_certificate_prints_the_intervals_its_statement_promises(study):
    cfg, eng = study
    cert = build_certificate(eng, save=False)
    est = cert["schemes"]["s"]["contracts"]["prev"]["estimates"]["all"]
    md = render_markdown(cert)
    for label in LABELS:
        e = est[label]
        assert f"| all | {label} | {e['estimate']:.3f} | [{e['lo']:.3f}, {e['hi']:.3f}] |" in md
    from potato.labeling_engine.certificate.render import render_html
    page = render_html(cert)
    assert page.count("<table>") == page.count("</table>") == 2
    assert f"[{est[LABELS[0]]['lo']:.3f}, {est[LABELS[0]]['hi']:.3f}]" in page


def test_certificate_counts_human_spend_and_names_combining_only_when_it_happened(study):
    cfg, eng = study
    cfg["labeling_engine"]["budgets"] = {"human_labels": 10_000}
    eng2 = Engine(cfg)
    cert = build_certificate(eng2, save=False)
    opened = sum(1 for r in eng2.store.requests() if r.purpose != "organic")
    assert cert["budgets"]["human_labels"]["spent"] == opened > 0
    md = render_markdown(cert)
    # One person per item: nothing was combined.
    assert cert["schemes"]["s"]["multi_rater_items"] == 0
    assert "combined by" not in md


def test_html_certificate_lists_and_code_and_per_source_counts(study):
    """Found by potato-skill (I4, H6, F6b): bare <li>s with no <ul>, literal
    backticks around unwrappable hashes, no per-source count and no budget line."""
    from bs4 import BeautifulSoup
    from potato.labeling_engine.certificate import render_html
    cfg, eng = study
    eng.store.set_budget(__import__("potato.labeling_engine.model.records",
                                    fromlist=["Budget"]).Budget(kind="human_labels",
                                                                limit=1000))
    cert = build_certificate(eng, save=False)
    soup = BeautifulSoup(render_html(cert), "html.parser")
    assert soup.find_all("li") and all(li.parent.name == "ul" for li in soup.find_all("li"))
    assert "`" not in soup.get_text()
    assert len(soup.find_all("code")) >= 3
    md = render_markdown(cert)
    auto = cert["schemes"]["s"]["delivered"]["auto:accepted"]
    assert f"Machine labels accepted, by source: fx {auto}." in md
    assert "of 1000 requested (" in md


def test_an_unmet_contract_states_a_target_not_a_guarantee(tmp_path):
    """Found by potato-skill (I9)."""
    clear_db_cache()
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "t",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                   "labels": LABELS}],
           "labeling_engine": {"enabled": True,
                               "sources": [{"id": "fx", "kind": "fixture",
                                            "error_rate": 0.1}],
                               "contracts": [{"id": "strict", "kind": "selective_risk",
                                              "schema": "s", "error": 0.01}]}}
    eng = Engine(cfg)
    rng = random.Random(0)
    items = [ItemView(f"i{k}", f"t{k}", data={"gold": rng.choice(LABELS)})
             for k in range(600)]
    scheme = eng.scheme("s")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in eng.store.requests(status=["open"]):
        eng.record_human_label(r.item_id, "s", gold[r.item_id], "ann", request_id=r.id)
    res = eng.certify(scheme)["strict"]
    assert res["status"] != "met"
    assert res["statement"].startswith("Target, not established")
    assert "With probability at least" not in render_markdown(build_certificate(eng, save=False))
    clear_db_cache()


def test_export_has_a_row_for_every_item_labeled_or_not(study, tmp_path):
    """Found by potato-skill (A7): 6 rows for a 30-item study."""
    cfg, eng = study
    # Unaccept some labels: they become pending rows, not missing ones.
    gone = [r.item_id for r in eng.store.resolved(schema="s")][:25]
    eng.store.conn.execute(
        f"DELETE FROM resolved_label WHERE item_id IN ({','.join('?' * len(gone))})", gone)
    out = tmp_path / "export2"
    ctx = ExportContext(config=cfg, annotations=[], items={}, schemas=cfg["annotation_schemes"],
                        output_dir=str(tmp_path))
    assert export_registry.export("labeling_engine", ctx, str(out)).success
    rows = [json.loads(l) for l in open(out / "labels.jsonl")]
    assert len(rows) == 1500 and len({r["id"] for r in rows}) == 1500
    pending = [r for r in rows if r["status"] == "pending"]
    assert {r["id"] for r in pending} == set(gone) and all(r["label"] is None for r in pending)


def test_a_budget_that_cannot_certify_is_warned_about(caplog):
    """Found by potato-skill (K1, the cap case): 10 human labels can never
    certify 10% at 0.9."""
    from potato.labeling_engine.config import parse_engine_config
    from potato.server_utils.config_module import _warn_engine_budget_too_small
    def cfg(cap):
        return parse_engine_config({
            "annotation_schemes": [{"name": "s", "annotation_type": "radio", "labels": LABELS}],
            "labeling_engine": {"enabled": True, "sources": [{"id": "fx", "kind": "fixture"}],
                                "budgets": {"human_labels": cap},
                                "contracts": [{"id": "acc", "kind": "selective_risk",
                                               "schema": "s", "error": 0.1}]}})
    with caplog.at_level("WARNING"):
        _warn_engine_budget_too_small(cfg(10))
    assert any("cannot certify acc" in r.getMessage() for r in caplog.records)
    caplog.clear()
    with caplog.at_level("WARNING"):
        _warn_engine_budget_too_small(cfg(400))
    assert not caplog.records


def test_threshold_legacy_labels_export_as_uncertified(tmp_path):
    """Found by potato-skill (B14)."""
    clear_db_cache()
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "legacy",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio", "labels": LABELS}],
           "labeling_engine": {"enabled": True,
                               "sources": [{"id": "fx", "kind": "fixture", "error_rate": 0.1}],
                               "contracts": [{"id": "old", "kind": "threshold_legacy",
                                              "schema": "s", "threshold": 0.5}]}}
    eng = Engine(cfg)
    rng = random.Random(0)
    items = [ItemView(f"i{k}", "t", data={"gold": rng.choice(LABELS)}) for k in range(200)]
    scheme = eng.scheme("s")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.certify(scheme)
    eng.resolve(scheme)
    out = tmp_path / "x"
    ctx = ExportContext(config=cfg, annotations=[], items={}, schemas=cfg["annotation_schemes"],
                        output_dir=str(tmp_path))
    assert export_registry.export("labeling_engine", ctx, str(out)).success
    rows = [json.loads(l) for l in open(out / "labels.jsonl")]
    auto = [r for r in rows if r["label_origin"] == "auto"]
    assert auto and all(r["status"] == "accepted_uncertified" for r in auto)
    # status (and so `potato label status` and the admin page) counts them
    # the same way; it said "auto:accepted" (potato-skill B15).
    resolved = eng.status()["schemes"]["s"]["resolved"]
    assert resolved.get("auto:accepted_uncertified") == len(auto)
    assert "auto:accepted" not in resolved
    clear_db_cache()


def test_export_after_a_config_change_does_not_say_accepted(study, tmp_path):
    """Found by potato-skill (B11)."""
    cfg, eng = study
    changed = json.loads(json.dumps(cfg))
    changed["labeling_engine"]["sources"][0]["options"]["separability"] = 0.81
    out = tmp_path / "x"
    ctx = ExportContext(config=changed, annotations=[], items={},
                        schemas=changed["annotation_schemes"], output_dir=str(tmp_path))
    assert export_registry.export("labeling_engine", ctx, str(out)).success
    rows = [json.loads(l) for l in open(out / "labels.jsonl")]
    auto = [r for r in rows if r["label_origin"] == "auto"]
    assert auto and all(r["status"] == "pending_recert" for r in auto)


def test_cancelled_requests_are_not_counted_as_requested(study):
    """Found by potato-skill: "verify 153 (1 answered)" included 49 requests a
    re-certification had cancelled."""
    from potato.labeling_engine.model.records import HumanRequest
    cfg, eng = study
    eng.store.add_requests([HumanRequest(item_id=f"i{k}", schema="s", purpose="verify",
                                         inclusion_prob=None) for k in range(5)])
    for r in eng.store.requests(purpose=["verify"], status=["open"])[:3]:
        eng.store.update_request(r.id, status="cancelled")
    md = render_markdown(build_certificate(eng))
    line = next(l for l in md.splitlines() if l.startswith("Human requests:"))
    verify = eng.store.request_counts()["verify"]
    shown = sum(n for st, n in verify.items() if st != "cancelled")
    assert f"verify {shown} (" in line and f"{verify['cancelled']} cancelled" in line
