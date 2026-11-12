"""
Writes an imported survey as Potato phase pages.

Two modes:

* **New project** (``-o DIR``): ``DIR/surveys/<page>.json`` for each page, a
  ``config.yaml`` that runs them before (or after) a placeholder annotation
  task, a three-item sample data file, ``README.md`` and ``IMPORT_REPORT.md``.
  Replace the placeholder task with the real one.
* **Into an existing project** (``--into CONFIG``): the page files go into
  ``surveys/`` beside that config, and a merged copy is written as
  ``<config>.with-<survey>.yaml``. The original config is never modified.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .base import SurveyImportResult

from potato.server_utils.config_schema import SCHEMA_URL

SCHEMA_MODELINE = f"# yaml-language-server: $schema={SCHEMA_URL}"

PLACEHOLDER_SCHEME = {
    "annotation_type": "radio",
    "name": "placeholder_label",
    "description": "Placeholder task: replace this question and data/items.jsonl with your own.",
    "labels": ["Option A", "Option B"],
}

PLACEHOLDER_ITEMS = [
    {"id": "item_1", "text": "Replace data/items.jsonl with the items to annotate."},
    {"id": "item_2", "text": "This placeholder task follows the imported survey pages."},
    {"id": "item_3", "text": "See IMPORT_REPORT.md for anything that did not carry over."},
]


def _phase_entries(result: SurveyImportResult, slot: str, surveys_rel: str) -> Dict[str, Any]:
    phases: Dict[str, Any] = {}
    for page in result.pages:
        entry: Dict[str, Any] = {"type": slot, "file": f"{surveys_rel}/{page.name}.json"}
        if page.show_when:
            entry["show_when"] = page.show_when["show_when"]
            if page.show_when.get("logic", "all") != "all":
                entry["logic"] = page.show_when["logic"]
        if page.exit_when:
            entry["exit_when"] = page.exit_when
        if page.randomize_questions:
            entry["randomize_questions"] = page.randomize_questions
        phases[page.name] = entry
    return phases


def _write_pages(result: SurveyImportResult, surveys_dir: Path) -> List[str]:
    surveys_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for page in result.pages:
        path = surveys_dir / f"{page.name}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(page.questions, f, ensure_ascii=False, indent=2)
            f.write("\n")
        written.append(str(path))
    return written


def report_text(result: SurveyImportResult, source: str) -> str:
    lines = [f"# Import report: {Path(source).name}", "",
             f"Format: {result.source_format}. "
             f"{len(result.pages)} page(s), {result.num_questions()} question(s).", ""]
    if result.untranslated:
        lines += ["## Not carried over", "",
                  "Potato has no equivalent for these, or the importer could not "
                  "translate them. Review each one; the study runs without them.", ""]
        lines += [f"- {u.line()}" for u in result.untranslated]
        lines.append("")
    else:
        lines += ["Everything in the source was carried over.", ""]
    if result.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in result.warnings] + [""]
    if result.name_map:
        lines += ["## Question names", "",
                  "| Source | Potato |", "|---|---|"]
        lines += [f"| {src} | {dst} |" for src, dst in result.name_map.items()]
        lines.append("")
    return "\n".join(lines)


def write_new_project(result: SurveyImportResult, output_dir: str, source: str,
                      slot: str = "prestudy") -> List[str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = _write_pages(result, out / "surveys")
    (out / "data").mkdir(exist_ok=True)
    data_path = out / "data" / "items.jsonl"
    if not data_path.exists():
        with data_path.open("w", encoding="utf-8") as f:
            for row in PLACEHOLDER_ITEMS:
                f.write(json.dumps(row) + "\n")
        written.append(str(data_path))

    page_names = [p.name for p in result.pages]
    order = (page_names + ["annotation"]) if slot == "prestudy" else (["annotation"] + page_names)
    phases: Dict[str, Any] = {"order": order}
    phases.update(_phase_entries(result, slot, "surveys"))
    phases["annotation"] = {"type": "annotation"}
    if result.counterbalance:
        phases["counterbalance"] = result.counterbalance

    task_name = result.title or f"{Path(source).stem} (imported)"
    config: Dict[str, Any] = {
        "port": 8000,
        "annotation_task_name": task_name,
        "task_dir": ".",
        "output_annotation_dir": "annotation_output/",
        "data_files": ["data/items.jsonl"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default",
        "export_include_phase_data": True,
    }
    if result.conditions:
        config["conditions"] = result.conditions
    config["phases"] = phases
    config["annotation_schemes"] = [dict(PLACEHOLDER_SCHEME)]
    config_path = out / "config.yaml"
    with config_path.open("w", encoding="utf-8") as f:
        f.write(SCHEMA_MODELINE + "\n")
        yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    written.append(str(config_path))

    report = out / "IMPORT_REPORT.md"
    report.write_text(report_text(result, source), encoding="utf-8")
    written.append(str(report))
    readme = out / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {task_name}\n\nImported from `{Path(source).name}` ({result.source_format}) "
            f"by `potato import`.\n\nThe survey pages are in `surveys/` and run "
            f"{'before' if slot == 'prestudy' else 'after'} a placeholder annotation task. "
            "Replace `annotation_schemes` in `config.yaml` and `data/items.jsonl` with "
            "the real task. `IMPORT_REPORT.md` lists anything that did not carry over.\n\n"
            "Run it:\n\n    potato start config.yaml -p 8000\n",
            encoding="utf-8")
        written.append(str(readme))
    return written


def write_into(result: SurveyImportResult, config_path: str, source: str,
               slot: str = "prestudy", overwrite: bool = False,
               prefix: Optional[str] = None) -> List[str]:
    """Pages beside an existing config, plus a merged copy of that config.

    The merged copy and the report are named after the source and the prefix
    (``config.with-<source>-<prefix>.yaml``), so a second import of the same
    file under another prefix writes beside the first instead of over it.
    """
    cfg_path = Path(config_path)
    with cfg_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    base_dir = cfg_path.parent
    stem = Path(source).stem
    tag = (prefix or "").strip("_-. ")
    if tag:
        stem = f"{stem}-{tag}"
    merged = cfg_path.with_name(f"{cfg_path.stem}.with-{stem}.yaml")
    report = base_dir / f"IMPORT_REPORT.{stem}.md"
    # An earlier import with the same source and prefix wrote these; replacing
    # them without a word would lose any edits made since.
    targets = [merged, report] + [base_dir / "surveys" / f"{p.name}.json" for p in result.pages]
    taken = [str(t) for t in targets if t.exists()]
    if taken and not overwrite:
        raise ValueError("these files exist from an earlier import and would be replaced: "
                         + ", ".join(taken) + ". Remove them, or use another --prefix")

    phases = config.get("phases")
    if isinstance(phases, list):
        raise ValueError(f"{config_path} uses the list form of `phases`; convert it to the "
                         "`order:` form first, or import into a new project with -o")
    phases = dict(phases or {})
    existing = set(phases) - {"order", "counterbalance"}
    clash = [p.name for p in result.pages if p.name in existing]
    if clash:
        raise ValueError(f"{config_path} already has phase page(s) named {', '.join(clash)}")
    existing_q = {s.get("name") for s in config.get("annotation_schemes") or []}
    clash_q = sorted(existing_q & {q.get("name") for q in result.all_questions()})
    if clash_q:
        raise ValueError(f"{config_path} already has question(s) named {', '.join(clash_q)}; "
                         "import with --prefix to rename the survey's questions")
    order = list(phases.get("order") or ["annotation"])
    if "annotation" not in order:
        order.append("annotation")
    idx = order.index("annotation")
    names = [p.name for p in result.pages]
    order = order[:idx] + names + order[idx:] if slot == "prestudy" else order[:idx + 1] + names + order[idx + 1:]
    phases["order"] = order
    phases.update(_phase_entries(result, slot, "surveys"))
    phases.setdefault("annotation", {"type": "annotation"})
    if result.counterbalance:
        phases["counterbalance"] = list(phases.get("counterbalance") or []) + result.counterbalance
    config["phases"] = phases
    if result.conditions and not config.get("conditions"):
        config["conditions"] = result.conditions
    elif result.conditions:
        result.warnings.append("The survey defines between-subjects conditions and the "
                               "config already has a `conditions` block; the survey's were not merged.")
    turned_on = "export_include_phase_data" not in config
    if turned_on:
        config["export_include_phase_data"] = True
        result.warnings.append(
            "Set export_include_phase_data: true in the merged config, so the survey answers "
            "are exported. They can hold personal data; set it to false to leave them out.")

    written = _write_pages(result, base_dir / "surveys")
    with merged.open("w", encoding="utf-8") as f:
        f.write(SCHEMA_MODELINE + "\n")
        f.write(f"# {cfg_path.name} with the pages imported from {Path(source).name}.\n"
                "# Comments in the original are not kept.\n")
        if turned_on:
            f.write("# export_include_phase_data was set to true so the survey answers are\n"
                    "# exported; they can hold personal data.\n")
        yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    written.append(str(merged))
    report.write_text(report_text(result, source), encoding="utf-8")
    written.append(str(report))
    return written


def apply_prefix(result: SurveyImportResult, prefix: Optional[str]) -> None:
    """Rename every question (and page) with a prefix, rewriting references."""
    if not prefix:
        return
    rename = {}
    for q in result.all_questions():
        rename[q["name"]] = f"{prefix}{q['name']}"

    from potato.server_utils.display_logic import group_key

    def fix_item(item):
        if isinstance(item, dict) and "schema" in item:
            return {**item, "schema": rename.get(item["schema"], item["schema"])}
        key = group_key(item)
        if key:
            inner = item[key]
            if isinstance(inner, dict):
                return {key: fix_item(inner)}
            return {key: [fix_item(i) for i in inner]}
        return item

    def fix(items):
        return [fix_item(i) for i in items or []]

    for page in result.pages:
        page.name = f"{prefix}{page.name}"
        for q in page.questions:
            q["name"] = rename[q["name"]]
            if q.get("display_logic"):
                q["display_logic"]["show_when"] = fix(q["display_logic"]["show_when"])
        for rule in (page.show_when, page.exit_when):
            if rule:
                rule["show_when"] = fix(rule["show_when"])
    for cb in result.counterbalance:
        cb["pages"] = [f"{prefix}{p}" for p in cb.get("pages", [])]
    result.name_map = {k: rename.get(v, v) for k, v in result.name_map.items()}
