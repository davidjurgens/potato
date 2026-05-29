"""
Schema-to-metric dispatcher and the top-level overlap-IAA report.

The dispatcher inspects a schema's ``annotation_type`` and (where relevant)
its labels block to decide which family of IAA metrics applies, then runs
those metrics across the overlap-sample items that have reached their cap.
"""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

import logging

from potato.server_utils.iaa import nominal, ordinal, continuous, multilabel, ranking, span, alpha

logger = logging.getLogger(__name__)


class SchemaKind(str, Enum):
    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    CONTINUOUS = "continuous"
    MULTILABEL = "multilabel"
    RANKING = "ranking"
    SPAN = "span"
    TEXT = "text"            # free-form text, no automatic IAA
    UNSUPPORTED = "unsupported"


_KIND_BY_TYPE = {
    # Nominal (single-label categorical)
    "radio": SchemaKind.NOMINAL,
    "select": SchemaKind.NOMINAL,
    "triage": SchemaKind.NOMINAL,
    # Ordinal
    "likert": SchemaKind.ORDINAL,
    "confidence": SchemaKind.ORDINAL,
    "semantic_differential": SchemaKind.ORDINAL,
    "range_slider": SchemaKind.ORDINAL,
    "vas": SchemaKind.ORDINAL,
    # Continuous
    "slider": SchemaKind.CONTINUOUS,
    "number": SchemaKind.CONTINUOUS,
    "multirate": SchemaKind.CONTINUOUS,
    "constant_sum": SchemaKind.CONTINUOUS,
    "soft_label": SchemaKind.CONTINUOUS,
    # Multi-label
    "multiselect": SchemaKind.MULTILABEL,  # may be downgraded to NOMINAL if max=1
    "hierarchical_multiselect": SchemaKind.MULTILABEL,
    "card_sort": SchemaKind.MULTILABEL,
    # Ranking
    "ranking": SchemaKind.RANKING,
    "bws": SchemaKind.RANKING,
    "pairwise": SchemaKind.RANKING,
    "conjoint": SchemaKind.RANKING,
    "best_worst_scaling": SchemaKind.RANKING,
    # Span
    "span": SchemaKind.SPAN,
    "error_span": SchemaKind.SPAN,
    "event_annotation": SchemaKind.SPAN,
    "coreference": SchemaKind.SPAN,
    "extractive_qa": SchemaKind.SPAN,
    "span_link": SchemaKind.SPAN,
    "tree_annotation": SchemaKind.SPAN,
    # Text
    "textbox": SchemaKind.TEXT,
    "text_edit": SchemaKind.TEXT,
    # Skipped
    "pure_display": SchemaKind.UNSUPPORTED,
    "video": SchemaKind.UNSUPPORTED,
    "audio_annotation": SchemaKind.UNSUPPORTED,
    "video_annotation": SchemaKind.UNSUPPORTED,
    "image_annotation": SchemaKind.UNSUPPORTED,
}


def classify_schema(scheme: Dict[str, Any]) -> SchemaKind:
    """Classify a schema definition into an IAA-relevant kind."""
    atype = (scheme.get("annotation_type") or "").strip().lower()
    kind = _KIND_BY_TYPE.get(atype, SchemaKind.UNSUPPORTED)
    # Downgrade multiselect with max_choices == 1 to NOMINAL
    if kind == SchemaKind.MULTILABEL and atype == "multiselect":
        max_choices = scheme.get("max_choices") or scheme.get("max_selections")
        if max_choices == 1:
            return SchemaKind.NOMINAL
    return kind


def metrics_for_schema(scheme: Dict[str, Any]) -> List[str]:
    """Return human-readable names of metrics that apply to ``scheme``."""
    kind = classify_schema(scheme)
    table = {
        SchemaKind.NOMINAL: ["percent_agreement", "cohen_kappa", "fleiss_kappa", "alpha_nominal"],
        SchemaKind.ORDINAL: ["weighted_kappa_linear", "weighted_kappa_quadratic", "spearman_rho", "alpha_ordinal"],
        SchemaKind.CONTINUOUS: ["pearson_r", "mae", "rmse", "alpha_interval", "icc_2_k"],
        SchemaKind.MULTILABEL: ["mean_jaccard", "alpha_masi"],
        SchemaKind.RANKING: ["kendall_tau", "spearman_footrule"],
        SchemaKind.SPAN: [
            "token_level_kappa", "span_f1_exact", "span_f1_partial",
            "krippendorff_alpha_u", "gamma_mathet",
        ],
        SchemaKind.TEXT: [],
        SchemaKind.UNSUPPORTED: [],
    }
    return list(table[kind])


# ---------------------------------------------------------------------------
# Data extraction from Potato's per-user annotation structures
# ---------------------------------------------------------------------------

def _label_value(label) -> Any:
    """Extract a comparable value from a Label object (or dict)."""
    if isinstance(label, dict):
        return label.get("name") or label.get("value")
    return getattr(label, "name", None) or getattr(label, "value", None)


def _gather_labels(
    instance_ids: Iterable[str],
    user_states: Dict[str, Any],
    schema_name: str,
):
    """
    Per item, return {user_id: <single value or list of values>} for one schema.

    For nominal/ordinal/continuous schemas the value is a scalar (the chosen
    label name or numeric rating). For multi-label schemas, it's a list.
    """
    rows: Dict[str, Dict[str, Any]] = {}
    for iid in instance_ids:
        per_user: Dict[str, Any] = {}
        for uid, ustate in user_states.items():
            labels_by_schema = ustate.get_label_annotations(iid)
            if not labels_by_schema:
                continue
            labels = labels_by_schema.get(schema_name)
            if not labels:
                continue
            vals = [_label_value(l) for l in labels]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            per_user[uid] = vals
        if per_user:
            rows[iid] = per_user
    return rows


def _gather_spans(
    instance_ids: Iterable[str],
    user_states: Dict[str, Any],
    schema_name: str,
):
    rows: Dict[str, Dict[str, list]] = {}
    for iid in instance_ids:
        per_user = {}
        for uid, ustate in user_states.items():
            spans_by_schema = ustate.get_span_annotations(iid)
            if not spans_by_schema:
                continue
            spans = spans_by_schema.get(schema_name) or []
            if not spans:
                continue
            per_user[uid] = list(spans)
        if per_user:
            rows[iid] = per_user
    return rows


def _text_length_for_item(item) -> int:
    """Best-effort character length of the item text used for span IAA."""
    if item is None:
        return 0
    try:
        text = item.get_text()
    except Exception:
        return 0
    return len(text) if isinstance(text, str) else 0


# ---------------------------------------------------------------------------
# Metric computation per kind
# ---------------------------------------------------------------------------

def _aggregate_nominal(rows):
    long_rows = []
    pairwise_kappa = []
    fleiss_inputs = []
    users_seen = set()
    for iid, per_user in rows.items():
        # Collapse multi-value into the first chosen label (single-label schema)
        flat = {u: v[0] for u, v in per_user.items() if v}
        if len(flat) < 2:
            continue
        users_seen.update(flat)
        for u, val in flat.items():
            long_rows.append((u, iid, val))
        fleiss_inputs.append(dict(Counter_(flat.values())))

    pair_users = sorted(users_seen)
    seqs_by_user: Dict[str, list] = {u: [] for u in pair_users}
    aligned_iids = []
    for iid, per_user in rows.items():
        flat = {u: v[0] for u, v in per_user.items() if v}
        if all(u in flat for u in pair_users):
            aligned_iids.append(iid)
            for u in pair_users:
                seqs_by_user[u].append(flat[u])

    return {
        "alpha_nominal": alpha.krippendorff_alpha(long_rows, level="nominal"),
        "fleiss_kappa": nominal.fleiss_kappa(fleiss_inputs),
        "pairwise_cohen_kappa": nominal.pairwise_cohen_kappa(seqs_by_user) if seqs_by_user else float("nan"),
        "n_items": len(rows),
        "n_aligned_items": len(aligned_iids),
        "n_annotators": len(pair_users),
    }


def _aggregate_ordinal(rows):
    long_rows = []
    seqs_by_user: Dict[str, list] = defaultdict(list)
    aligned_users = None
    for iid, per_user in rows.items():
        flat = {u: v[0] for u, v in per_user.items() if v}
        if len(flat) < 2:
            continue
        for u, val in flat.items():
            long_rows.append((u, iid, val))
        if aligned_users is None:
            aligned_users = set(flat)
        else:
            aligned_users &= set(flat)
        for u, val in flat.items():
            seqs_by_user[u].append(val)
    weighted_lin = _pairwise_mean(seqs_by_user, ordinal.weighted_kappa, weights="linear")
    weighted_quad = _pairwise_mean(seqs_by_user, ordinal.weighted_kappa, weights="quadratic")
    rho = _pairwise_mean(seqs_by_user, ordinal.spearman_rho)
    return {
        "weighted_kappa_linear": weighted_lin,
        "weighted_kappa_quadratic": weighted_quad,
        "spearman_rho": rho,
        "alpha_ordinal": alpha.krippendorff_alpha(long_rows, level="ordinal"),
        "n_items": len(rows),
        "n_annotators": len(seqs_by_user),
    }


def _aggregate_continuous(rows):
    long_rows = []
    seqs_by_user: Dict[str, list] = defaultdict(list)
    for iid, per_user in rows.items():
        flat = {}
        for u, v in per_user.items():
            try:
                flat[u] = float(v[0])
            except (TypeError, ValueError):
                continue
        if len(flat) < 2:
            continue
        for u, val in flat.items():
            long_rows.append((u, iid, val))
            seqs_by_user[u].append(val)

    pearson = _pairwise_mean(seqs_by_user, continuous.pearson_r)
    mae_val = _pairwise_mean(seqs_by_user, continuous.mae)
    rmse_val = _pairwise_mean(seqs_by_user, continuous.rmse)

    # ICC needs an items x raters matrix where every rater rates every item.
    users = sorted(seqs_by_user)
    aligned_iids = []
    matrix = []
    for iid, per_user in rows.items():
        try:
            row = [float(per_user[u][0]) for u in users]
        except (KeyError, TypeError, ValueError):
            continue
        matrix.append(row)
        aligned_iids.append(iid)
    icc_k = continuous.icc_2_k(matrix) if matrix and users else float("nan")

    return {
        "pearson_r": pearson,
        "mae": mae_val,
        "rmse": rmse_val,
        "alpha_interval": alpha.krippendorff_alpha(long_rows, level="interval"),
        "icc_2_k": icc_k,
        "n_items": len(rows),
        "n_aligned_items": len(aligned_iids),
        "n_annotators": len(users),
    }


def _aggregate_multilabel(rows):
    long_rows = []
    label_sets_by_user: Dict[str, list] = defaultdict(list)
    for iid, per_user in rows.items():
        flat = {u: frozenset(v) for u, v in per_user.items() if v}
        if len(flat) < 2:
            continue
        for u, val in flat.items():
            long_rows.append((u, iid, val))
            label_sets_by_user[u].append(val)
    return {
        "mean_jaccard": multilabel.mean_jaccard(label_sets_by_user),
        "alpha_masi": multilabel.alpha_masi(long_rows),
        "n_items": len(rows),
        "n_annotators": len(label_sets_by_user),
    }


def _aggregate_ranking(rows):
    seqs_by_user: Dict[str, list] = defaultdict(list)
    for iid, per_user in rows.items():
        flat = {u: list(v) for u, v in per_user.items() if v}
        if len(flat) < 2:
            continue
        for u, val in flat.items():
            seqs_by_user[u].append(val)
    tau = _pairwise_rank_mean(seqs_by_user, ranking.kendall_tau)
    footrule = _pairwise_rank_mean(seqs_by_user, ranking.spearman_footrule)
    return {
        "kendall_tau": tau,
        "spearman_footrule": footrule,
        "n_items": len(rows),
        "n_annotators": len(seqs_by_user),
    }


def _aggregate_span(span_rows, item_lookup):
    token_kappas = []
    f1_exact = []
    f1_partial = []
    alphas_u = []
    gammas = []
    n_items = 0
    annotators = set()
    for iid, per_user in span_rows.items():
        if len(per_user) < 2:
            continue
        item = item_lookup.get(iid)
        length = _text_length_for_item(item)
        if length <= 0:
            continue
        annotators.update(per_user)
        n_items += 1
        try:
            tk = span.token_level_kappa(per_user, length)
            if tk == tk:
                token_kappas.append(tk)
        except Exception as exc:
            logger.debug("token_level_kappa failed on %s: %s", iid, exc)
        try:
            exact = span.pairwise_span_f1(per_user, partial=False)
            partial = span.pairwise_span_f1(per_user, partial=True)
            if exact == exact:
                f1_exact.append(exact)
            if partial == partial:
                f1_partial.append(partial)
        except Exception as exc:
            logger.debug("span_f1 failed on %s: %s", iid, exc)
        try:
            au = span.krippendorff_alpha_u(per_user, length)
            if au == au:
                alphas_u.append(au)
        except Exception as exc:
            logger.debug("alpha_u failed on %s: %s", iid, exc)
        try:
            g = span.gamma(per_user, length=length)
            if g == g:
                gammas.append(g)
        except Exception as exc:
            logger.debug("gamma failed on %s: %s", iid, exc)

    def _mean(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    return {
        "token_level_kappa": _mean(token_kappas),
        "span_f1_exact": _mean(f1_exact),
        "span_f1_partial": _mean(f1_partial),
        "krippendorff_alpha_u": _mean(alphas_u),
        "gamma_mathet": _mean(gammas),
        "n_items": n_items,
        "n_annotators": len(annotators),
    }


# ---------------------------------------------------------------------------
# Pairwise helpers
# ---------------------------------------------------------------------------

def _pairwise_mean(seqs_by_user, fn, **kwargs):
    users = list(seqs_by_user)
    if len(users) < 2:
        return float("nan")
    out = []
    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            a = seqs_by_user[users[i]]
            b = seqs_by_user[users[j]]
            m = min(len(a), len(b))
            if m < 2:
                continue
            try:
                v = fn(a[:m], b[:m], **kwargs) if kwargs else fn(a[:m], b[:m])
                if v == v:
                    out.append(v)
            except Exception as exc:
                logger.debug("pairwise metric %s failed: %s", fn.__name__, exc)
    return sum(out) / len(out) if out else float("nan")


def _pairwise_rank_mean(seqs_by_user, fn):
    users = list(seqs_by_user)
    if len(users) < 2:
        return float("nan")
    out = []
    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            a = seqs_by_user[users[i]]
            b = seqs_by_user[users[j]]
            m = min(len(a), len(b))
            for k in range(m):
                try:
                    v = fn(a[k], b[k])
                    if v == v:
                        out.append(v)
                except Exception:
                    continue
    return sum(out) / len(out) if out else float("nan")


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def compute_overlap_iaa(item_state_manager, user_state_manager, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute IAA across the overlap-sample items that have reached their cap.

    Returns a dict shape:
        {
            "schemas": {
                "<schema_name>": {
                    "kind": "<SchemaKind value>",
                    "annotation_type": "<from config>",
                    "metrics": { <metric>: <float|null>, ... },
                    "n_items": int,
                    "n_annotators": int,
                }
            },
            "items": {
                "<instance_id>": {
                    "annotators": [...],
                    "cap": int,
                    "schemas": {
                        "<schema_name>": { ... per-item metric breakdown ... }
                    }
                }
            },
            "n_overlap_items": int,
        }
    """
    schemes = _extract_schemes(config)
    if not schemes:
        return {"schemas": {}, "items": {}, "n_overlap_items": 0}

    # Overlap items: per-item cap >= 2 AND saturated.
    overlap_items = []
    for iid, item in item_state_manager.instance_id_to_instance.items():
        cap = item_state_manager._get_annotator_cap_for_item(iid)
        if cap is None or cap < 2:
            continue
        if len(item_state_manager.instance_annotators[iid]) < cap:
            continue
        overlap_items.append(iid)

    # Build {user_id: user_state} for users who touched any overlap item.
    relevant_user_ids = set()
    for iid in overlap_items:
        relevant_user_ids.update(item_state_manager.instance_annotators[iid])
    user_states = {}
    for uid in relevant_user_ids:
        ustate = user_state_manager.get_user_state(uid) if hasattr(user_state_manager, "get_user_state") else None
        if ustate is not None:
            user_states[uid] = ustate

    schema_report: Dict[str, Any] = {}
    item_report: Dict[str, Any] = {iid: {
        "annotators": sorted(item_state_manager.instance_annotators[iid]),
        "cap": item_state_manager._get_annotator_cap_for_item(iid),
        "schemas": {},
    } for iid in overlap_items}

    for scheme in schemes:
        name = scheme.get("name")
        if not name:
            continue
        kind = classify_schema(scheme)
        if kind in (SchemaKind.TEXT, SchemaKind.UNSUPPORTED):
            continue
        if kind == SchemaKind.SPAN:
            rows = _gather_spans(overlap_items, user_states, name)
            metrics = _aggregate_span(rows, item_state_manager.instance_id_to_instance)
        else:
            rows = _gather_labels(overlap_items, user_states, name)
            if kind == SchemaKind.NOMINAL:
                metrics = _aggregate_nominal(rows)
            elif kind == SchemaKind.ORDINAL:
                metrics = _aggregate_ordinal(rows)
            elif kind == SchemaKind.CONTINUOUS:
                metrics = _aggregate_continuous(rows)
            elif kind == SchemaKind.MULTILABEL:
                metrics = _aggregate_multilabel(rows)
            elif kind == SchemaKind.RANKING:
                metrics = _aggregate_ranking(rows)
            else:
                continue
        schema_report[name] = {
            "kind": kind.value,
            "annotation_type": scheme.get("annotation_type"),
            "metrics": metrics,
        }
        for iid in rows if kind != SchemaKind.SPAN else rows:
            item_report.setdefault(iid, {"annotators": [], "cap": -1, "schemas": {}})
            item_report[iid]["schemas"][name] = {"n_annotators": len(rows[iid])}

    return {
        "schemas": schema_report,
        "items": item_report,
        "n_overlap_items": len(overlap_items),
    }


def _extract_schemes(config: Dict[str, Any]):
    """Pull annotation_schemes from the config (top-level or under a phase)."""
    if "annotation_schemes" in config and isinstance(config["annotation_schemes"], list):
        return config["annotation_schemes"]
    schemes = []
    phases = config.get("phases", {}) or {}
    for key, val in phases.items():
        if isinstance(val, dict) and isinstance(val.get("annotation_schemes"), list):
            schemes.extend(val["annotation_schemes"])
    return schemes


# Local imports placed at the bottom to avoid circular imports at module load.
from collections import Counter as Counter_  # noqa: E402
