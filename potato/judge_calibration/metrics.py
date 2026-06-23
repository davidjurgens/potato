"""
Metrics for judge calibration.

Pure(ish) functions that take plain label dictionaries and produce the report
numbers: per-model accuracy/precision/recall/F1 vs human gold, inter-annotator
agreement (Cohen's kappa pairwise — partitioned into human<->LLM / LLM<->LLM /
human<->human, plus Fleiss' kappa and Krippendorff's alpha over all raters),
per-model confusion matrices, calibration (ECE/Brier/reliability), and — for
likert — mean absolute error.

IAA reuses ``potato.agreement`` (cohen_kappa_pairwise / fleiss_kappa /
interpret_kappa). Krippendorff uses simpledorff (nominal for radio, interval
for likert — this build of simpledorff ships nominal_metric + interval_metric
only; interval is used as the ordinal proxy).

Inputs (all keyed by instance id):
    llm_modal:    {model_name: {iid: label}}
    llm_conf:     {model_name: {iid: confidence}}
    human_labels: {human_id:  {iid: label}}
Single-label schemas (radio/select/likert) are supported here; multiselect and
span get their own handling in later phases.
"""

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from potato.agreement import cohen_kappa_pairwise, fleiss_kappa, interpret_kappa
from potato.judge_calibration.calibration import calibration_report

logger = logging.getLogger(__name__)

LLM_PREFIX = "llm::"
HUMAN_PREFIX = "human::"


# ----- gold resolution ----------------------------------------------------

def _majority(labels: List[Any]) -> Optional[Any]:
    """Most common label; ties broken by sorted string order (deterministic)."""
    if not labels:
        return None
    counts = Counter(str(l) for l in labels)
    top = max(counts.values())
    winners = sorted(k for k, v in counts.items() if v == top)
    winner_str = winners[0]
    return next(l for l in labels if str(l) == winner_str)


def resolve_gold(human_labels: Dict[str, Dict[str, Any]], gold_strategy: str) -> Dict[str, Any]:
    """Per-instance human gold label."""
    humans = sorted(human_labels.keys())
    if not humans:
        return {}
    if gold_strategy == "single" or len(humans) == 1:
        if len(humans) > 1:
            logger.info("judge_calibration: gold=single with %d humans; using '%s'",
                        len(humans), humans[0])
        return dict(human_labels[humans[0]])

    # majority across humans
    all_iids = set()
    for h in humans:
        all_iids.update(human_labels[h].keys())
    gold = {}
    for iid in all_iids:
        votes = [human_labels[h][iid] for h in humans if iid in human_labels[h]]
        m = _majority(votes)
        if m is not None:
            gold[iid] = m
    return gold


# ----- classification metrics --------------------------------------------

def _classification_metrics(y_true: List[str], y_pred: List[str], valid_labels: List[str]) -> Dict[str, Any]:
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support, confusion_matrix

    labels = valid_labels or sorted(set(y_true) | set(y_pred))
    acc = float(accuracy_score(y_true, y_pred)) if y_true else 0.0
    p, r, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0
    )
    pw, rw, f1w, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="weighted", zero_division=0
    )
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    confusion = {
        gold: {pred: int(cm[i][j]) for j, pred in enumerate(labels)}
        for i, gold in enumerate(labels)
    }
    return {
        "accuracy": round(acc, 6),
        "precision_macro": round(float(p), 6),
        "recall_macro": round(float(r), 6),
        "f1_macro": round(float(f1), 6),
        "precision_weighted": round(float(pw), 6),
        "recall_weighted": round(float(rw), 6),
        "f1_weighted": round(float(f1w), 6),
        "confusion_matrix": confusion,
        "labels": labels,
        "n": len(y_true),
    }


def _mae(y_true: List[str], y_pred: List[str]) -> Optional[float]:
    """Mean absolute error for numeric (likert) labels; None if non-numeric."""
    try:
        diffs = [abs(float(t) - float(p)) for t, p in zip(y_true, y_pred)]
    except (TypeError, ValueError):
        return None
    return round(sum(diffs) / len(diffs), 6) if diffs else None


# ----- IAA ----------------------------------------------------------------

def _build_reliability_df(
    llm_modal: Dict[str, Dict[str, Any]],
    human_labels: Dict[str, Dict[str, Any]],
):
    import pandas as pd

    rows = []
    for model, preds in llm_modal.items():
        for iid, label in preds.items():
            if label is None:
                continue
            rows.append({"unit": iid, "annotator": LLM_PREFIX + model, "annotation": str(label)})
    for human, preds in human_labels.items():
        for iid, label in preds.items():
            if label is None:
                continue
            rows.append({"unit": iid, "annotator": HUMAN_PREFIX + human, "annotation": str(label)})
    return pd.DataFrame(rows, columns=["unit", "annotator", "annotation"])


def _pair_kind(a: str, b: str) -> str:
    a_llm, b_llm = a.startswith(LLM_PREFIX), b.startswith(LLM_PREFIX)
    if a_llm and b_llm:
        return "llm_llm"
    if (not a_llm) and (not b_llm):
        return "human_human"
    return "human_llm"


def compute_iaa(
    llm_modal: Dict[str, Dict[str, Any]],
    human_labels: Dict[str, Dict[str, Any]],
    ordinal: bool = False,
) -> Dict[str, Any]:
    df = _build_reliability_df(llm_modal, human_labels)
    if df.empty:
        return {"cohen": {}, "fleiss": {}, "krippendorff": None}

    cohen = cohen_kappa_pairwise(df)
    # Partition pairs by rater kind.
    partitioned = {"human_llm": [], "llm_llm": [], "human_human": []}
    for pair in cohen.get("pairs", []):
        kind = _pair_kind(pair["annotator_a"], pair["annotator_b"])
        partitioned[kind].append(pair)

    def _mean(pairs):
        ks = [p["kappa"] for p in pairs]
        return round(sum(ks) / len(ks), 4) if ks else None

    fleiss = fleiss_kappa(df)

    krippendorff = None
    try:
        import simpledorff
        from simpledorff.metrics import nominal_metric, interval_metric
        kdf = df.copy()
        metric_fn = nominal_metric
        if ordinal:
            try:
                kdf["annotation"] = kdf["annotation"].astype(float)
                metric_fn = interval_metric
            except (TypeError, ValueError):
                metric_fn = nominal_metric
        alpha = simpledorff.calculate_krippendorffs_alpha_for_df(
            kdf, experiment_col="unit", annotator_col="annotator",
            class_col="annotation", metric_fn=metric_fn,
        )
        krippendorff = {
            "alpha": round(float(alpha), 4),
            "metric": "interval" if (ordinal and metric_fn is interval_metric) else "nominal",
            "interpretation": interpret_kappa(float(alpha)),
        }
    except Exception as e:
        logger.warning("judge_calibration: krippendorff failed: %s", e)

    return {
        "cohen": {
            "mean_kappa": cohen.get("mean_kappa"),
            "mean_human_llm": _mean(partitioned["human_llm"]),
            "mean_llm_llm": _mean(partitioned["llm_llm"]),
            "mean_human_human": _mean(partitioned["human_human"]),
            "pairs": cohen.get("pairs", []),
        },
        "fleiss": fleiss,
        "krippendorff": krippendorff,
    }


# ----- multiselect --------------------------------------------------------

def _jaccard(a, b) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 1.0


def _mean_pairwise_jaccard(
    rater_labels: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Mean pairwise Jaccard agreement, partitioned by rater kind."""
    from itertools import combinations

    raters = sorted(rater_labels.keys())
    partitioned = {"human_llm": [], "llm_llm": [], "human_human": []}
    all_scores = []
    for a, b in combinations(raters, 2):
        shared = set(rater_labels[a]) & set(rater_labels[b])
        if not shared:
            continue
        score = sum(_jaccard(rater_labels[a][i], rater_labels[b][i]) for i in shared) / len(shared)
        all_scores.append(score)
        partitioned[_pair_kind(a, b)].append(score)

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "mean_jaccard": _mean(all_scores),
        "mean_human_llm": _mean(partitioned["human_llm"]),
        "mean_llm_llm": _mean(partitioned["llm_llm"]),
        "mean_human_human": _mean(partitioned["human_human"]),
    }


def compute_multiselect_report(
    schema_name: str,
    valid_labels: List[str],
    llm_modal: Dict[str, Dict[str, Any]],
    llm_conf: Dict[str, Dict[str, float]],
    human_labels: Dict[str, Dict[str, Any]],
    gold_strategy: str = "single",
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Per-label P/R/F1 + mean Jaccard + set-match calibration for multiselect."""
    from sklearn.metrics import precision_recall_fscore_support
    from sklearn.preprocessing import MultiLabelBinarizer
    from potato.judge_calibration.calibration import calibration_report

    # gold: per-instance set (majority = union of labels appearing in >half of raters)
    humans = sorted(human_labels.keys())
    gold: Dict[str, Any] = {}
    if humans:
        if gold_strategy == "single" or len(humans) == 1:
            gold = {iid: set(v) for iid, v in human_labels[humans[0]].items()}
        else:
            all_iids = set().union(*[set(human_labels[h]) for h in humans])
            for iid in all_iids:
                votes = Counter()
                raters_for = 0
                for h in humans:
                    if iid in human_labels[h]:
                        raters_for += 1
                        for lab in human_labels[h][iid]:
                            votes[lab] += 1
                gold[iid] = {lab for lab, c in votes.items() if c > raters_for / 2}

    mlb = MultiLabelBinarizer(classes=valid_labels)
    mlb.fit([valid_labels])

    per_model = {}
    for model, preds in llm_modal.items():
        overlap = sorted(iid for iid in preds if iid in gold)
        if not overlap:
            per_model[model] = {"n": 0}
            continue
        y_true = mlb.transform([sorted(gold[iid]) for iid in overlap])
        y_pred = mlb.transform([sorted(preds[iid] or []) for iid in overlap])
        p, r, f1, _ = precision_recall_fscore_support(
            y_true, y_pred, average="macro", zero_division=0)
        pmi, rmi, f1mi, _ = precision_recall_fscore_support(
            y_true, y_pred, average="micro", zero_division=0)
        jacc = sum(_jaccard(preds[iid], gold[iid]) for iid in overlap) / len(overlap)

        conf = llm_conf.get(model, {})
        confidences = [float(conf.get(iid, 0.0)) for iid in overlap]
        correctness = [1 if set(preds[iid] or []) == set(gold[iid]) else 0 for iid in overlap]

        per_model[model] = {
            "precision_macro": round(float(p), 6),
            "recall_macro": round(float(r), 6),
            "f1_macro": round(float(f1), 6),
            "f1_micro": round(float(f1mi), 6),
            "mean_jaccard": round(jacc, 6),
            "exact_match_accuracy": round(sum(correctness) / len(correctness), 6),
            "calibration": calibration_report(confidences, correctness, n_bins),
            "labels": valid_labels,
            "n": len(overlap),
        }

    # IAA via mean pairwise Jaccard across all raters
    rater_labels = {LLM_PREFIX + m: {i: set(v or []) for i, v in d.items()}
                    for m, d in llm_modal.items()}
    for h, d in human_labels.items():
        rater_labels[HUMAN_PREFIX + h] = {i: set(v or []) for i, v in d.items()}

    return {
        "schema": schema_name,
        "annotation_type": "multiselect",
        "n_gold": len(gold),
        "gold_strategy": gold_strategy,
        "per_model": per_model,
        "iaa": {"jaccard": _mean_pairwise_jaccard(rater_labels)},
    }


# ----- span (EXPERIMENTAL) ------------------------------------------------

def _match_spans(pred: List[dict], gold: List[dict], iou_threshold: float):
    """Greedy IoU matching of predicted spans to gold spans (same label).

    Returns (tp, fp, fn, matched_ious, matched_pred_flags). Each predicted span
    is a dict with start/end/label (+ optional confidence); matched_pred_flags
    is a list aligned to `pred` indicating which predicted spans matched a gold.
    """
    from potato.judge_calibration.aggregation import span_iou

    used_gold = set()
    matched_ious = []
    matched_pred = [False] * len(pred)
    for pi, p in enumerate(pred):
        best_iou, best_gi = 0.0, None
        for gi, g in enumerate(gold):
            if gi in used_gold or g.get("label") != p.get("label"):
                continue
            iou = span_iou((p["start"], p["end"]), (g["start"], g["end"]))
            if iou >= iou_threshold and iou > best_iou:
                best_iou, best_gi = iou, gi
        if best_gi is not None:
            used_gold.add(best_gi)
            matched_ious.append(best_iou)
            matched_pred[pi] = True
    tp = len(matched_ious)
    fp = len(pred) - tp
    fn = len(gold) - tp
    return tp, fp, fn, matched_ious, matched_pred


def span_prf(predicted: List[dict], gold: List[dict],
             iou_threshold: float = 0.5) -> Dict[str, float]:
    """Public IoU-matched span precision/recall/F1 (judge-vs-human or rater-pair).

    Promotes the previously-internal span matcher to a supported entry point used
    by the LLM-judge span path (``potato.ai.judge.score_spans``).
    """
    tp, fp, fn, matched_ious, _ = _match_spans(predicted, gold, iou_threshold)
    out = _prf(tp, fp, fn)
    out["mean_iou"] = round(sum(matched_ious) / len(matched_ious), 6) if matched_ious else 0.0
    return out


def _prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6)}


def _pairwise_span_f1(a: Dict[str, List[dict]], b: Dict[str, List[dict]], iou_threshold: float):
    """Symmetric span-F1 agreement between two raters over shared instances."""
    shared = set(a) & set(b)
    if not shared:
        return None
    tp = fp = fn = 0
    for iid in shared:
        t, f_p, f_n, _, _ = _match_spans(a[iid], b[iid], iou_threshold)
        tp += t; fp += f_p; fn += f_n
    return _prf(tp, fp, fn)["f1"]


def _to_units(spans: List[dict]):
    """Convert span dicts to (start, end, label) tuples."""
    return [(int(s["start"]), int(s["end"]), str(s["label"])) for s in spans]


def _segment_label(seg_lo: int, seg_hi: int, units) -> str:
    """Label of the span covering an atomic segment, or 'O' (outside)."""
    for (s, e, lab) in units:
        if s <= seg_lo and e >= seg_hi:
            return lab
    return "O"


def compute_span_token_iaa(rater_units: Dict[str, Dict[str, list]]) -> Dict[str, Any]:
    """Chance-corrected span agreement via atomic-segment projection.

    Each instance is cut at every span boundary any annotator drew; each atomic
    segment gets that annotator's label (or 'O'). Standard Cohen/Fleiss κ and
    Krippendorff α (nominal) then run over the (instance:segment, annotator,
    label) table. Only segments inside the union of annotated regions are
    considered, which limits — but does not eliminate — 'O'-inflation.
    """
    import pandas as pd

    rows = []
    # union of all instance ids
    all_iids = set()
    for d in rater_units.values():
        all_iids.update(d.keys())

    for iid in all_iids:
        present = {name: d[iid] for name, d in rater_units.items() if iid in d}
        boundaries = sorted({b for units in present.values() for (s, e, _) in units for b in (s, e)})
        if len(boundaries) < 2:
            continue  # no annotated extent -> nothing to compare
        for k in range(len(boundaries) - 1):
            lo, hi = boundaries[k], boundaries[k + 1]
            if hi <= lo:
                continue
            for name, units in present.items():
                rows.append({"unit": f"{iid}:{k}", "annotator": name,
                             "annotation": _segment_label(lo, hi, units)})

    if not rows:
        return {"cohen": {}, "fleiss": {}, "krippendorff": None, "note": "no overlapping segments"}

    df = pd.DataFrame(rows, columns=["unit", "annotator", "annotation"])
    cohen = cohen_kappa_pairwise(df)
    partitioned = {"human_llm": [], "llm_llm": [], "human_human": []}
    for pair in cohen.get("pairs", []):
        partitioned[_pair_kind(pair["annotator_a"], pair["annotator_b"])].append(pair["kappa"])

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    krippendorff = None
    try:
        import simpledorff
        from simpledorff.metrics import nominal_metric
        alpha = simpledorff.calculate_krippendorffs_alpha_for_df(
            df, experiment_col="unit", annotator_col="annotator",
            class_col="annotation", metric_fn=nominal_metric)
        krippendorff = {"alpha": round(float(alpha), 4), "interpretation": interpret_kappa(float(alpha))}
    except Exception as e:
        logger.warning("judge_calibration: span token krippendorff failed: %s", e)

    return {
        "cohen": {
            "mean_kappa": cohen.get("mean_kappa"),
            "mean_human_llm": _mean(partitioned["human_llm"]),
            "mean_llm_llm": _mean(partitioned["llm_llm"]),
            "mean_human_human": _mean(partitioned["human_human"]),
        },
        "fleiss": fleiss_kappa(df),
        "krippendorff": krippendorff,
        "n_segments": df["unit"].nunique(),
    }


def compute_span_report(
    schema_name: str,
    valid_labels: List[str],
    llm_spans: Dict[str, Dict[str, List[dict]]],
    human_spans: Dict[str, Dict[str, List[dict]]],
    gold_strategy: str = "single",
    iou_threshold: float = 0.5,
    n_bins: int = 10,
    instance_lengths: Optional[Dict[str, int]] = None,
    gamma_samples: int = 30,
) -> Dict[str, Any]:
    """EXPERIMENTAL span metrics: IoU-matched P/R/F1, mean IoU, span calibration."""
    from itertools import combinations
    from potato.judge_calibration.calibration import calibration_report

    humans = sorted(human_spans.keys())
    gold: Dict[str, List[dict]] = {}
    if humans:
        if gold_strategy == "majority" and len(humans) > 1:
            logger.info("judge_calibration: span gold=majority not supported; using single human '%s'", humans[0])
        gold = dict(human_spans[humans[0]])

    per_model = {}
    for model, by_iid in llm_spans.items():
        overlap = sorted(iid for iid in by_iid if iid in gold)
        tp = fp = fn = 0
        all_ious = []
        confidences, correctness = [], []
        for iid in overlap:
            pred = by_iid[iid]
            t, f_p, f_n, ious, matched = _match_spans(pred, gold[iid], iou_threshold)
            tp += t; fp += f_p; fn += f_n
            all_ious.extend(ious)
            for p, ok in zip(pred, matched):
                confidences.append(float(p.get("confidence", 0.0)))
                correctness.append(1 if ok else 0)
        block = _prf(tp, fp, fn)
        block["mean_iou"] = round(sum(all_ious) / len(all_ious), 6) if all_ious else 0.0
        block["tp"] = tp
        block["fp"] = fp
        block["fn"] = fn
        block["n_instances"] = len(overlap)
        block["calibration"] = calibration_report(confidences, correctness, n_bins)
        per_model[model] = block

    # IAA: mean pairwise span-F1 across all raters, partitioned by kind.
    rater_spans = {LLM_PREFIX + m: d for m, d in llm_spans.items()}
    for h, d in human_spans.items():
        rater_spans[HUMAN_PREFIX + h] = d
    partitioned = {"human_llm": [], "llm_llm": [], "human_human": []}
    all_scores = []
    for a, b in combinations(sorted(rater_spans), 2):
        score = _pairwise_span_f1(rater_spans[a], rater_spans[b], iou_threshold)
        if score is None:
            continue
        all_scores.append(score)
        partitioned[_pair_kind(a, b)].append(score)

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    # Chance-corrected agreement: token/segment κ-α and a local γ.
    rater_units = {name: {iid: _to_units(sp) for iid, sp in d.items()}
                   for name, d in rater_spans.items()}
    token_iaa = compute_span_token_iaa(rater_units)

    # Continuum lengths for γ's chance model: actual text length if provided,
    # else the max span end seen per instance.
    lengths = dict(instance_lengths or {})
    for d in rater_units.values():
        for iid, units in d.items():
            max_end = max((e for (_, e, _) in units), default=0)
            lengths[iid] = max(lengths.get(iid, 0), max_end)

    gamma = None
    try:
        from potato.judge_calibration.gamma import gamma_agreement
        gamma = gamma_agreement(
            rater_units, lengths,
            is_llm=lambda n: n.startswith(LLM_PREFIX),
            n_samples=gamma_samples,
        )
    except Exception as e:
        logger.warning("judge_calibration: gamma agreement failed: %s", e)

    return {
        "schema": schema_name,
        "annotation_type": "span",
        "experimental": True,
        "n_gold": len(gold),
        "gold_strategy": "single",
        "iou_threshold": iou_threshold,
        "per_model": per_model,
        "iaa": {
            "span_f1": {
                "mean": _mean(all_scores),
                "mean_human_llm": _mean(partitioned["human_llm"]),
                "mean_llm_llm": _mean(partitioned["llm_llm"]),
                "mean_human_human": _mean(partitioned["human_human"]),
            },
            "token_kappa": token_iaa,
            "gamma": gamma,
        },
    }


# ----- top-level per-schema report ---------------------------------------

def compute_schema_report(
    schema_name: str,
    annotation_type: str,
    valid_labels: List[str],
    llm_modal: Dict[str, Dict[str, Any]],
    llm_conf: Dict[str, Dict[str, float]],
    human_labels: Dict[str, Dict[str, Any]],
    gold_strategy: str = "single",
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Build the full metric block for one single-label schema."""
    ordinal = annotation_type == "likert"
    gold = resolve_gold(human_labels, gold_strategy)

    per_model: Dict[str, Any] = {}
    for model, preds in llm_modal.items():
        # overlap = instances with both a model prediction and a gold label
        overlap = sorted(
            iid for iid, lab in preds.items()
            if lab is not None and iid in gold
        )
        y_true = [str(gold[iid]) for iid in overlap]
        y_pred = [str(preds[iid]) for iid in overlap]

        block = _classification_metrics(y_true, y_pred, valid_labels)
        if ordinal:
            block["mae"] = _mae(y_true, y_pred)

        # calibration: correct vs gold; confidence = vote fraction
        conf = llm_conf.get(model, {})
        confidences = [float(conf.get(iid, 0.0)) for iid in overlap]
        correctness = [1 if str(preds[iid]) == str(gold[iid]) else 0 for iid in overlap]
        block["calibration"] = calibration_report(confidences, correctness, n_bins)
        per_model[model] = block

    iaa = compute_iaa(llm_modal, human_labels, ordinal=ordinal)

    return {
        "schema": schema_name,
        "annotation_type": annotation_type,
        "n_gold": len(gold),
        "gold_strategy": gold_strategy,
        "per_model": per_model,
        "iaa": iaa,
    }
