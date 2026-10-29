"""
Legacy machine-labeling config -> an equivalent ``labeling_engine`` block.

Potato grew several ways to have a model label data before the engine:
``solo_mode``, ``icl_labeling``, ``judge_alignment``, ``judge_calibration``,
``pre_annotation``, ``active_learning.llm`` and ``ai_budget``. They keep
working; this module says what the engine version of each would be, so a
study can move over deliberately:

    potato label migrate-config config.yaml > config.engine.yaml

``translate`` returns ``(block, notes)``. The block is never enabled by
itself: it is a proposal to read, with ``notes`` saying where the old
behaviour and the engine's differ. Above all, where the old subsystem
accepted machine labels on a fixed confidence threshold, the translation
keeps that as ``threshold_legacy`` (no guarantee) and adds the
``selective_risk`` contract that would replace it.

``deprecation_warnings`` names each legacy key with its replacement and the
3.0 removal target; ``potato validate`` prints them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

DECISION_TYPES = ("laya", "systemone")
REMOVAL = "3.0"

LEGACY_KEYS = {
    "icl_labeling": "labeling_engine (an llm source plus a threshold_legacy or "
                    "selective_risk contract)",
    "judge_calibration": "labeling_engine (judge sources with k_sample confidence)",
}
# pre_annotation is not deprecated. It shows a model's or an import's answer
# as an editable starting point, which the engine's static source does not
# do: there a label is accepted where a contract certifies it. Every importer
# (camera traps, BirdNET, QDPX, ...) writes pre_annotation for exactly that,
# and a warning that it would be removed sent users toward something else.
# `migrate-config` still translates it for anyone who wants the engine.


def _model_source(sid: str, m: Dict[str, Any], kind: Optional[str] = None) -> Dict[str, Any]:
    et = m.get("endpoint_type") or m.get("type") or ""
    out = {"id": sid, "kind": kind or ("decision" if et in DECISION_TYPES else "llm"),
           "endpoint_type": et, "model": m.get("model", "")}
    ai = m.get("ai_config") or {}
    for k in ("base_url", "api_key", "max_tokens", "temperature", "timeout"):
        v = m.get(k, ai.get(k))
        if v is not None:
            out[k] = v
    if m.get("endpoint_url") and "base_url" not in out:
        out["base_url"] = m["endpoint_url"]
    opts = {k: m[k] for k in ("device", "batch_size", "max_options", "state_key") if k in m}
    if opts:
        out["options"] = opts
    return out


def _ai_support_source(sid: str, cfg: Dict[str, Any], kind: str = "llm") -> Optional[Dict]:
    ai = cfg.get("ai_support") or {}
    if not ai.get("endpoint_type"):
        return None
    return _model_source(sid, {"endpoint_type": ai["endpoint_type"],
                               **(ai.get("ai_config") or {})}, kind)


def _one_of_n(cfg) -> List[str]:
    return [s["name"] for s in cfg.get("annotation_schemes") or []
            if isinstance(s, dict) and s.get("annotation_type") in ("radio", "select", "likert")]


def translate(cfg: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    sources: List[Dict[str, Any]] = []
    cascade: List[str] = []
    contracts: List[Dict[str, Any]] = []
    humans: Dict[str, Any] = {}
    budgets: Dict[str, Any] = {}
    notes: List[str] = []
    schemes = _one_of_n(cfg)

    sm = cfg.get("solo_mode") or {}
    if sm.get("enabled"):
        routing = sm.get("confidence_routing") or {}
        if routing.get("enabled") and routing.get("tiers"):
            for k, tier in enumerate(routing["tiers"]):
                sid = tier.get("name") or f"tier{k}"
                sources.append(_model_source(sid, tier.get("model") or {}))
                cascade.append(sid)
            notes.append("solo_mode.confidence_routing: each tier's fixed "
                         "confidence_threshold becomes a threshold chosen and certified "
                         "by the selective_risk contract.")
        else:
            for k, m in enumerate(sm.get("labeling_models") or []):
                sid = f"solo{k}"
                sources.append(_model_source(sid, m))
                cascade.append(sid) if k == 0 else None
        jury = sm.get("jury") or {}
        if jury.get("enabled") and jury.get("models"):
            members = []
            for k, m in enumerate(jury["models"]):
                sid = f"juror{k}"
                sources.append(_model_source(sid, m))
                members.append(sid)
            sources.append({"id": "jury", "kind": "jury", "members": members})
            cascade = ["jury"]
        agreement = float((sm.get("thresholds") or {}).get(
            "end_human_annotation_agreement", 0.9))
        for name in schemes:
            contracts.append({"id": f"{name}_accuracy", "kind": "selective_risk",
                              "schema": name, "error": round(1 - agreement, 4),
                              "confidence": 0.9})
        notes.append(f"solo_mode handed the corpus to the LLM once agreement reached "
                     f"{agreement:.0%}; the engine instead accepts labels only under a "
                     f"selective_risk guarantee of at most {1 - agreement:.0%} error.")
        humans["pools"] = ["solo"]

    icl = cfg.get("icl_labeling") or {}
    if icl.get("enabled"):
        src = _ai_support_source("icl", cfg)
        if src:
            sources.append(src)
            cascade.append("icl")
        thr = float((icl.get("llm_labeling") or {}).get("confidence_threshold", 0.7))
        rate = float((icl.get("verification") or {}).get("sample_rate", 0.2))
        for name in schemes:
            contracts.append({"id": f"{name}_icl_threshold", "kind": "threshold_legacy",
                              "schema": name, "threshold": thr})
            contracts.append({"id": f"{name}_accuracy", "kind": "selective_risk",
                              "schema": name, "error": 0.1, "confidence": 0.9})
        humans["calibration_rate"] = rate
        notes.append(f"icl_labeling accepted labels at confidence >= {thr} without a "
                     "guarantee (kept as threshold_legacy). Its verification sample was "
                     f"{(icl.get('verification') or {}).get('selection_strategy', 'low_confidence')}"
                     "-ordered; the engine's calibration sample is uniform, which is what "
                     "makes the accuracy estimate unbiased.")

    ja = cfg.get("judge_alignment") or {}
    if ja.get("enabled"):
        src = _ai_support_source("judge", {"ai_support": ja.get("ai_support")
                                           or cfg.get("ai_support")}, "judge")
        if src:
            rubrics = {k: (v or {}).get("rubric") for k, v in (ja.get("schemas") or {}).items()}
            if len(rubrics) == 1:
                src["options"] = {"rubric": next(iter(rubrics.values()))}
            sources.append(src)
            cascade.append("judge")
        for name in (ja.get("schemas") or {}):
            contracts.append({"id": f"{name}_as_good_as_a_person",
                              "kind": "no_worse_than_human", "schema": name,
                              "epsilon": 0.15})
        if (ja.get("inline") or {}).get("enabled"):
            notes.append("judge_alignment.inline showed the judge's verdict while people "
                         "labeled, so its agreement was measured on anchored labels. The "
                         "engine's calibration requests are blind.")
        humans.setdefault("overlap", 0.3)

    jc = cfg.get("judge_calibration") or {}
    if jc.get("enabled"):
        for k, m in enumerate(jc.get("models") or []):
            sid = f"judge{k}"
            s = _model_source(sid, m, "judge")
            s["confidence"] = {"method": "k_sample", "samples": int(jc.get("k_samples", 5))}
            if jc.get("prompt"):
                s["prompt"] = jc["prompt"]
            if jc.get("schemas"):
                s["schemas"] = list(jc["schemas"])
            sources.append(s)
            cascade.append(sid) if not cascade else None
        # The key lives under `sampling`; a bare `sample_size` is accepted too.
        sample_size = (jc.get("sampling") or {}).get("sample_size") or jc.get("sample_size")
        if sample_size:
            budgets.setdefault("human_labels", int(sample_size))
        notes.append("judge_calibration's k-sample agreement becomes each judge's "
                     "k_sample confidence; its blind sample becomes calibration requests"
                     + (f", capped at its sample_size of {int(sample_size)} human "
                        "labels (budgets.human_labels)" if sample_size else "")
                     + ".")

    pa = cfg.get("pre_annotation") or {}
    if pa.get("field") or pa.get("predictions_file"):
        s = {"id": "preannotations", "kind": "static"}
        if pa.get("predictions_file"):
            s["predictions_file"] = pa["predictions_file"]
        else:
            s["field"] = pa.get("field", "predictions")
        sources.append(s)
        cascade.insert(0, "preannotations")
        notes.append("pre_annotation prefilled the form; as a static source its labels "
                     "are accepted only where a contract certifies them, and shown on "
                     "verify requests otherwise.")

    al = (cfg.get("active_learning") or {}).get("llm") or {}
    if al.get("enabled") and al.get("endpoint_type"):
        sources.append(_model_source("al_llm", al))
        cascade.append("al_llm") if not cascade else None

    cap = (cfg.get("ai_budget") or {}).get("cap_usd")
    if cap is not None:
        budgets["model_usd"] = float(cap)

    if not sources:
        return None, notes
    seen, uniq = set(), []
    for s in sources:
        if s["id"] not in seen:
            uniq.append(s)
            seen.add(s["id"])
    cids, ucontracts = set(), []
    for c in contracts:
        if c["id"] not in cids:
            ucontracts.append(c)
            cids.add(c["id"])
    block = {"enabled": False, "sources": uniq, "cascade": cascade or [uniq[0]["id"]],
             "contracts": ucontracts}
    if humans:
        block["humans"] = humans
    if budgets:
        block["budgets"] = budgets
    return block, notes


def deprecation_warnings(cfg: Dict[str, Any]) -> List[str]:
    out = []
    for key, replacement in LEGACY_KEYS.items():
        block = cfg.get(key) or {}
        present = block.get("enabled")
        if present:
            out.append(f"{key} still works, but the labeling engine now does this: use "
                       f"{replacement}. `potato label migrate-config` writes the "
                       f"equivalent block. {key} is planned for removal in {REMOVAL}.")
    return out
