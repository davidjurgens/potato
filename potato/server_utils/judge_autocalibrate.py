"""
Automated judge calibration (G5).

Closes the loop on LLM-as-judge: the instances where a human *corrected* the
judge (human label ≠ judge label) are exactly where the judge is wrong, so they
make the most informative few-shot examples. This module gathers those
corrections and re-runs the judge with them injected into the prompt, creating a
new prompt version whose κ can be compared against the baseline — LangSmith's
"human corrections auto-become few-shot examples", grounded in Potato's existing
κ tracking.

Leakage guard: when judging an instance, any correction *for that same instance*
is excluded from its few-shot set (you never show the judge the answer to the
item it's grading).

Builds entirely on the existing ``judge_alignment`` persistence + compute layer
(``gather_pairs`` / ``save_prediction`` / ``compute_alignment_from_pairs``).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from potato.server_utils import judge_alignment as ja

logger = logging.getLogger(__name__)


def _instance_text(ism, iid: str) -> str:
    try:
        item = ism.get_item(iid)
        return item.get_text() if item else ""
    except Exception:
        return ""


def _fingerprint(corrections: List[Dict[str, Any]]) -> str:
    """Stable hash of a correction set so the prompt version changes with it."""
    basis = "|".join(sorted(f"{c['id']}:{c['label']}" for c in corrections))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:8]


def collect_corrections(
    config: Dict[str, Any],
    users: List[str],
    prompt_version: Optional[str] = None,
    source_pairs: Optional[Dict[str, List]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Per-schema correction exemplars (judge disagreed with the human).

    Returns ``{schema: [{"id", "text", "label"(=human gold)}]}``.
    """
    from potato.item_state_management import get_item_state_manager
    schema_names = [s.get("name") for s in ja.judge_scoped_schemas(config)]
    version = prompt_version or ja.latest_prompt_version(config)
    pairs = source_pairs if source_pairs is not None else \
        ja.gather_pairs(config, users, schema_names, version)
    ism = get_item_state_manager()

    out: Dict[str, List[Dict[str, Any]]] = {}
    for schema, plist in pairs.items():
        corrections = []
        for inst, human, judge, _conf, _reason in plist:
            if human is not None and judge is not None and str(human) != str(judge):
                corrections.append({
                    "id": inst,
                    "text": _instance_text(ism, inst),
                    "label": str(human),
                })
        out[schema] = corrections
    return out


def autocalibrate(
    config: Dict[str, Any],
    users: List[str],
    max_corrections: int = 5,
    max_per_schema: Optional[int] = None,
    min_corrections: int = 1,
    service: Any = None,
) -> Dict[str, Any]:
    """Run one auto-calibration round per judge-scoped schema.

    For each schema with corrections: re-judge its human-annotated instances with
    the corrections injected as few-shot (leakage-guarded), persist under a new
    prompt version, and report base vs new κ.

    ``service`` (a JudgeService-like with ``get_rubric`` + ``judge_instance``) may
    be injected for testing.
    """
    from potato.ai.judge import JudgeService, compute_prompt_version
    from potato.item_state_management import get_item_state_manager

    schemas_info = ja.judge_scoped_schemas(config)
    schema_names = [s.get("name") for s in schemas_info]
    base_version = ja.latest_prompt_version(config)
    base_pairs = ja.gather_pairs(config, users, schema_names, base_version)
    base_report = ja.compute_alignment_from_pairs(base_pairs)
    corrections = collect_corrections(config, users, base_version, source_pairs=base_pairs)

    service = service or JudgeService(config)
    ism = get_item_state_manager()
    results: Dict[str, Any] = {}

    for schema in schemas_info:
        name = schema.get("name")
        base_kappa = base_report.get(name, {}).get("kappa")
        sch_corr = corrections.get(name, [])[:max_corrections]
        if len(sch_corr) < min_corrections:
            results[name] = {"status": "skipped", "reason": "no corrections",
                             "base_kappa": base_kappa, "n_corrections": len(sch_corr)}
            continue

        rubric = service.get_rubric(schema)
        new_version = compute_prompt_version(
            rubric, name, True, extra="corr:" + _fingerprint(sch_corr))

        ids = ja.annotated_instance_ids(users, name)
        if max_per_schema:
            ids = ids[:max_per_schema]

        judged = 0
        for iid in ids:
            text = _instance_text(ism, iid)
            # Leakage guard: never show the judge a correction for the very
            # instance it is grading.
            shots = [c for c in sch_corr if c["id"] != iid] or None
            pred = service.judge_instance(iid, schema, text,
                                          few_shot_examples=shots,
                                          prompt_version=new_version)
            if pred is not None:
                ja.save_prediction(config, pred)
                judged += 1

        new_pairs = ja.gather_pairs(config, users, [name], new_version)
        new_kappa = ja.compute_alignment_from_pairs(new_pairs).get(name, {}).get("kappa")
        delta = (round(new_kappa - base_kappa, 3)
                 if (base_kappa is not None and new_kappa is not None) else None)
        results[name] = {
            "status": "calibrated",
            "base_version": base_version,
            "new_version": new_version,
            "base_kappa": base_kappa,
            "new_kappa": new_kappa,
            "delta": delta,
            "improved": bool(base_kappa is not None and new_kappa is not None
                             and new_kappa > base_kappa),
            "n_corrections": len(sch_corr),
            "judged": judged,
        }

    improved = sum(1 for r in results.values() if r.get("improved"))
    return {"schemas": results, "improved_count": improved, "total": len(results)}
