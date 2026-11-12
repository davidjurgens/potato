"""
Argilla (2.x) dataset importer.

Accepts both ways Argilla saves a dataset:

* ``dataset.to_disk(path)``: a folder with ``.argilla/settings.json`` and
  ``records.json``.
* ``dataset.to_hub(repo)``: a Hugging Face dataset whose repository carries
  ``.argilla/settings.json`` beside flattened columns
  (``<question>.responses``, ``.responses.users``, ``.responses.status``,
  ``<question>.suggestion``, ``.suggestion.score``, ``.suggestion.agent``).
  Pass a local snapshot folder, or the repo id with ``--hf-dataset``.

The two differ in one way that matters. ``records.json`` stores each response
as ``{value, user_id}`` with no status, so a discarded or draft response cannot
be told from a submitted one, and all of them are imported (with a warning).
The Hub columns keep the status, and only ``submitted`` responses are imported.

Questions map as: label_selection -> radio, multi_label_selection ->
multiselect, rating -> likert (or radio when the scale is not 1..N), text ->
text, span -> span. ``ranking`` is reported and left out.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import ProjectImportResult, ProjectItem, humanize
from .writer import safe_username

SETTINGS = Path(".argilla") / "settings.json"


class ArgillaImporter:
    format_name = "argilla"
    description = ("Argilla 2.x dataset: a to_disk folder, or a to_hub dataset "
                   "(local snapshot or --hf-dataset)")
    file_extensions: List[str] = []

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        return path.is_dir() and (path / SETTINGS).is_file()

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        path = Path(path)
        settings_path = path / SETTINGS
        if not settings_path.is_file():
            raise ValueError(f"{path} has no {SETTINGS}; is it an Argilla to_disk "
                             "folder or a to_hub dataset snapshot?")
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        result = ProjectImportResult(source_format="Argilla")
        result.guidelines = settings.get("guidelines") or ""
        distribution = settings.get("distribution") or {}
        if isinstance(distribution.get("min_submitted"), int):
            result.annotations_per_item = distribution["min_submitted"]
        questions = self._schemes(settings, result)
        self._display(settings, questions, result)

        records_path = path / "records.json"
        if records_path.is_file():
            records = json.loads(records_path.read_text(encoding="utf-8"))
            result.warn("records.json does not record whether a response was "
                        "submitted, discarded or a draft, so every response was "
                        "imported. Export with to_hub to keep the status.")
            for index, record in enumerate(records):
                if isinstance(record, dict):
                    self._nested(record, index, questions, result)
        else:
            rows = _hub_rows(path)
            if rows is None:
                raise ValueError(f"{path} has settings but neither records.json nor "
                                 "dataset files (parquet/arrow/jsonl) to read.")
            for index, row in enumerate(rows):
                self._flat(row, index, questions, result)
        if not result.annotations_per_item or result.annotations_per_item < 2:
            # min_submitted 1 is Argilla's default and says nothing about how
            # many people actually answered; use what the records show.
            most = max((len(item.responses) for item in result.items), default=0)
            result.annotations_per_item = most or None
        return result

    # --------------------------------------------------------------- settings
    def _schemes(self, settings, result) -> Dict[str, dict]:
        """question name -> {"scheme": ..., "type": ..., "values": [...]}"""
        questions: Dict[str, dict] = {}
        for q in settings.get("questions") or []:
            name = q.get("name")
            spec = q.get("settings") or {}
            kind = spec.get("type")
            options = [o for o in spec.get("options") or [] if isinstance(o, dict)]
            values = [o.get("value") for o in options]
            scheme: Dict[str, Any] = {
                "name": name,
                "description": q.get("description") or q.get("title") or humanize(name),
            }
            if q.get("required"):
                scheme["label_requirement"] = {"required": True}
            if kind == "label_selection":
                scheme.update(annotation_type="radio", labels=[str(v) for v in values])
            elif kind == "multi_label_selection":
                scheme.update(annotation_type="multiselect", labels=[str(v) for v in values])
            elif kind == "rating":
                ints = [v for v in values if isinstance(v, int)]
                if ints and sorted(ints) == list(range(1, len(ints) + 1)):
                    scheme.update(annotation_type="likert", size=len(ints),
                                  min_label="1", max_label=str(len(ints)))
                else:
                    # A 0..10 or sparse scale has no 1..N likert equivalent;
                    # radio keeps every value exactly.
                    scheme.update(annotation_type="radio", labels=[str(v) for v in values],
                                  horizontal=True)
                    kind = "rating_as_radio"
            elif kind == "text":
                scheme["annotation_type"] = "text"
                scheme["multiline"] = True
            elif kind == "span":
                scheme.update(annotation_type="span",
                              labels=[{"name": str(v)} for v in values])
            else:
                result.skipped[f"{kind} questions"] += 1
                result.warn(f"The {kind} question '{name}' has no Potato equivalent "
                            "in this importer and was left out, with its answers.")
                continue
            questions[name] = {"scheme": scheme, "type": kind,
                               "field": spec.get("field")}
            result.schemes.append(scheme)
        return questions

    def _display(self, settings, questions, result) -> None:
        fields = [f for f in settings.get("fields") or [] if isinstance(f, dict)]
        kinds = {f.get("name"): (f.get("settings") or {}).get("type", "text") for f in fields}
        span_fields = {q["field"] for q in questions.values() if q["type"] == "span"}
        shown = [f.get("name") for f in fields if kinds.get(f.get("name")) in ("text", "image", "chat")]
        if not shown:
            return
        result.text_key = next(iter(span_fields & set(shown)), shown[0])
        if "chat" in kinds.values():
            result.warn("Chat fields are shown as text: each message on its own line, "
                        "prefixed with its role.")
        if len(shown) > 1:
            display = []
            for field_name in shown:
                kind = kinds[field_name]
                entry = {"key": field_name, "type": "image" if kind == "image" else "text",
                         "label": next((f.get("title") for f in fields
                                        if f.get("name") == field_name), None) or humanize(field_name)}
                if field_name in span_fields:
                    entry["span_target"] = True
                display.append(entry)
            result.instance_display = {"fields": display}
        result._chat_fields = {n for n, k in kinds.items() if k == "chat"}

    # ---------------------------------------------------------------- records
    def _item(self, record_id, index, fields, result) -> ProjectItem:
        values = dict(fields)
        for name in getattr(result, "_chat_fields", ()):
            if isinstance(values.get(name), list):
                values[name] = "\n".join(
                    f"{m.get('role', '')}: {m.get('content', '')}" if isinstance(m, dict) else str(m)
                    for m in values[name])
        # A record without an id gets one that cannot collide with a real id.
        return ProjectItem(instance_id=str(record_id) if record_id else f"argilla_record_{index}",
                           fields=values)

    def _nested(self, record, index, questions, result) -> None:
        item = self._item(record.get("id") or record.get("_server_id"), index,
                          record.get("fields") or {}, result)
        if record.get("metadata"):
            item.fields["metadata"] = record["metadata"]
        for qname, responses in (record.get("responses") or {}).items():
            for response in responses or []:
                self._answer(item, qname, response.get("value"), response.get("user_id"),
                             questions, result)
        for qname, suggestion in (record.get("suggestions") or {}).items():
            self._suggest(item, qname, suggestion or {}, questions)
        result.items.append(item)

    def _flat(self, row, index, questions, result) -> None:
        fields = {k: v for k, v in row.items()
                  if "." not in k and k not in ("id", "_server_id", "status")}
        item = self._item(row.get("id") or row.get("_server_id"), index, fields, result)
        for qname in questions:
            values = row.get(f"{qname}.responses") or []
            users = row.get(f"{qname}.responses.users") or []
            statuses = row.get(f"{qname}.responses.status") or []
            for i, value in enumerate(values):
                status = statuses[i] if i < len(statuses) else None
                if status not in (None, "submitted"):
                    result.skipped[f"{status} responses"] += 1
                    continue
                self._answer(item, qname, value, users[i] if i < len(users) else None,
                             questions, result)
            if row.get(f"{qname}.suggestion") is not None:
                self._suggest(item, qname, {
                    "value": row.get(f"{qname}.suggestion"),
                    "score": row.get(f"{qname}.suggestion.score"),
                    "agent": row.get(f"{qname}.suggestion.agent"),
                }, questions)
        result.items.append(item)

    @staticmethod
    def _user(user_id, result) -> str:
        origin = str(user_id) if user_id else "unknown"
        name = safe_username(f"argilla_{origin[:8]}")
        result.annotator_ids[name] = origin
        return name

    def _answer(self, item, qname, value, user_id, questions, result) -> None:
        question = questions.get(qname)
        if question is None or value is None:
            if question is None:
                result.skipped["answers to questions left out"] += 1
            return
        converted = _convert(question, value, item, result)
        if converted is not None:
            item.responses.setdefault(self._user(user_id, result), {})[qname] = converted

    @staticmethod
    def _suggest(item, qname, suggestion, questions) -> None:
        question = questions.get(qname)
        if question is None or suggestion.get("value") is None:
            return
        converted = _convert(question, suggestion["value"], item, None)
        if converted is None:
            return
        item.predictions[qname] = converted
        item.prediction_sources[qname] = {k: v for k, v in (
            ("model", suggestion.get("agent")), ("score", suggestion.get("score")))
            if v is not None}


def _convert(question, value, item, result) -> Any:
    kind = question["type"]
    if kind == "label_selection" or kind == "rating_as_radio":
        return str(value)
    if kind == "multi_label_selection":
        return [str(v) for v in (value if isinstance(value, list) else [value])]
    if kind == "rating":
        return int(value)
    if kind == "text":
        return str(value)
    if kind == "span":
        spans = []
        for span in value if isinstance(value, list) else []:
            if not isinstance(span, dict) or span.get("start") is None:
                continue
            # Argilla validates span offsets against the field text on its
            # Python server, so they are code points already.
            spans.append({"start": int(span["start"]), "end": int(span["end"]),
                          "label": str(span.get("label"))})
        return spans
    return None


def _hub_rows(path: Path) -> Optional[List[dict]]:
    """Rows of a to_hub dataset snapshot, via the datasets library."""
    files = (sorted(path.rglob("*.parquet")) or sorted(path.rglob("*.arrow"))
             or sorted(p for p in path.rglob("*.jsonl") if ".argilla" not in p.parts))
    if not files:
        return None
    try:
        import datasets  # lazy: heavy, and only needed for this path
    except ImportError as exc:
        raise ValueError("Reading a to_hub dataset needs the `datasets` package: "
                         "pip install datasets") from exc
    builder = {".parquet": "parquet", ".arrow": "arrow", ".jsonl": "json"}[files[0].suffix]
    dataset = datasets.load_dataset(builder, data_files=[str(f) for f in files], split="train")
    return [dict(row) for row in dataset]


def download_hub_dataset(repo_id: str, target: Path) -> Path:
    """Fetch a to_hub dataset repository (settings plus data) into ``target``."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ValueError("Importing from the Hub needs huggingface_hub: "
                         "pip install huggingface_hub") from exc
    return Path(snapshot_download(repo_id=repo_id, repo_type="dataset",
                                  local_dir=str(target)))
