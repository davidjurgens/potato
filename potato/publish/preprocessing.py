"""The preprocessing pipeline: ExportContext -> PublishBundle.

Required steps always run (validation, privacy). Optional steps are driven by the
resolved options dict (see ``publish.config.DEFAULT_OPTIONS``): aggregation, train/
val/test splitting, coverage filtering, PII scrubbing, media bundling, and which
logical splits to include.

Statistics for the dataset card come from Paper Mode (``paper.compute_metrics``),
anonymized with the *same* mapping applied to the data splits so annotator ids line
up between the README and the rows.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

from potato.export.cli import build_export_context
from potato.paper import report as paper_report
from potato.paper.collect import collect_project
from potato.paper.metrics import compute_metrics
from potato.publish import bundle as bundle_mod
from potato.publish.config import DatasetMetadata, PublishConfig, resolve_options

logger = logging.getLogger(__name__)

# Fields that must never reach a published dataset.
_INTERNAL_FIELDS = {"email", "ip", "ip_address", "prolific_id", "prolific_pid",
                    "mturk_id", "worker_id", "assignment_id", "hit_id", "password"}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\-\s().]{7,}\d)\b")
_MEDIA_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff",
               ".mp3", ".wav", ".ogg", ".m4a", ".flac",
               ".mp4", ".webm", ".mov", ".avi", ".mkv")


def _scrub_text(text: str) -> str:
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    return text


def _apply_anonymization(annotation_rows: List[dict]) -> Dict[str, str]:
    """Map user_id -> A1..An in place; returns the mapping (for reuse/logging)."""
    mapping = paper_report.anon_map(
        r.get("user_id", "") for r in annotation_rows)
    for row in annotation_rows:
        if "user_id" in row:
            row["user_id"] = mapping.get(row["user_id"], row["user_id"])
    return mapping


def _strip_internal_fields(rows: List[dict]) -> None:
    for row in rows:
        for key in list(row):
            if key.lower() in _INTERNAL_FIELDS:
                del row[key]


def _filter_min_annotators(annotation_rows: List[dict], minimum: int) -> List[dict]:
    if minimum <= 1:
        return annotation_rows
    from collections import defaultdict
    per_instance = defaultdict(set)
    for r in annotation_rows:
        per_instance[r.get("instance_id")].add(r.get("user_id"))
    keep = {iid for iid, users in per_instance.items() if len(users) >= minimum}
    return [r for r in annotation_rows if r.get("instance_id") in keep]


def _partition_splits(rows: List[dict], spec: Dict[str, float],
                      seed: int) -> Dict[str, List[dict]]:
    """Deterministically partition rows by instance into named fractions.

    Splits are assigned per distinct instance_id (never splitting one instance
    across train/test) using a seeded hash, so the result is reproducible without
    importing ``random`` (which is unseeded-forbidden in some contexts) — a stable
    hash of ``seed:instance_id`` maps into the cumulative fraction bands.
    """
    import hashlib
    names = list(spec.keys())
    total = sum(spec.values()) or 1.0
    fractions = [spec[n] / total for n in names]
    bounds, acc = [], 0.0
    for fr in fractions:
        acc += fr
        bounds.append(acc)

    out: Dict[str, List[dict]] = {n: [] for n in names}
    for row in rows:
        iid = str(row.get("instance_id", ""))
        h = hashlib.sha256(f"{seed}:{iid}".encode()).hexdigest()
        frac = int(h[:8], 16) / 0xFFFFFFFF
        for name, bound in zip(names, bounds):
            if frac <= bound:
                out[name].append(row)
                break
        else:
            out[names[-1]].append(row)
    return out


def run_pipeline(config_path: str,
                 options: Optional[dict] = None,
                 metadata_overrides: Optional[dict] = None,
                 publish_config: Optional[PublishConfig] = None) -> bundle_mod.PublishBundle:
    """Build a PublishBundle from a Potato config path and resolved options."""
    context = build_export_context(config_path)
    pub = publish_config or PublishConfig.from_config(context.config)
    opts = resolve_options(pub.options, options)
    metadata: DatasetMetadata = pub.metadata.merge_overrides(metadata_overrides)

    warnings: List[str] = []

    # --- required: drop empty/label-less annotation records --------------------
    annotations = [a for a in context.annotations
                   if a.get("labels") or a.get("spans")]
    if not annotations:
        warnings.append("No non-empty annotations found to publish.")

    # --- annotation rows (canonical flattening) --------------------------------
    ann_rows = bundle_mod.build_annotation_rows(annotations)

    # --- optional: coverage filter ---------------------------------------------
    min_ann = int(opts.get("min_annotators", 1) or 1)
    if min_ann > 1:
        before = len(ann_rows)
        ann_rows = _filter_min_annotators(ann_rows, min_ann)
        warnings.append(
            f"Coverage filter (min_annotators={min_ann}) dropped "
            f"{before - len(ann_rows)} of {before} annotation rows.")

    # --- required: privacy -----------------------------------------------------
    anonymize = bool(opts.get("anonymize", True))
    if anonymize:
        _apply_anonymization(ann_rows)
    _strip_internal_fields(ann_rows)

    # --- gold aggregation ------------------------------------------------------
    gold_rows: List[dict] = []
    if opts.get("include_gold", True) and opts.get("aggregation", "majority") != "none":
        gold_rows = bundle_mod.build_gold_rows(
            ann_rows, aggregation=str(opts.get("aggregation", "majority")))

    # --- spans / items ---------------------------------------------------------
    span_rows = bundle_mod.build_span_rows(annotations) \
        if opts.get("include_spans", True) else []
    item_rows = bundle_mod.build_item_rows(context.items) \
        if opts.get("include_items", True) else []
    if anonymize:
        _strip_internal_fields(item_rows)

    # --- optional: PII scrub of free text --------------------------------------
    if opts.get("scrub_pii", False):
        for row in item_rows:
            for k, v in list(row.items()):
                if isinstance(v, str):
                    row[k] = _scrub_text(v)
        for row in span_rows:
            if isinstance(row.get("text"), str):
                row["text"] = _scrub_text(row["text"])

    # --- assemble logical splits -----------------------------------------------
    splits: Dict[str, List[dict]] = {}
    split_spec = opts.get("splits")
    primary = gold_rows if gold_rows else ann_rows
    if split_spec:
        seed = int(opts.get("split_seed", 42) or 42)
        parts = _partition_splits(primary, split_spec, seed)
        splits.update(parts)
        # Keep the raw per-annotator split available too when both exist.
        if gold_rows and opts.get("include_annotations", True):
            splits["annotations"] = ann_rows
    else:
        if opts.get("include_annotations", True):
            splits["annotations"] = ann_rows
        if gold_rows:
            splits["gold"] = gold_rows
    if span_rows:
        splits["spans"] = span_rows
    if item_rows:
        splits["items"] = item_rows
    if opts.get("include_phase_responses", False) and context.phase_responses:
        splits["phase_responses"] = list(context.phase_responses)

    # --- report metrics (anonymized with the same scheme) ----------------------
    stats: Dict[str, Any] = {}
    try:
        project = collect_project(config_path)
        if anonymize:
            paper_report.anonymize(project)
        stats = compute_metrics(project)
    except Exception as e:                       # metrics are best-effort
        logger.warning("Could not compute report metrics: %s", e)
        warnings.append(f"Report metrics unavailable: {e}")

    # --- media bundling --------------------------------------------------------
    media_files: List[str] = []
    if opts.get("bundle_media", False):
        media_files = _collect_media(context, warnings)

    return bundle_mod.PublishBundle(
        splits=splits,
        schemas=context.schemas,
        metadata=metadata,
        config=context.config,
        stats=stats,
        media_files=media_files,
        warnings=warnings,
    )


def _collect_media(context, warnings: List[str]) -> List[str]:
    """Resolve media files referenced by items under the task's media directory."""
    config = context.config
    task_dir = config.get("task_dir", ".")
    config_file = config.get("__config_file__", "")
    base = os.path.dirname(config_file) if config_file else os.getcwd()
    media_dir = config.get("media_directory", "media")
    root = os.path.normpath(os.path.join(base, task_dir))

    found, missing = [], 0
    for item in context.items.values():
        if not isinstance(item, dict):
            continue
        for val in item.values():
            if not isinstance(val, str):
                continue
            if not val.lower().endswith(_MEDIA_EXTS):
                continue
            rel = val[len("/media/"):] if val.startswith("/media/") else val
            for candidate in (os.path.join(root, rel),
                              os.path.join(root, media_dir, os.path.basename(rel))):
                if os.path.isfile(candidate):
                    found.append(candidate)
                    break
            else:
                missing += 1
    if missing:
        warnings.append(f"{missing} referenced media file(s) were not found on disk "
                        f"and were skipped.")
    # De-duplicate, preserve order.
    seen, unique = set(), []
    for p in found:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique
