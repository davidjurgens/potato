"""
Judge ↔ human alignment: persistence + agreement computation.

Pairs each LLM-judge verdict (from ``potato/ai/judge.py``) with the human gold
label for the same instance/schema and computes Cohen's κ, a confusion matrix,
agreement rate, and the list of disagreements. Judge predictions are persisted
per *prompt version* so the admin report can track κ as the rubric is calibrated.

Layout under ``{task_dir}/judge_alignment/``:
  predictions.json  -> {prompt_version: {"<instance>::<schema>": JudgePrediction}}
  comparisons.json  -> [{instance_id, schema, human_label, judge_label, agrees, prompt_version}]
                       (running log written by the inline capture path)

The κ computation reuses ``potato/agreement.py`` (judge vs. human gold as two
"annotators"). The pure ``compute_alignment_from_pairs`` is the unit-testable core.
"""

import json
import logging
import os
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ----- paths / persistence ----------------------------------------------

def _dir(config: Dict[str, Any]) -> str:
    base = config.get("output_annotation_dir") or config.get("task_dir") or "."
    return os.path.join(base, "judge_alignment")


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def predictions_path(config: Dict[str, Any]) -> str:
    return os.path.join(_dir(config), "predictions.json")


def comparisons_path(config: Dict[str, Any]) -> str:
    return os.path.join(_dir(config), "comparisons.json")


def load_predictions(config: Dict[str, Any]) -> Dict[str, Dict[str, dict]]:
    return _load_json(predictions_path(config), {})


def save_prediction(config: Dict[str, Any], pred) -> None:
    """Persist one JudgePrediction (keyed by prompt_version → instance::schema)."""
    data = load_predictions(config)
    version = pred.prompt_version or "default"
    data.setdefault(version, {})[f"{pred.instance_id}::{pred.schema_name}"] = pred.to_dict()
    _save_json(predictions_path(config), data)


def latest_prompt_version(config: Dict[str, Any]) -> Optional[str]:
    data = load_predictions(config)
    if not data:
        return None
    # Most-populated version is the "current" working set.
    return max(data.keys(), key=lambda v: len(data[v]))


def record_comparison(config: Dict[str, Any], instance_id: str, schema: str,
                      human_label: Any, judge_label: Any, prompt_version: str) -> None:
    """Append a human↔judge comparison to the running log (inline capture)."""
    log = _load_json(comparisons_path(config), [])
    log.append({
        "instance_id": instance_id,
        "schema": schema,
        "human_label": str(human_label),
        "judge_label": str(judge_label),
        "agrees": str(human_label) == str(judge_label),
        "prompt_version": prompt_version,
    })
    _save_json(comparisons_path(config), log)


def running_agreement(config: Dict[str, Any], schema: Optional[str] = None) -> Dict[str, Any]:
    """Quick running agreement from the comparison log (for the inline badge)."""
    log = _load_json(comparisons_path(config), [])
    if schema:
        log = [c for c in log if c.get("schema") == schema]
    n = len(log)
    agree = sum(1 for c in log if c.get("agrees"))
    pairs = {s: [] for s in {c["schema"] for c in log}}
    for c in log:
        pairs[c["schema"]].append((c["instance_id"], c["human_label"], c["judge_label"], None, ""))
    kappa = None
    if schema and pairs.get(schema):
        res = compute_alignment_from_pairs({schema: pairs[schema]}).get(schema, {})
        kappa = res.get("kappa")
    return {"n": n, "agreements": agree,
            "agreement_rate": round(agree / n, 3) if n else 0.0, "kappa": kappa}


# ----- human label extraction --------------------------------------------

def human_label_for(instance_id: str, schema_name: str, username: str) -> Optional[str]:
    """The single categorical label a user assigned for a schema, or None."""
    from potato.flask_server import get_annotations_for_user_on
    anns = get_annotations_for_user_on(username, instance_id) or {}
    chosen = anns.get(schema_name)
    if not chosen:
        return None
    # Single-choice: the (first) selected label name.
    keys = [k for k in chosen.keys()]
    return keys[0] if keys else None


def majority_human_label(instance_id: str, schema_name: str, users: List[str]) -> Optional[str]:
    votes = []
    for u in users:
        lab = human_label_for(instance_id, schema_name, u)
        if lab is not None:
            votes.append(lab)
    if not votes:
        return None
    return Counter(votes).most_common(1)[0][0]


# ----- agreement computation (pure core) ----------------------------------

def compute_alignment_from_pairs(
    pairs_by_schema: Dict[str, List[Tuple[str, Any, Any, Optional[float], str]]],
) -> Dict[str, Any]:
    """Compute per-schema judge↔human alignment from resolved pairs.

    pairs_by_schema: {schema: [(instance_id, human_label, judge_label,
                                judge_confidence|None, reasoning), ...]}
    Returns {schema: {kappa, interpretation, agreement_rate, n, confusion,
                      disagreements[]}}.
    """
    import pandas as pd
    from potato.agreement import cohen_kappa_pairwise, interpret_kappa

    out: Dict[str, Any] = {}
    for schema, pairs in pairs_by_schema.items():
        pairs = [p for p in pairs if p[1] is not None and p[2] is not None]
        n = len(pairs)
        if n == 0:
            out[schema] = {"kappa": None, "interpretation": "no overlap",
                           "agreement_rate": 0.0, "n": 0, "confusion": {},
                           "disagreements": []}
            continue

        agree = sum(1 for _, h, j, *_ in pairs if str(h) == str(j))
        confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        disagreements = []
        rows = []
        for inst, h, j, conf, reason in pairs:
            confusion[str(h)][str(j)] += 1
            rows.append({"unit": inst, "annotator": "human", "annotation": str(h)})
            rows.append({"unit": inst, "annotator": "judge", "annotation": str(j)})
            if str(h) != str(j):
                disagreements.append({
                    "instance_id": inst, "human_label": str(h), "judge_label": str(j),
                    "judge_confidence": conf, "reasoning": reason,
                })

        kappa = None
        interp = "n/a"
        try:
            res = cohen_kappa_pairwise(pd.DataFrame(rows))
            kappa = res.get("mean_kappa")
            if kappa is not None:
                interp = interpret_kappa(kappa)
        except Exception as e:
            logger.warning(f"Judge alignment: kappa failed for {schema}: {e}")

        out[schema] = {
            "kappa": round(kappa, 3) if isinstance(kappa, (int, float)) else None,
            "interpretation": interp,
            "agreement_rate": round(agree / n, 3),
            "n": n,
            "confusion": {h: dict(js) for h, js in confusion.items()},
            "disagreements": disagreements,
        }
    return out


# ----- gathering from persisted predictions + live human labels -----------

def judge_scoped_schemas(config: Dict[str, Any]) -> List[dict]:
    """Annotation schemes the judge should evaluate (categorical only).

    Honors ``judge_alignment.schemas`` allow-list if present; otherwise all
    radio/select/likert schemes.
    """
    schemes = config.get("annotation_schemes", []) or []
    allow = set((config.get("judge_alignment", {}) or {}).get("schemas", {}).keys())
    cats = {"radio", "select", "likert"}
    out = []
    for s in schemes:
        if s.get("annotation_type") not in cats:
            continue
        if allow and s.get("name") not in allow:
            continue
        out.append(s)
    return out


def gather_pairs(config: Dict[str, Any], users: List[str], schema_names: List[str],
                 prompt_version: Optional[str]) -> Dict[str, List[Tuple]]:
    """Build (instance, human_gold, judge_label, conf, reasoning) pairs."""
    preds = load_predictions(config)
    version = prompt_version or latest_prompt_version(config)
    version_preds = preds.get(version, {}) if version else {}

    pairs_by_schema: Dict[str, List[Tuple]] = {s: [] for s in schema_names}
    for key, pred in version_preds.items():
        instance_id, _, schema = key.partition("::")
        if schema not in pairs_by_schema:
            continue
        gold = majority_human_label(instance_id, schema, users)
        if gold is None:
            continue
        pairs_by_schema[schema].append((
            instance_id, gold, pred.get("predicted_label"),
            pred.get("confidence"), pred.get("reasoning", ""),
        ))
    return pairs_by_schema


def annotated_instance_ids(users: List[str], schema_name: str) -> List[str]:
    """Instance ids that at least one user has labeled for this schema."""
    from potato.flask_server import get_user_state
    ids = set()
    for u in users:
        st = get_user_state(u)
        if not st:
            continue
        for iid in st.get_annotated_instance_ids():
            if human_label_for(iid, schema_name, u) is not None:
                ids.add(iid)
    return sorted(ids)


def run_judge_batch(config: Dict[str, Any], users: List[str],
                    rubric_overrides: Optional[Dict[str, str]] = None,
                    max_per_schema: Optional[int] = None) -> Dict[str, Any]:
    """Run the judge over human-annotated instances and persist predictions.

    rubric_overrides: {schema_name: rubric} to calibrate + create a new prompt
    version. Few-shot examples (when enabled) are drawn from high-agreement
    human labels, excluding the instance being judged.
    """
    from potato.ai.judge import JudgeService, compute_prompt_version
    from potato.item_state_management import get_item_state_manager

    # Apply rubric overrides into a working config copy.
    cfg = dict(config)
    ja = dict(cfg.get("judge_alignment", {}) or {})
    if rubric_overrides:
        schemas_cfg = dict(ja.get("schemas", {}) or {})
        for name, rubric in rubric_overrides.items():
            sc = dict(schemas_cfg.get(name, {}) or {})
            sc["rubric"] = rubric
            schemas_cfg[name] = sc
        ja["schemas"] = schemas_cfg
        cfg["judge_alignment"] = ja

    service = JudgeService(cfg)
    ism = get_item_state_manager()
    few_shot_cfg = (ja.get("few_shot") or {})
    use_few_shot = bool(few_shot_cfg.get("enabled", False))

    n_judged, n_failed, version_seen = 0, 0, None
    for schema in judge_scoped_schemas(cfg):
        schema_name = schema.get("name")
        ids = annotated_instance_ids(users, schema_name)
        if max_per_schema:
            ids = ids[:max_per_schema]
        examples = _few_shot_examples(schema_name, use_few_shot, few_shot_cfg)
        for iid in ids:
            try:
                item = ism.get_item(iid)
                text = item.get_text() if item else ""
            except Exception:
                text = ""
            shots = [e for e in examples if e.get("id") != iid] or None
            pred = service.judge_instance(iid, schema, text, few_shot_examples=shots)
            if pred is None:
                n_failed += 1
                continue
            save_prediction(cfg, pred)
            version_seen = pred.prompt_version
            n_judged += 1

    return {"judged": n_judged, "failed": n_failed, "prompt_version": version_seen}


def _few_shot_examples(schema_name: str, enabled: bool, cfg: Dict[str, Any]) -> List[dict]:
    """Gold few-shot examples from high-agreement human labels (or [])."""
    if not enabled:
        return []
    try:
        from potato.ai.icl_labeler import get_icl_labeler
        labeler = get_icl_labeler()
        if labeler is None:
            return []
        by_schema = labeler.refresh_high_confidence_examples()
        examples = by_schema.get(schema_name, [])[: int(cfg.get("max_examples", 5))]
        return [{"id": getattr(e, "instance_id", ""),
                 "text": getattr(e, "instance_text", getattr(e, "text", "")),
                 "label": getattr(e, "label", getattr(e, "agreed_label", ""))}
                for e in examples]
    except Exception as e:
        logger.warning(f"Judge few-shot example gathering failed: {e}")
        return []


def compute_judge_alignment(config: Dict[str, Any], users: List[str],
                            prompt_version: Optional[str] = None) -> Dict[str, Any]:
    """Full report: per-schema alignment for a prompt version + version list."""
    schemas = [s.get("name") for s in judge_scoped_schemas(config)]
    version = prompt_version or latest_prompt_version(config)
    pairs = gather_pairs(config, users, schemas, version)
    per_schema = compute_alignment_from_pairs(pairs)

    preds = load_predictions(config)
    versions = []
    for v in preds.keys():
        v_pairs = gather_pairs(config, users, schemas, v)
        v_report = compute_alignment_from_pairs(v_pairs)
        kappas = [r["kappa"] for r in v_report.values() if r.get("kappa") is not None]
        versions.append({
            "prompt_version": v,
            "n_predictions": len(preds[v]),
            "mean_kappa": round(sum(kappas) / len(kappas), 3) if kappas else None,
        })

    return {
        "prompt_version": version,
        "per_schema": per_schema,
        "prompt_versions": sorted(versions, key=lambda x: x["prompt_version"]),
    }
