"""
Judge Calibration report assembly + output files.

Pulls together the LLM results (from the ResultStore) and the human blind
labels (from UserState) into the metric inputs, runs ``metrics`` per schema,
and writes three artifacts under the configured output dir:

- ``llm_labels.jsonl`` : every LLM's label on every labeled item (the deliverable)
- ``report.json``      : the structured metrics report
- ``report.html``      : a human-readable summary

Human labels live entirely in UserState (never as pseudo-users) so they're read
through the normal user-state API here.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from potato.judge_calibration.metrics import (
    compute_schema_report,
    compute_multiselect_report,
    compute_span_report,
)

logger = logging.getLogger(__name__)


def _is_selected(value: Any) -> bool:
    """Whether a stored label value counts as 'chosen'."""
    if value is None or value is False:
        return False
    return str(value).strip().lower() not in ("", "false", "0", "none")


def extract_human_label(label_dict, schema_name: str, annotation_type: str):
    """Pull a human's label for one schema from a flat {Label: value} dict.

    Returns a label name (str) for single-label schemas, a sorted list for
    multiselect, or None if the schema was not answered.
    """
    chosen = [
        lab.name for lab, val in label_dict.items()
        if getattr(lab, "schema", None) == schema_name and _is_selected(val)
    ]
    if annotation_type == "multiselect":
        return sorted(chosen)
    return chosen[0] if chosen else None


def collect_metric_inputs(
    store, schema_info: Dict[str, Any], restrict_ids: Optional[set] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, float]], Dict[str, Dict[str, Any]]]:
    """Assemble (llm_modal, llm_conf, human_labels) for one schema."""
    schema_name = schema_info.get("name")
    annotation_type = schema_info.get("annotation_type", "radio")

    llm_modal: Dict[str, Dict[str, Any]] = {}
    llm_conf: Dict[str, Dict[str, float]] = {}
    for r in store.all_results():
        if r.schema_name != schema_name:
            continue
        if restrict_ids is not None and r.instance_id not in restrict_ids:
            continue
        llm_modal.setdefault(r.model, {})[r.instance_id] = r.modal_label
        llm_conf.setdefault(r.model, {})[r.instance_id] = r.confidence

    human_labels: Dict[str, Dict[str, Any]] = {}
    try:
        from potato.user_state_management import get_user_state_manager
        usm = get_user_state_manager()
        users = usm.get_all_users() if usm else []
    except Exception as e:
        logger.warning("judge_calibration: could not load user states: %s", e)
        users = []

    for user in users:
        uid = user.get_user_id()
        for iid in user.get_annotated_instance_ids():
            if restrict_ids is not None and iid not in restrict_ids:
                continue
            label_dict = user.get_label_annotations(iid)
            if not label_dict:
                continue
            lab = extract_human_label(label_dict, schema_name, annotation_type)
            if lab is None or (isinstance(lab, list) and not lab):
                continue
            human_labels.setdefault(uid, {})[iid] = lab

    return llm_modal, llm_conf, human_labels


def extract_human_spans(span_dict, schema_name: str) -> List[dict]:
    """Pull a human's spans for one schema from a flat {SpanAnnotation: value} dict."""
    out = []
    for sp in span_dict:
        if getattr(sp, "schema", None) != schema_name:
            continue
        out.append({"start": sp.start, "end": sp.end, "label": sp.name})
    return out


def collect_span_inputs(store, schema_info, restrict_ids=None):
    """Assemble (llm_spans, human_spans) for one span schema.

    llm_spans[model][iid]  = list of {start, end, label, confidence}
    human_spans[hid][iid]  = list of {start, end, label}
    """
    schema_name = schema_info.get("name")

    llm_spans: Dict[str, Dict[str, List[dict]]] = {}
    for r in store.all_results():
        if r.schema_name != schema_name:
            continue
        if restrict_ids is not None and r.instance_id not in restrict_ids:
            continue
        # modal_label for span is a list of span dicts (may be empty)
        llm_spans.setdefault(r.model, {})[r.instance_id] = r.modal_label or []

    human_spans: Dict[str, Dict[str, List[dict]]] = {}
    try:
        from potato.user_state_management import get_user_state_manager
        usm = get_user_state_manager()
        users = usm.get_all_users() if usm else []
    except Exception as e:
        logger.warning("judge_calibration: could not load user states: %s", e)
        users = []

    for user in users:
        uid = user.get_user_id()
        for iid in user.get_annotated_instance_ids():
            if restrict_ids is not None and iid not in restrict_ids:
                continue
            span_dict = user.get_span_annotations(iid)
            if not span_dict:
                continue
            spans = extract_human_spans(span_dict, schema_name)
            if spans:
                human_spans.setdefault(uid, {})[iid] = spans
    return llm_spans, human_spans


def _instance_text_lengths(manager) -> Dict[str, int]:
    """Map instance_id -> text length (chars) for γ's continuum model."""
    lengths: Dict[str, int] = {}
    try:
        from potato.item_state_management import get_item_state_manager
        ism = get_item_state_manager()
        text_key = (manager.app_config.get("item_properties", {}) or {}).get("text_key")
        for iid, item in ism.instance_id_to_instance.items():
            data = item.get_data()
            if isinstance(data, dict) and text_key and text_key in data:
                lengths[iid] = len(str(data[text_key]))
            else:
                lengths[iid] = len(str(item.get_text()))
    except Exception as e:
        logger.warning("judge_calibration: could not compute text lengths: %s", e)
    return lengths


def build_report(manager) -> Dict[str, Any]:
    """Compute the report for all evaluated schemas and write output files."""
    config = manager.config
    schema_infos = manager.get_schema_infos()
    out_dir = config.output.dir
    os.makedirs(out_dir, exist_ok=True)

    # --- per-LLM labels file (all labeled items) ---
    labels_path = os.path.join(out_dir, config.output.labels_file)
    with open(labels_path, "w") as f:
        for r in manager.store.all_results():
            f.write(json.dumps(r.to_dict()) + "\n")

    # --- restrict metrics to the human calibration sample if one was drawn ---
    sample_ids = manager.phase.get_phase_data("calibration_sample")
    restrict = set(sample_ids) if sample_ids else None

    from potato.ai.judge import extract_labels

    schema_reports = {}
    for schema_info in schema_infos:
        name = schema_info.get("name")
        atype = schema_info.get("annotation_type", "radio")
        valid_labels = extract_labels(schema_info)
        if atype == "span":
            llm_spans, human_spans = collect_span_inputs(
                manager.store, schema_info, restrict_ids=restrict
            )
            schema_reports[name] = compute_span_report(
                schema_name=name,
                valid_labels=valid_labels,
                llm_spans=llm_spans,
                human_spans=human_spans,
                gold_strategy=config.human.gold,
                n_bins=config.calibration.n_bins,
                instance_lengths=_instance_text_lengths(manager),
            )
            continue
        llm_modal, llm_conf, human_labels = collect_metric_inputs(
            manager.store, schema_info, restrict_ids=restrict
        )
        if atype == "multiselect":
            schema_reports[name] = compute_multiselect_report(
                schema_name=name,
                valid_labels=valid_labels,
                llm_modal=llm_modal,
                llm_conf=llm_conf,
                human_labels=human_labels,
                gold_strategy=config.human.gold,
                n_bins=config.calibration.n_bins,
            )
        else:
            schema_reports[name] = compute_schema_report(
                schema_name=name,
                annotation_type=atype,
                valid_labels=valid_labels,
                llm_modal=llm_modal,
                llm_conf=llm_conf,
                human_labels=human_labels,
                gold_strategy=config.human.gold,
                n_bins=config.calibration.n_bins,
            )

    report = {
        "generated_at": datetime.now().isoformat(),
        "models": manager.store.models(),
        "n_models": len(config.models),
        "k_samples": config.k_samples,
        "n_labeled_items": len(manager.store.labeled_instance_ids()),
        "n_calibration_sample": len(restrict) if restrict else None,
        "human": {"num_raters": config.human.num_raters, "gold": config.human.gold},
        "schemas": schema_reports,
    }

    json_path = os.path.join(out_dir, config.output.report_json)
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    html_path = os.path.join(out_dir, config.output.report_html)
    with open(html_path, "w") as f:
        f.write(render_html(report))

    logger.info("judge_calibration: wrote report to %s", out_dir)
    return report


# ----- HTML rendering -----------------------------------------------------

def render_html(report: Dict[str, Any]) -> str:
    """Render a compact, self-contained HTML summary of the report."""
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Judge Calibration Report</title>",
        # Self-contained (portable/emailable) but aligned to Potato's brand:
        # Outfit-first font stack, violet accent, accessible contrast, dark mode.
        "<style>",
        ":root{--fg:#18181b;--muted:#52525b;--border:#d4d4d8;--th-bg:#f4f4f6;",
        "--accent:#6e56cf;--bg:#ffffff}",
        "@media (prefers-color-scheme: dark){:root{--fg:#e4e4e7;--muted:#a1a1aa;",
        "--border:#3f3f46;--th-bg:#27272a;--accent:#a18fff;--bg:#18181b}}",
        "body{font-family:'Outfit',ui-sans-serif,system-ui,-apple-system,sans-serif;",
        "margin:2rem auto;max-width:900px;padding:0 1rem;color:var(--fg);background:var(--bg)}",
        "h1{font-size:1.5rem;color:var(--accent)}",
        "h2{font-size:1.2rem;margin-top:2rem;padding-bottom:.25rem;border-bottom:1px solid var(--border)}",
        "a{color:var(--accent)}",
        ".tbl-wrap{overflow-x:auto;margin:1rem 0}",
        "table{border-collapse:collapse;width:100%;min-width:min-content}",
        "th,td{border:1px solid var(--border);padding:6px 10px;text-align:left;font-size:0.9rem;white-space:nowrap}",
        "th{background:var(--th-bg)}.muted{color:var(--muted)}",
        ".metric{font-variant-numeric:tabular-nums}",
        "</style></head><body>",
        "<h1>Judge Calibration Report</h1>",
        f"<p class='muted'>Generated {report.get('generated_at','')} · "
        f"{report.get('n_models',0)} model(s), k={report.get('k_samples','?')} samples · "
        f"{report.get('n_labeled_items',0)} items labeled"
        + (f" · {report['n_calibration_sample']} in calibration sample"
           if report.get('n_calibration_sample') else "")
        + "</p>",
    ]

    for name, sr in (report.get("schemas") or {}).items():
        parts.append(f"<h2>Schema: {name} <span class='muted'>({sr.get('annotation_type','')})</span></h2>")
        if sr.get("skipped"):
            parts.append(f"<p class='muted'>{sr['skipped']}</p>")
            continue
        parts.append(f"<p class='muted'>{sr.get('n_gold',0)} human gold labels "
                     f"(gold = {sr.get('gold_strategy','single')})</p>")

        # per-model metrics table
        parts.append("<div class='tbl-wrap'><table><tr><th>Model</th><th>Acc</th><th>F1 (macro)</th>"
                     "<th>ECE</th><th>Brier</th><th>n</th></tr>")
        if sr.get("experimental"):
            parts.append("<p class='muted'>⚠ Experimental — span aggregation and "
                         "IoU matching are heuristic.</p>")

        for model, m in (sr.get("per_model") or {}).items():
            cal = m.get("calibration", {})
            mae = f" · MAE {m['mae']}" if m.get("mae") is not None else ""
            acc = m.get("accuracy", m.get("exact_match_accuracy", ""))
            extra = f" · Jaccard {m['mean_jaccard']}" if m.get("mean_jaccard") is not None else ""
            if m.get("mean_iou") is not None and "mean_jaccard" not in m:
                extra = f" · IoU {m['mean_iou']}"
            f1 = m.get("f1_macro", m.get("f1", ""))
            n = m.get("n", m.get("n_instances", ""))
            parts.append(
                f"<tr><td>{model}</td>"
                f"<td class='metric'>{acc}</td>"
                f"<td class='metric'>{f1}{mae}{extra}</td>"
                f"<td class='metric'>{cal.get('ece','')}</td>"
                f"<td class='metric'>{cal.get('brier','')}</td>"
                f"<td class='metric'>{n}</td></tr>"
            )
        parts.append("</table></div>")

        # IAA
        iaa = sr.get("iaa", {})
        parts.append("<div class='tbl-wrap'><table><tr><th>Agreement</th><th>Value</th></tr>")
        if "span_f1" in iaa:
            j = iaa["span_f1"]
            parts.append(f"<tr><td>Span F1 (human↔LLM)</td><td class='metric'>{j.get('mean_human_llm')}</td></tr>")
            parts.append(f"<tr><td>Span F1 (LLM↔LLM)</td><td class='metric'>{j.get('mean_llm_llm')}</td></tr>")
            parts.append(f"<tr><td>Span F1 (human↔human)</td><td class='metric'>{j.get('mean_human_human')}</td></tr>")
            tk = (iaa.get("token_kappa") or {}).get("cohen", {}) or {}
            if tk:
                parts.append(f"<tr><td>Token κ (human↔LLM, chance-corrected)</td><td class='metric'>{tk.get('mean_human_llm')}</td></tr>")
                parts.append(f"<tr><td>Token κ (LLM↔LLM)</td><td class='metric'>{tk.get('mean_llm_llm')}</td></tr>")
            tkr = (iaa.get("token_kappa") or {}).get("krippendorff") or {}
            if tkr:
                parts.append(f"<tr><td>Token Krippendorff α</td><td class='metric'>{tkr.get('alpha')}</td></tr>")
            g = iaa.get("gamma") or {}
            if g and g.get("gamma") is not None:
                parts.append(f"<tr><td>γ (Gamma, approx.) overall</td><td class='metric'>{g.get('gamma')}</td></tr>")
                parts.append(f"<tr><td>γ (human↔LLM)</td><td class='metric'>{g.get('mean_human_llm')}</td></tr>")
        elif "jaccard" in iaa:
            j = iaa["jaccard"]
            parts.append(f"<tr><td>Jaccard (human↔LLM)</td><td class='metric'>{j.get('mean_human_llm')}</td></tr>")
            parts.append(f"<tr><td>Jaccard (LLM↔LLM)</td><td class='metric'>{j.get('mean_llm_llm')}</td></tr>")
            parts.append(f"<tr><td>Jaccard (human↔human)</td><td class='metric'>{j.get('mean_human_human')}</td></tr>")
        else:
            cohen = iaa.get("cohen", {})
            kripp = iaa.get("krippendorff") or {}
            parts.append(f"<tr><td>Cohen κ (human↔LLM)</td><td class='metric'>{cohen.get('mean_human_llm')}</td></tr>")
            parts.append(f"<tr><td>Cohen κ (LLM↔LLM)</td><td class='metric'>{cohen.get('mean_llm_llm')}</td></tr>")
            parts.append(f"<tr><td>Cohen κ (human↔human)</td><td class='metric'>{cohen.get('mean_human_human')}</td></tr>")
            parts.append(f"<tr><td>Fleiss κ (all raters)</td><td class='metric'>{iaa.get('fleiss',{}).get('kappa')}</td></tr>")
            parts.append(f"<tr><td>Krippendorff α ({kripp.get('metric','')})</td><td class='metric'>{kripp.get('alpha')}</td></tr>")
        parts.append("</table></div>")

    parts.append("</body></html>")
    return "".join(parts)
