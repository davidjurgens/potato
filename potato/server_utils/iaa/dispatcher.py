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
    GEOMETRY = "geometry"    # 2D shapes: boxes, polygons, masks, points
    TEMPORAL = "temporal"    # labelled time ranges: audio and video segments
    EPISODE = "episode"      # robot demonstrations: phases + outcome + reward
    ROLLOUT = "rollout"      # world-model rollouts: break-points + preference
    CAPTION = "caption"      # free text about a region: agreement over meaning
    GROUNDING = "grounding"  # referring expression -> region: detection + where
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
    # Geometry / temporal (stored as a JSON blob under a single ``_data`` key)
    "image_annotation": SchemaKind.GEOMETRY,
    "audio_annotation": SchemaKind.TEMPORAL,
    "video_annotation": SchemaKind.TEMPORAL,
    "episode_annotation": SchemaKind.EPISODE,
    "rollout_evaluation": SchemaKind.ROLLOUT,
    "region_caption": SchemaKind.CAPTION,
    "grounding_eval": SchemaKind.GROUNDING,
    # Skipped
    "pure_display": SchemaKind.UNSUPPORTED,
    "video": SchemaKind.UNSUPPORTED,
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
        SchemaKind.GEOMETRY: [
            "mean_agreement", "mean_matched_iou", "detection_f1",
            "mean_object_count_diff",
            # Chance-corrected, and the ones to quote in a paper.
            "sigma", "ks", "detection_alpha", "classification_alpha",
        ],
        SchemaKind.TEMPORAL: [
            "mean_agreement", "mean_matched_iou", "detection_f1",
            "mean_object_count_diff",
        ],
        # Three groups rather than a flat list, because an episode annotation
        # is three different kinds of answer and blending them would hide which
        # one the annotators disagreed about -- and they have different fixes.
        SchemaKind.EPISODE: [
            "phases.mean_agreement", "phases.mean_matched_iou",
            "phases.detection_f1",
            "outcome.outcome_alpha",
            "reward.reward_icc", "reward.reward_pearson_r",
            "reward.reward_coverage",
        ],
        # Four groups, and a tolerance sweep behind them. Reporting one number
        # would hide which of "does it break", "when", "why" and "how badly"
        # the annotators disagreed about, and every one of them depends on the
        # tolerance window the sweep varies.
        SchemaKind.ROLLOUT: [
            "detection.alpha", "localization.mean_offset",
            "localization.sigma", "localization.ks",
            "category.alpha", "severity.alpha",
            "preference.alpha", "counterfactual.alpha",
            "coverage.answered_fraction",
        ],
        # Alpha plus the RAW mean distance, because alpha is chance-corrected
        # and this is not: a corpus whose captions are all near-identical can
        # have an undefined or negative alpha alongside excellent raw
        # agreement, and only the pair explains what happened.
        SchemaKind.CAPTION: [
            "alpha", "mean_pairwise_distance",
            "matching.n_matched_regions", "matching.n_unmatched_regions",
        ],
        # Three groups, because "is it there", "where is it" and "did anyone
        # answer" are separate findings with separate fixes: a low detection
        # alpha means the expression is ambiguous, a low localization score
        # means the drawing is sloppy, and low coverage means neither number
        # rests on much. `pointing` appears only for `region_type: point`,
        # where IoU is meaningless and distance replaces it.
        SchemaKind.GROUNDING: [
            "detection.alpha", "detection.percent_agreement",
            "localization.mean_iou", "localization.median_iou",
            "pointing.mean_pairwise_distance",
            "coverage.answered_fraction",
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


def _schema_values(ustate, instance_id: str, schema_name: str):
    """
    ``{label_name: value}`` for one schema on one item, or ``None``.

    ``get_label_annotations`` returns the *flat* ``{Label: value}`` container,
    not a mapping keyed by schema name. Regrouping is shared with adjudication
    via :func:`annotation_values.group_by_schema` so the two cannot drift.
    """
    from potato.server_utils import annotation_values

    stored = ustate.get_label_annotations(instance_id)
    if not stored:
        return None
    return annotation_values.group_by_schema(stored).get(schema_name)


def _gather_labels(
    instance_ids: Iterable[str],
    user_states: Dict[str, Any],
    schema_name: str,
    numeric: bool = False,
):
    """
    Per item, return {user_id: [values]} for one schema.

    The value of a categorical answer is the *label name* whose stored value is
    truthy: radio stores ``{"positive": True}`` and likert ``{"2": "2"}``, so in
    both the name carries the answer.

    Historically this looked the schema up by name in the flat ``{Label: value}``
    container. A string never hashes to a ``Label``, so the lookup always missed
    and every metric in this module reported NaN over zero items for every
    schema of every kind. Fixed here; pinned by
    ``tests/unit/test_iaa_dispatcher_gathering.py``.
    """
    from potato.server_utils import annotation_values

    rows: Dict[str, Dict[str, Any]] = {}
    for iid in instance_ids:
        per_user: Dict[str, Any] = {}
        for uid, ustate in user_states.items():
            values = _schema_values(ustate, iid, schema_name)
            if not values:
                continue
            names = annotation_values.selected_labels(values)
            if not names:
                continue
            if numeric:
                vals = [v for v in (_as_number(n, values) for n in names)
                        if v is not None]
                if not vals:
                    continue
            else:
                vals = names
            per_user[uid] = vals
        if per_user:
            rows[iid] = per_user
    return rows


def _as_number(name: str, values: Any) -> Optional[float]:
    """
    Numeric reading of one selected option.

    Likert-style schemas put the number in the label *name* (``{"2": "2"}``);
    sliders and number inputs put it in the stored *value*. Try the name first,
    then the value, rather than assuming either.
    """
    try:
        return float(name)
    except (TypeError, ValueError):
        pass
    if isinstance(values, dict):
        try:
            return float(values.get(name))
        except (TypeError, ValueError):
            return None
    return None


def _gather_blobs(
    instance_ids: Iterable[str],
    user_states: Dict[str, Any],
    schema_name: str,
    scheme: Dict[str, Any],
):
    """
    Per item, return {user_id: [canonical objects]} for a ``_data``-blob schema.

    Image, audio, video and tiered annotation all serialize through the same
    ``annotation-data-input`` convention — one JSON string under a ``_data``
    label — so one gatherer covers every modality and
    ``annotation_values.comparable_value`` decides whether that blob becomes 2D
    shapes or timeline segments.
    """
    from potato.server_utils import annotation_values

    rows: Dict[str, Dict[str, Any]] = {}
    for iid in instance_ids:
        per_user: Dict[str, Any] = {}
        for uid, ustate in user_states.items():
            values = _schema_values(ustate, iid, schema_name)
            if values is None:
                continue
            objects = annotation_values.comparable_value(scheme, values)
            if not isinstance(objects, list):
                continue
            # An empty list is a real answer ("nothing here"), so it is kept:
            # two annotators who both find nothing agree.
            per_user[uid] = objects
        if len(per_user) >= 2:
            rows[iid] = per_user
    return rows


def _gather_raw(
    instance_ids: Iterable[str],
    user_states: Dict[str, Any],
    schema_name: str,
):
    """
    Per item, ``{user_id: stored_value}`` with no interpretation at all.

    For schemas whose blob holds several independent layers, where deciding
    what "the value" is belongs to the measure rather than to the gatherer.
    """
    rows: Dict[str, Dict[str, Any]] = {}
    for iid in instance_ids:
        per_user = {}
        for uid, ustate in user_states.items():
            values = _schema_values(ustate, iid, schema_name)
            if values is None:
                continue
            per_user[uid] = values
        if len(per_user) >= 2:
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


def _aggregate_blobs(rows, scheme: Dict[str, Any], match_threshold: float = 0.5):
    """
    Agreement over 2D shapes or timeline segments.

    Four numbers, because annotators disagree in distinguishable ways and one
    scalar would hide which:

    ``mean_agreement``          overall, penalizing both bad boundaries and
                                missed objects (the measure adjudication routes on)
    ``mean_matched_iou``        boundary quality *given* both annotators found
                                the object — high here with low detection_f1
                                means they draw well but miss things
    ``detection_f1``            did they find the same objects at all
    ``mean_object_count_diff``  the crudest signal, and often the first to move

    Deliberately **not** Krippendorff's alpha over IoU. Because IoU distance is
    bounded in [0, 1], randomly paired shapes saturate at distance ~1, expected
    disagreement collapses to ~1, and alpha degenerates to ``1 - mean distance``
    with no working chance correction. Braylan, Alonso & Lease (WWW 2022,
    arXiv:2212.09503) measured the consequence on exactly these tasks: alpha
    ranks L2 (0.687) above IoU (0.505) and GIoU (0.507) for bounding boxes,
    inverting the ordering their distribution-based measures and practitioners
    both give. Chance-corrected detection/classification alpha and the
    sigma/KS measures are tracked separately.
    """
    from potato.server_utils import annotation_values
    from potato.server_utils.iaa import geometry

    temporal = annotation_values.supports_temporal(scheme)
    sim_fn = geometry.temporal_similarity if temporal else None

    agreements: List[float] = []
    matched_ious: List[float] = []
    detection_f1s: List[float] = []
    count_diffs: List[float] = []
    annotators = set()
    n_items = 0

    for iid, per_user in rows.items():
        users = sorted(per_user)
        if len(users) < 2:
            continue
        annotators.update(users)
        n_items += 1
        for i in range(len(users)):
            for j in range(i + 1, len(users)):
                a = per_user[users[i]]
                b = per_user[users[j]]

                d = annotation_values.distance(scheme, a, b, match_threshold)
                if d is not None:
                    agreements.append(1.0 - d)

                count_diffs.append(abs(len(a) - len(b)))

                if not a or not b:
                    # One annotator marked nothing. Detection F1 is 1.0 only when
                    # BOTH found nothing; otherwise it is a total detection miss.
                    detection_f1s.append(1.0 if not a and not b else 0.0)
                    continue

                matches, _un_a, _un_b = geometry.match_instances(
                    a, b, match_threshold, sim_fn=sim_fn)
                detection_f1s.append(2.0 * len(matches) / (len(a) + len(b)))
                matched_ious.extend(score for _i, _j, score in matches)

    def _mean(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    result = {
        "mean_agreement": _mean(agreements),
        "mean_matched_iou": _mean(matched_ious),
        "detection_f1": _mean(detection_f1s),
        "mean_object_count_diff": _mean(count_diffs),
        "n_items": n_items,
        "n_annotators": len(annotators),
    }

    # The chance-corrected measures this docstring promised. Spatial only:
    # the sigma baseline is built from between-ITEM distances, and for temporal
    # segments "a segment from another clip" is not a meaningful comparison
    # when clips differ in length.
    if not temporal and n_items:
        try:
            from potato.server_utils.iaa import geometry_agreement as ga

            report = ga.geometry_agreement(rows, threshold=match_threshold)
            result["sigma"] = report["localization"]["sigma"]
            result["ks"] = report["localization"]["ks"]
            result["detection_alpha"] = report["detection"]["alpha"]
            result["classification_alpha"] = report["classification"]["alpha"]
            # Carry the reasons through: a bare NaN in an admin table cannot
            # be told apart from a broken computation.
            for source, key in (("detection", "detection_alpha_note"),
                                ("classification", "classification_alpha_note")):
                note = report[source].get("undefined_because")
                if note:
                    result[key] = note
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("geometry agreement failed: %s", exc)

    return result


def _parse_caption_rows(rows):
    """
    ``{item: {annotator: [{"region", "caption"}]}}`` from the stored blobs.

    Parsed here rather than in the measure because the measure is also called
    directly with already-parsed data by tests and by analysis scripts, and a
    function that accepted both shapes would have to guess which it got.
    """
    import json as _json

    parsed = {}
    for item_id, per_user in rows.items():
        entries = {}
        for user_id, stored in per_user.items():
            value = stored
            if isinstance(value, dict):
                value = next(iter(value.values()), None)
            if isinstance(value, str):
                try:
                    value = _json.loads(value)
                except ValueError:
                    continue
            if isinstance(value, dict):
                captions = value.get("captions")
                if isinstance(captions, list):
                    entries[user_id] = captions
        if len(entries) >= 2:
            parsed[item_id] = entries
    return parsed


def _aggregate_span(span_rows, find_item):
    """``find_item`` is a ``id -> Item or None`` callable, not a mapping: the
    span length has to come from the item, and a mapping would have to be
    materialized first — see potato/item_store.py."""
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
        item = find_item(iid)
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
    for iid, item in item_state_manager.iter_items():
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
            metrics = _aggregate_span(rows, item_state_manager.find_item)
        elif kind == SchemaKind.EPISODE:
            from potato.server_utils.iaa import episodes as episode_iaa
            # The raw stored blob, not a pre-parsed one: the episode report
            # parses each layer itself so it cannot drift from what the
            # timeline wrote.
            rows = _gather_raw(overlap_items, user_states, name)
            metrics = episode_iaa.episode_report(rows, scheme)
        elif kind == SchemaKind.CAPTION:
            from potato.server_utils.iaa import captions as caption_iaa

            rows = _gather_raw(overlap_items, user_states, name)
            metrics = caption_iaa.region_caption_report(
                _parse_caption_rows(rows),
                distance=(scheme.get("agreement_distance") or "token"))
        elif kind == SchemaKind.GROUNDING:
            from potato.server_utils.iaa import grounding as grounding_iaa
            # Raw, like the episode and rollout reports: the blob holds three
            # independent layers and the measure that scores each one parses it,
            # so the report cannot drift from what the client wrote.
            rows = _gather_raw(overlap_items, user_states, name)
            metrics = grounding_iaa.grounding_report(rows, scheme)
        elif kind == SchemaKind.ROLLOUT:
            from potato.server_utils.iaa import rollouts as rollout_iaa
            # Raw for the same reason the episode report takes it raw: the four
            # layers are parsed by the measure that scores them, so the report
            # cannot drift from what the client wrote.
            rows = _gather_raw(overlap_items, user_states, name)
            metrics = rollout_iaa.rollout_report(rows, scheme)
        elif kind in (SchemaKind.GEOMETRY, SchemaKind.TEMPORAL):
            rows = _gather_blobs(overlap_items, user_states, name, scheme)
            metrics = _aggregate_blobs(rows, scheme)
        else:
            rows = _gather_labels(overlap_items, user_states, name,
                                  numeric=(kind == SchemaKind.CONTINUOUS))
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


def json_safe(value: Any) -> Any:
    """
    Replace NaN/Infinity with ``None`` so a report can be serialized as JSON.

    An undefined metric is legitimately NaN in Python, but ``NaN`` is **not
    valid JSON** (RFC 8259). Python's own ``json`` emits the bare token and its
    own loader accepts it, which hides the problem locally — but simplejson,
    Go, Rust and, critically, the browser's ``JSON.parse`` all reject it. So
    ``/admin/iaa`` produced a response strict clients could not read at all,
    and before the gathering fix every metric was NaN, meaning *every* response.

    ``null`` is also the more honest encoding: "this metric is not defined for
    this data", rather than a number that happens to compare false with itself.
    """
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and (value != value or value in (
            float("inf"), float("-inf"))):
        return None
    return value


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
