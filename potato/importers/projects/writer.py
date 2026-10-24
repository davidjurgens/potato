"""
Write a :class:`ProjectImportResult` out as a runnable Potato project.

Suggestions become pre-annotations, exactly as in the CV and text importers.
People's answers are only written as those people's saved work when the caller
asks (`--keep-annotators`): they are real annotations by real, named people,
which is what an agreement report needs, but writing them means the study
starts with those items done, and that is the caller's decision.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from potato.importers._common import assert_unique_ids
from potato.importers.text.project import PREDICTION_FIELD, SCHEMA_MODELINE

from .base import ProjectImportResult

logger = logging.getLogger(__name__)

#: Data column holding who made each suggestion. Nothing in Potato reads it;
#: it is there so the model name and score survive the move.
PREDICTION_SOURCES_FIELD = "prediction_sources"


def safe_username(raw: Any) -> str:
    """A login name Potato accepts and a directory name the OS accepts."""
    name = re.sub(r"[^A-Za-z0-9_.@-]+", "_", str(raw)).strip("._")
    return name or "annotator"


def label_entries(scheme: dict, value: Any) -> List[list]:
    """`[{"schema", "name"}, value]` pairs for one answer, as a browser save writes them.

    The pairs follow what the annotation page itself stores, captured from a
    live save: radio and multiselect store the option name as both name and
    value, likert the point as a string, text under `text_box`, number and
    slider their value as a string, and an image scheme one JSON list under
    `_data`. Spans are not label entries; see `span_entries`.
    """
    schema = scheme["name"]
    kind = scheme["annotation_type"]

    def entry(name, stored):
        return [{"schema": schema, "name": str(name)}, stored]

    if kind == "radio":
        return [entry(value, str(value))]
    if kind == "multiselect":
        return [entry(v, str(v)) for v in (value or [])]
    if kind == "select":
        # The dropdown's label_name is "select-one" and its value the option.
        return [entry("select-one", str(value))]
    if kind == "likert":
        return [entry(int(value), str(int(value)))]
    if kind == "text":
        return [entry("text_box", str(value))]
    if kind == "number":
        return [entry("number", str(value))]
    if kind == "slider":
        return [entry("slider", str(value))]
    if kind == "image_annotation":
        return [entry("_data", json.dumps(value or []))]
    return []


def span_entries(scheme: dict, spans: List[dict]) -> List[list]:
    schema = scheme["name"]
    return [[{"schema": schema, "name": s["label"], "title": s["label"],
              "start": int(s["start"]), "end": int(s["end"])}, "1"]
            for s in spans or []]


def prediction_value(scheme: dict, value: Any) -> Any:
    """The pre-annotation shape for one suggestion (flask_server's reader)."""
    if scheme["annotation_type"] == "span":
        return [{"start": int(s["start"]), "end": int(s["end"]),
                 "name": s["label"], "title": s["label"]} for s in value or []]
    return value


def build_config(result: ProjectImportResult, data_file: str,
                 task_name: str, keep_annotators: bool = False,
                 extra_config: Optional[dict] = None) -> dict:
    config: Dict[str, Any] = {
        "port": 8000,
        "annotation_task_name": task_name,
        "task_dir": ".",
        "output_annotation_dir": "annotation_output/",
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": result.text_key},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default",
    }
    if keep_annotators and result.annotator_ids:
        # The imported people have no Potato passwords. The roster rows the
        # writer adds carry none, which the authenticator accepts only on a
        # passwordless study; the README and the CLI both say to change this
        # before deploying.
        config["require_password"] = False
        # Closed enrolment: the imported names are the roster. Leaving
        # allow_all_users on would let anyone who finds the URL register a
        # fresh name next to people whose work is already there. Add new
        # annotators to this list (deploy preflight D022 flags the missing
        # passwords).
        config["user_config"] = {"allow_all_users": False,
                                 "users": sorted(result.annotator_ids)}
        # The source study's own overlap target. /admin/iaa scores only items
        # that have reached their annotator cap, so without it the imported
        # agreement was invisible there; with it, items the source finished are
        # complete and new annotators get the rest.
        target = result.annotations_per_item
        if target and target >= 2:
            config["max_annotations_per_item"] = target
    if result.instance_display:
        config["instance_display"] = result.instance_display
    if any(item.predictions for item in result.items):
        # Suggestions are a starting point the annotator corrects; they are
        # only stored once someone saves, so an item nobody opened exports as
        # empty rather than as a model's answer passed off as a person's.
        config["pre_annotation"] = {
            "enabled": True,
            "field": PREDICTION_FIELD,
            "allow_modification": True,
        }
    # Keys a caller adds on top (the FiftyOne backend's annotator count and
    # media folder); they win over anything above.
    config.update(extra_config or {})
    config["annotation_schemes"] = [dict(s) for s in result.schemes]
    return config


def write_project(result: ProjectImportResult, output_dir: str, source: str,
                  keep_annotators: bool = False, config_only: bool = False,
                  stem: Optional[str] = None, extra_config: Optional[dict] = None,
                  task_name: Optional[str] = None) -> List[str]:
    output = Path(output_dir)
    (output / "data").mkdir(parents=True, exist_ok=True)
    stem = stem or Path(source).stem or "imported"
    task_name = task_name or f"{stem} (imported)"
    data_rel = os.path.join("data", f"{stem}.jsonl")
    schemes = {s["name"]: s for s in result.schemes}
    written: List[str] = []

    if not config_only:
        assert_unique_ids(item.instance_id for item in result.items)
        data_path = output / data_rel
        with data_path.open("w", encoding="utf-8") as handle:
            for item in result.items:
                row: Dict[str, Any] = {"id": item.instance_id}
                row.update(item.fields)
                predictions = {name: prediction_value(schemes[name], value)
                               for name, value in item.predictions.items()
                               if name in schemes}
                if predictions:
                    row[PREDICTION_FIELD] = predictions
                if item.prediction_sources:
                    row[PREDICTION_SOURCES_FIELD] = item.prediction_sources
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        written.append(str(data_path))

        if keep_annotators:
            written.extend(_write_annotators(result, output, schemes, task_name))

    if result.media_files and not config_only:
        import shutil
        from potato.importers.projects._dh import within
        # Checked here, where every importer's files are copied: a symlink in
        # a downloaded dataset (tar and zip both carry them) would otherwise
        # copy any local file into media/, which the server publishes.
        roots = [Path(r) for r in result.media_roots] or [
            Path(source) if Path(source).is_dir() else Path(source).parent]
        for rel, src in result.media_files.items():
            if not within(Path(src), roots):
                result.warn(f"{rel}: its source {src} is outside the input folder "
                            "(a link out of it?); not copied")
                result.skipped["files outside the input folder"] += 1
                continue
            dest = output / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(src, dest)
                written.append(str(dest))

    config_path = output / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        handle.write(SCHEMA_MODELINE + "\n")
        yaml.safe_dump(build_config(result, data_rel, task_name,
                                    keep_annotators=keep_annotators,
                                    extra_config=extra_config),
                       handle, sort_keys=False, default_flow_style=False,
                       allow_unicode=True)
    written.append(str(config_path))

    readme = output / "README.md"
    if readme.exists():
        logger.info("README.md already exists; leaving it alone")
    else:
        _write_readme(readme, result, source, keep_annotators)
        written.append(str(readme))
    return written


def _write_annotators(result: ProjectImportResult, output: Path,
                      schemes: Dict[str, dict], task_name: str) -> List[str]:
    """One user_state.json per source annotator, holding their own answers."""
    by_user: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for item in result.items:
        for user, answers in item.responses.items():
            by_user.setdefault(user, {})[item.instance_id] = answers

    written = []
    for user, items in sorted(by_user.items()):
        label_to_value: Dict[str, list] = {}
        span_to_value: Dict[str, list] = {}
        for instance_id, answers in items.items():
            labels, spans = [], []
            for name, value in answers.items():
                scheme = schemes.get(name)
                if scheme is None:
                    continue
                if scheme["annotation_type"] == "span":
                    spans.extend(span_entries(scheme, value))
                else:
                    labels.extend(label_entries(scheme, value))
            if labels:
                label_to_value[instance_id] = labels
            if spans:
                span_to_value[instance_id] = spans

        ordering = list(items)
        state = {
            "user_id": user,
            "max_assignments": -1,
            "instance_id_ordering": ordering,
            "current_instance_index": 0,
            # Where the annotator is in the study. Without it the server reads
            # the person as not yet in the annotation phase and /annotate
            # redirects to itself. A study with no `phases` block has one page,
            # named after annotation_task_name, which is what a live save writes.
            "current_phase_and_page": ["annotation", task_name],
            "completed_phase_and_pages": [],
            "instance_id_to_label_to_value": label_to_value,
            "instance_id_to_span_to_value": span_to_value,
            "phase_to_page_to_label_to_value": {},
            "phase_to_page_to_span_to_value": {},
        }
        user_dir = output / "annotation_output" / user
        user_dir.mkdir(parents=True, exist_ok=True)
        path = user_dir / "user_state.json"
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        written.append(str(path))

    # The roster. The server refuses to register a name that already owns
    # annotations but is not a known account (it would hand a stranger
    # someone's work), so the imported people have to be accounts already.
    # This is the default user_config_path for output_annotation_dir
    # "annotation_output/".
    if by_user:
        roster = output / "annotation_output" / "user_config.json"
        known = set()
        if roster.exists():
            for line in roster.read_text(encoding="utf-8").splitlines():
                try:
                    known.add(json.loads(line).get("username"))
                except (ValueError, AttributeError):
                    continue
        with roster.open("a", encoding="utf-8") as handle:
            for user in sorted(by_user):
                if user not in known:
                    handle.write(json.dumps({"username": user}) + "\n")
        written.append(str(roster))
    return written


def _write_readme(path: Path, result: ProjectImportResult, source: str,
                  keep_annotators: bool) -> None:
    stats = result.summarize()
    people = ""
    if result.annotator_ids:
        rows = "\n".join(f"| `{name}` | `{origin}` |"
                         for name, origin in sorted(result.annotator_ids.items()))
        people = f"""
## Annotators

| Potato username | In the source |
|---|---|
{rows}
"""
    skipped = ""
    if result.skipped:
        rows = "\n".join(f"- {what}: {count}" for what, count in
                         sorted(result.skipped.items()))
        skipped = f"\n## Left out\n\n{rows}\n"
    guidelines = (f"\n## Guidelines from the source\n\n{result.guidelines}\n"
                  if result.guidelines else "")
    answers = (
        "Each source annotator's answers are written as that person's saved "
        "work under `annotation_output/`, so agreement can be computed straight "
        "away. Log in with the username in the table below to see them. The "
        "project is passwordless (`require_password: false`) because the "
        "imported people have no Potato passwords, and only the imported names "
        "may log in (`user_config.users`; add new annotators there). Before "
        "deploying it, set `require_password: true` and add a password to each "
        "row of `annotation_output/user_config.json`; `potato deploy` refuses "
        "a public deployment until you do."
        if keep_annotators else
        "People's answers in the source were not written as saved work. Re-run "
        "with `--keep-annotators` to bring them across."
    )
    path.write_text(f"""# Imported {result.source_format} project

Generated by `potato import` from `{Path(source).name}`.

- **Items:** {stats['num_items']}
- **Questions:** {stats['num_schemes']}
- **Annotators:** {stats['num_annotators']}
- **Answers:** {stats['num_responses']}
- **Model suggestions:** {stats['num_predictions']}

## Run it

```bash
python potato/flask_server.py start config.yaml -p 8000
```

## What came across

- Model suggestions are *pre-annotations*: shown as a starting point and stored
  only when someone saves. The model and score of each one are kept in the data
  file's `{PREDICTION_SOURCES_FIELD}` column.
- {answers}
{people}{skipped}{guidelines}""", encoding="utf-8")
