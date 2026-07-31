"""
Repair single-select annotations corrupted before the GH #167 fix.

Potato versions up to 2.7.1 could persist every option an annotator ever clicked for a
``radio``, ``likert`` or ``confidence`` schema — one ``Label(schema, option)`` entry per
click — instead of replacing the previous answer. This tool rewrites affected
``user_state.json`` files so each such schema holds exactly the answer the annotator
settled on.

Resolution prefers the timestamped behavioral trail
(``instance_id_to_behavioral_data[*].annotation_changes``) over the persisted label
order. That distinction matters: the label dict serializes in *first-write* order, so a
``5 -> 4 -> 5`` revision persists as ``[5, 4]`` and order alone would answer ``4``.
Every record resolved by the weaker signal is reported.

Usage::

    potato repair-annotations path/to/config.yaml            # dry run by default
    potato repair-annotations path/to/config.yaml --apply
    potato repair-annotations path/to/config.yaml --apply --no-backup
"""

import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _resolve_output_dir(config: dict, config_path: str) -> str:
    """Absolute path to the task's annotation output directory."""
    out = config.get("output_annotation_dir", "")
    if os.path.isabs(out):
        return out
    base = config.get("task_dir") or os.path.dirname(os.path.abspath(config_path))
    if not os.path.isabs(base):
        base = os.path.join(os.path.dirname(os.path.abspath(config_path)), base)
    return os.path.normpath(os.path.join(base, out))


def _group_by_schema(entries: List[list]) -> Dict[str, List[int]]:
    """Map schema name -> indices into the serialized [[{schema,name}, value], ...] list."""
    groups: Dict[str, List[int]] = {}
    for idx, entry in enumerate(entries):
        if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
            continue
        label_obj = entry[0]
        if not isinstance(label_obj, dict):
            continue
        groups.setdefault(label_obj.get("schema", ""), []).append(idx)
    return groups


def _repair_entry_list(entries: List[list], single_select: set,
                       changes: List[dict]) -> Tuple[List[list], List[dict]]:
    """Collapse over-full single-select schemas in one serialized label list.

    Returns:
        ``(new_entries, reports)`` where each report describes one collapse.
    """
    from potato.export.single_select import EXEMPT_LABEL_NAMES, resolve_final_label

    drop = set()
    reports = []
    for schema, indices in _group_by_schema(entries).items():
        if schema not in single_select:
            continue
        names = [entries[i][0].get("name", "") for i in indices]
        non_exempt = [n for n in names if n not in EXEMPT_LABEL_NAMES]
        if len(non_exempt) <= 1:
            continue

        winner, method = resolve_final_label(schema, names, changes)
        for i in indices:
            name = entries[i][0].get("name", "")
            if name in EXEMPT_LABEL_NAMES or name == winner:
                continue
            drop.add(i)
        reports.append({
            "schema": schema,
            "stored": non_exempt,
            "kept": winner,
            "dropped": [n for n in non_exempt if n != winner],
            "method": method,
        })

    if not drop:
        return entries, reports
    return [e for i, e in enumerate(entries) if i not in drop], reports


def repair_user_state(state: dict, single_select: set) -> Tuple[dict, List[dict]]:
    """Repair one parsed ``user_state.json``. Returns ``(state, reports)``.

    ``state`` is mutated in place and also returned for convenience.
    """
    from potato.export.single_select import behavioral_changes, phase_changes

    reports = []

    labels_by_instance = state.get("instance_id_to_label_to_value") or {}
    for instance_id, entries in labels_by_instance.items():
        if not isinstance(entries, list):
            continue
        new_entries, rs = _repair_entry_list(
            entries, single_select, behavioral_changes(state, instance_id))
        if rs:
            labels_by_instance[instance_id] = new_entries
            for r in rs:
                r.update({"scope": "annotation", "instance_id": instance_id})
            reports.extend(rs)

    phase_data = state.get("phase_to_page_to_label_to_value") or {}
    for phase, pages in phase_data.items():
        if not isinstance(pages, dict):
            continue
        for page, entries in pages.items():
            if not isinstance(entries, list):
                continue
            new_entries, rs = _repair_entry_list(
                entries, single_select, phase_changes(state, phase, page))
            if rs:
                pages[page] = new_entries
                for r in rs:
                    r.update({"scope": phase, "instance_id": page})
                reports.extend(rs)

    return state, reports


def repair_output_dir(output_dir: str, single_select: set, apply: bool = False,
                      backup: bool = True) -> Dict[str, Any]:
    """Repair every ``user_state.json`` under ``output_dir``.

    Args:
        output_dir: The task's annotation output directory.
        single_select: Schema names that may hold at most one label.
        apply: Write the changes. When False (the default) nothing is modified.
        backup: Write ``user_state.json.bak`` before overwriting.

    Returns:
        A summary dict with per-user reports and counts.
    """
    summary = {
        "output_dir": output_dir,
        "users_scanned": 0,
        "users_repaired": 0,
        "collapses": 0,
        "resolved_by_behavioral": 0,
        "resolved_by_order": 0,
        "reports": [],
        "applied": apply,
    }

    if not os.path.isdir(output_dir):
        logger.error(f"Output directory not found: {output_dir}")
        return summary

    for user_dir in sorted(os.listdir(output_dir)):
        state_file = os.path.join(output_dir, user_dir, "user_state.json")
        if not os.path.exists(state_file):
            continue
        summary["users_scanned"] += 1

        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        state, reports = repair_user_state(state, single_select)
        if not reports:
            continue

        summary["users_repaired"] += 1
        summary["collapses"] += len(reports)
        for r in reports:
            r["user_dir"] = user_dir
            if r["method"] == "behavioral":
                summary["resolved_by_behavioral"] += 1
            elif r["method"] == "order":
                summary["resolved_by_order"] += 1
        summary["reports"].extend(reports)

        if apply:
            if backup:
                shutil.copy2(state_file, state_file + ".bak")
            # Same atomic temp-file + replace dance UserState.save() uses, so an
            # interrupted repair cannot leave a truncated state file behind.
            tmp = state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f)
            os.replace(tmp, state_file)

    return summary


def print_summary(summary: Dict[str, Any]) -> None:
    """Human-readable report."""
    mode = "APPLIED" if summary["applied"] else "DRY RUN (nothing written)"
    print(f"\nSingle-select annotation repair — {mode}")
    print(f"  Output directory : {summary['output_dir']}")
    print(f"  Users scanned    : {summary['users_scanned']}")
    print(f"  Users repaired   : {summary['users_repaired']}")
    print(f"  Values collapsed : {summary['collapses']}")
    print(f"     from timestamps: {summary['resolved_by_behavioral']}")
    print(f"     from order     : {summary['resolved_by_order']}")

    if summary["reports"]:
        print("\n  Detail:")
        for r in summary["reports"]:
            flag = "  <-- heuristic" if r["method"] == "order" else ""
            print(f"    [{r['scope']}] {r['user_dir']} / {r['instance_id']} / "
                  f"{r['schema']}: kept '{r['kept']}', dropped "
                  f"{r['dropped']} ({r['method']}){flag}")

    if summary["resolved_by_order"]:
        print(
            f"\n  WARNING: {summary['resolved_by_order']} value(s) were resolved by "
            f"persisted order because no behavioral trail was available. Stored order "
            f"is FIRST-WRITE order, not recency, so an A->B->A revision resolves to B. "
            f"Review those rows before relying on them."
        )
    if not summary["applied"] and summary["collapses"]:
        print("\n  Re-run with --apply to write these changes "
              "(a .bak copy is kept unless you pass --no-backup).")
    print()


def run_repair(args) -> int:
    """Entry point for ``potato repair-annotations``. Returns a process exit code."""
    from potato.server_utils.config_module import init_config, config
    from potato.export.single_select import single_select_schema_names

    init_config(args)

    single_select = single_select_schema_names(config.get("annotation_schemes") or [])
    single_select |= single_select_schema_names(config.get("_surveyflow_schemes") or [])

    # SurveyFlow questions live in external phase files that only the full server
    # startup loads into _surveyflow_schemes. Read them directly so a repair run does
    # not need to boot the app just to learn a prestudy likert's type.
    single_select |= single_select_schema_names(_load_phase_schemes(config, args.config_file))

    if not single_select:
        print("No single-select (radio/likert/confidence) schemas in this config — "
              "nothing to repair.")
        return 0

    output_dir = _resolve_output_dir(config, args.config_file)
    print(f"Single-select schemas: {', '.join(sorted(single_select))}")

    summary = repair_output_dir(
        output_dir, single_select,
        apply=getattr(args, "apply", False),
        backup=not getattr(args, "no_backup", False),
    )
    print_summary(summary)
    return 0


def _load_phase_schemes(config: dict, config_path: str) -> List[dict]:
    """Question schemes declared in the config's SurveyFlow phase files."""
    schemes: List[dict] = []
    phases = config.get("phases") or {}
    if not isinstance(phases, dict):
        return schemes

    config_dir = os.path.dirname(os.path.abspath(config_path))
    task_dir = config.get("task_dir") or ""
    if task_dir and not os.path.isabs(task_dir):
        task_dir = os.path.normpath(os.path.join(config_dir, task_dir))

    for name, phase in phases.items():
        if name == "order" or not isinstance(phase, dict):
            continue
        rel = phase.get("file")
        if not rel or not str(rel).endswith(".json"):
            continue

        # init_config may already have rewritten the path relative to the process CWD,
        # or left it relative to the config/task dir. Try each; the first hit wins.
        if os.path.isabs(rel):
            candidates = [rel]
        else:
            candidates = [
                os.path.join(config_dir, rel),
                os.path.join(task_dir, rel) if task_dir else None,
                os.path.abspath(rel),
            ]
        path = next((c for c in candidates if c and os.path.exists(c)), None)
        if path is None:
            logger.warning(f"Could not locate phase file '{rel}' for phase '{name}'; "
                           f"its questions will not be considered for repair")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                schemes.extend(s for s in loaded if isinstance(s, dict))
        except Exception as e:
            logger.warning(f"Could not read phase file {path}: {e}")
    return schemes
