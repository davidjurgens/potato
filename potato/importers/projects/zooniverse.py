"""
Zooniverse project importer.

Input is one of:

* a directory holding the project's exports: the workflow export
  (``*workflows*.csv``), the classification export (``*classifications*.csv``)
  and, optionally, the subject export (``*subjects*.csv``), which is the only
  export that carries the subjects' image, audio or video URLs;
* the classification export alone, with ``options["workflow"]`` naming the
  workflow export (CSV or API JSON) when it is not in the same directory;
* a workflow on its own, as the workflow export CSV or the Panoptes API JSON
  (``{"workflows": [...]}`` or one workflow object). This brings the questions
  across with no items.

Options: ``workflow`` (path), ``subjects`` (path), ``workflow_id``, and
``workflow_version`` (``"16.55"`` or ``"16"``).

One workflow version is imported. Zooniverse bumps the major version when the
tasks change and the minor version when only their text does, so the default
is the latest major version the classifications use; classifications made
under other major versions are counted as skipped. Minor versions are read
with their own strings, so an answer whose label was later reworded still
lands on the right option.

Tasks map as:

    single            radio
    multiple          multiselect
    shortcut          multiselect (the shortcut options)
    dropdown-simple   select (radio until the writer stores select answers)
    dropdown          select, when it is one list with no conditions
    text              text
    slider            slider
    drawing           image_annotation: point -> landmark, rectangle -> bbox,
                      polygon -> polygon, line -> polyline, circle and
                      ellipse -> ellipse, freehand* -> freeform
    highlighter       span, when the subject text is available
    combo             its sub-tasks, each mapped as above

Survey tasks, drawing-tool detail questions, transcription, crop and
data-vis tasks are reported with their counts and left out.

Zooniverse shows a workflow's tasks one after another and branches on the
answers to single-answer questions. Potato shows every question on the item
page, so each task reached only through particular answers gets a
``display_logic`` rule built from every path that leads to it: the item page
shows the same questions the volunteer would have seen.

Each volunteer's classifications become that person's responses. A volunteer
who was not logged in becomes ``anon_<hash>`` of the not-logged-in id
Zooniverse assigns (which is derived from their IP address).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from potato.export.cv_utils import to_client_object

from .base import (SUPPORTED_TYPES, ProjectImportResult, ProjectItem, humanize,
                   utf16_to_code_points)
from .writer import safe_username

#: Drawing tool type -> image_annotation tool.
DRAWING_TOOLS = {
    "point": "landmark",
    "rectangle": "bbox",
    "polygon": "polygon",
    "line": "polyline",
    "circle": "ellipse",
    "ellipse": "ellipse",
    "freehand": "freeform",
    "freehandLine": "freeform",
    "freehandShape": "freeform",
    "freehandSegmentLine": "freeform",
    "freehandSegmentShape": "freeform",
}

#: Task types reported and left out, with the reason given in the warning.
REPORTED_TASKS = {
    "survey": "a survey task (species choices with follow-up questions) has no "
              "Potato equivalent",
    "transcription": "transcription tasks (lines with transcribed text) have no "
                     "Potato equivalent in this importer",
    "dataVisAnnotation": "data-vis annotation tasks have no Potato equivalent",
    "crop": "crop tasks have no Potato equivalent",
}

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg")
AUDIO_EXT = (".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac")
VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v", ".ogv")
TEXT_EXT = (".txt",)

#: Subject metadata keys a text subject's own text may be kept under.
TEXT_KEYS = ("text", "#text", "Text")

PROVENANCE = {"source": "import", "import_format": "zooniverse"}

_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|~~)")


# ------------------------------------------------------------------ helpers

def _read_csv(path: Path) -> List[Dict[str, str]]:
    # Exports hold whole JSON documents in single cells.
    csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _csv_header(path: Path) -> List[str]:
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def _csv_kind(path: Path) -> Optional[str]:
    """``classifications`` / ``workflows`` / ``subjects`` from a CSV's header."""
    header = set(_csv_header(path))
    if {"classification_id", "annotations", "subject_ids"} <= header:
        return "classifications"
    if {"workflow_id", "tasks", "first_task", "version"} <= header:
        return "workflows"
    if {"subject_id", "locations"} <= header:
        return "subjects"
    return None


def _json(text: Any, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return default


def _workflow_objects(data: Any) -> Optional[List[dict]]:
    """The workflow objects in an API response or a bare workflow."""
    if isinstance(data, dict) and isinstance(data.get("workflows"), list):
        found = [w for w in data["workflows"] if isinstance(w, dict) and "tasks" in w]
        return found or None
    if isinstance(data, dict) and isinstance(data.get("tasks"), dict) and (
            "first_task" in data or "steps" in data):
        return [data]
    return None


def _json_workflows(path: Path) -> Optional[List[dict]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return _workflow_objects(data)


def _version(text: Any) -> Tuple[Optional[int], Optional[int]]:
    """``"16.55"`` -> (16, 55); ``"16"`` -> (16, None)."""
    if text is None or str(text).strip() == "":
        return None, None
    parts = str(text).strip().split(".")
    try:
        major = int(parts[0])
    except ValueError:
        return None, None
    try:
        minor = int(parts[1]) if len(parts) > 1 and parts[1] != "" else None
    except ValueError:
        minor = None
    return major, minor


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return int(number) if number.is_integer() else number


def clean_text(text: Any) -> str:
    """Zooniverse markdown -> plain text (image tags give their alt text)."""
    if not isinstance(text, str):
        return "" if text is None else str(text)
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_EMPHASIS.sub("", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def _image_alt(text: Any) -> str:
    match = _MD_IMAGE.search(text) if isinstance(text, str) else None
    return re.sub(r"\.(png|jpe?g|gif|svg|webp)$", "", match.group(1).strip(),
                  flags=re.IGNORECASE) if match else ""


def _resolve_strings(value: Any, strings: Dict[str, str]) -> Any:
    """Replace translation keys (``"T0.question"``) with their text."""
    if not strings:
        return value
    if isinstance(value, str):
        return strings.get(value, value)
    if isinstance(value, list):
        return [_resolve_strings(v, strings) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_strings(v, strings) for k, v in value.items()}
    return value


def _unique_labels(raw: Sequence[Any], what: str, result: ProjectImportResult) -> List[str]:
    """Clean, non-empty, distinct option names, in the source order."""
    labels: List[str] = []
    seen: Counter = Counter()
    for index, text in enumerate(raw):
        name = clean_text(text) or _image_alt(text) or f"Option {index + 1}"
        name = name.replace(":::", ":")
        seen[name] += 1
        if seen[name] > 1:
            result.warn(f"{what} has two options that read '{name}'; the second "
                        f"is named '{name} ({seen[name]})'.")
            name = f"{name} ({seen[name]})"
        labels.append(name)
    return labels


def _media_type(mime: str, url: str) -> Optional[str]:
    mime = (mime or "").lower()
    for kind in ("image", "audio", "video"):
        if mime.startswith(kind + "/"):
            return kind
    if mime.startswith("text/"):
        return "text"
    path = str(url).split("?")[0].lower()
    for kind, exts in (("image", IMAGE_EXT), ("audio", AUDIO_EXT),
                       ("video", VIDEO_EXT), ("text", TEXT_EXT)):
        if path.endswith(exts):
            return kind
    return None


def _locations(raw: Any) -> List[Tuple[Optional[str], str]]:
    """(media type, url) for each frame, from either export shape.

    The subject export writes ``{"0": url, "1": url}``; the API writes
    ``[{"image/png": url}, ...]``.
    """
    raw = _json(raw, raw)
    out: List[Tuple[Optional[str], str]] = []
    if isinstance(raw, dict):
        keys = sorted(raw, key=lambda k: (not str(k).isdigit(), int(k) if str(k).isdigit() else 0, str(k)))
        for key in keys:
            url = raw[key]
            if isinstance(url, str) and url:
                out.append((_media_type("" if str(key).isdigit() else str(key), url), url))
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                for mime, url in entry.items():
                    if isinstance(url, str) and url:
                        out.append((_media_type(mime, url), url))
            elif isinstance(entry, str) and entry:
                out.append((_media_type("", entry), entry))
    return out


# ------------------------------------------------------------------ model

@dataclass
class Workflow:
    workflow_id: str
    major: Optional[int]
    minor: Optional[int]
    tasks: Dict[str, dict]
    first_task: str
    steps: list = field(default_factory=list)
    name: str = ""

    @property
    def version(self) -> str:
        if self.major is None:
            return "unknown"
        return f"{self.major}.{self.minor}" if self.minor is not None else str(self.major)


def _workflow_from_row(row: Dict[str, str]) -> Workflow:
    strings = _json(row.get("strings"), {}) or {}
    tasks = _resolve_strings(_json(row.get("tasks"), {}) or {}, strings)
    major, _ = _version(row.get("version"))
    minor = _number(row.get("minor_version"))
    return Workflow(workflow_id=str(row.get("workflow_id") or ""), major=major,
                    minor=int(minor) if minor is not None else None,
                    tasks=tasks if isinstance(tasks, dict) else {},
                    first_task=row.get("first_task") or "",
                    steps=_json(row.get("steps"), []) or [],
                    name=row.get("display_name") or "")


def _workflow_from_api(obj: dict) -> Workflow:
    strings = obj.get("strings") if isinstance(obj.get("strings"), dict) else {}
    tasks = _resolve_strings(obj.get("tasks") or {}, strings)
    major, minor = _version(obj.get("version"))
    return Workflow(workflow_id=str(obj.get("id") or ""), major=major, minor=minor,
                    tasks=tasks if isinstance(tasks, dict) else {},
                    first_task=obj.get("first_task") or "",
                    steps=obj.get("steps") or [], name=obj.get("display_name") or "")


@dataclass
class _Node:
    """What Zooniverse shows on one screen: a task, a combo, or a step."""
    key: str
    tasks: List[str]
    #: (target node key, (single task key, answer index) or None)
    edges: List[Tuple[str, Optional[Tuple[str, int]]]] = field(default_factory=list)


# ------------------------------------------------------------------ importer

class ZooniverseImporter:
    format_name = "zooniverse"
    description = ("Zooniverse project: workflow export (CSV or API JSON) with the "
                   "classification export CSV, optionally the subject export")
    file_extensions = [".csv", ".json"]

    # ------------------------------------------------------------ detection
    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if path.is_dir():
            files = self._scan(path)
            return bool(files["classifications"] or files["workflows"])
        if not path.is_file():
            return False
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return _csv_kind(path) in ("classifications", "workflows")
        if suffix == ".json":
            try:
                with path.open(encoding="utf-8-sig") as handle:
                    head = handle.read(1024).lstrip()
            except (OSError, UnicodeDecodeError):
                return False
            if not head.startswith("{"):
                return False
            return _json_workflows(path) is not None
        return False

    @staticmethod
    def _scan(directory: Path) -> Dict[str, List[Path]]:
        found: Dict[str, List[Path]] = {"classifications": [], "workflows": [],
                                        "subjects": [], "workflow_json": []}
        for child in sorted(directory.iterdir()):
            if not child.is_file():
                continue
            if child.suffix.lower() == ".csv":
                kind = _csv_kind(child)
                if kind:
                    found[kind].append(child)
            elif child.suffix.lower() == ".json" and _json_workflows(child):
                found["workflow_json"].append(child)
        return found

    # ------------------------------------------------------------ parse
    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = dict(options or {})
        path = Path(path)
        classification_files: List[Path] = []
        workflow_files: List[Path] = []
        subject_files: List[Path] = []

        if path.is_dir():
            files = self._scan(path)
            classification_files = files["classifications"]
            workflow_files = files["workflows"] + files["workflow_json"]
            subject_files = files["subjects"]
        elif path.suffix.lower() == ".csv" and _csv_kind(path) == "classifications":
            classification_files = [path]
            sibling = self._scan(path.parent)
            workflow_files = sibling["workflows"] + sibling["workflow_json"]
            subject_files = sibling["subjects"]
        elif path.suffix.lower() == ".csv" and _csv_kind(path) == "workflows":
            workflow_files = [path]
        elif path.suffix.lower() == ".json" and _json_workflows(path):
            workflow_files = [path]
        else:
            raise ValueError(f"{path} is not a Zooniverse workflow or classification "
                             "export, or a directory holding them")
        if options.get("workflow"):
            workflow_files = [Path(options["workflow"])]
        if options.get("subjects"):
            subject_files = [Path(options["subjects"])]
        if len(classification_files) > 1:
            raise ValueError("More than one classification export: "
                             + ", ".join(p.name for p in classification_files)
                             + ". Pass the one to import.")
        if not workflow_files:
            raise ValueError("No workflow export found. A classification export only "
                             "names its tasks; pass the workflow export (Lab > Data "
                             "exports > workflows) with options workflow=<path>, or "
                             "put it in the same directory.")

        workflows = self._load_workflows(workflow_files)
        rows = _read_csv(classification_files[0]) if classification_files else []

        result = ProjectImportResult(source_format="Zooniverse")
        workflow = self._choose(workflows, rows, options, result)
        same_major = {w.minor: w for w in workflows
                      if w.workflow_id == workflow.workflow_id and w.major == workflow.major}

        converters = self._schemes(workflow, result)
        result.guidelines = self._guidelines(workflow, converters)
        subjects = self._read_subjects(subject_files, workflow, result)
        responses: Dict[str, Dict[str, Dict[str, Any]]] = {}
        if rows:
            responses = self._classifications(rows, workflow, same_major, converters,
                                              subjects, result)
        elif classification_files:
            result.warn("The classification export has no rows.")
        if subjects:
            self._items(subjects, converters, responses, result)
        most = max((len(item.responses) for item in result.items), default=0)
        result.annotations_per_item = most or None
        return result

    # ------------------------------------------------------------ workflows
    @staticmethod
    def _load_workflows(files: Iterable[Path]) -> List[Workflow]:
        workflows: List[Workflow] = []
        for f in files:
            f = Path(f)
            if f.suffix.lower() == ".json":
                objects = _json_workflows(f)
                if not objects:
                    raise ValueError(f"{f} holds no Zooniverse workflow")
                workflows.extend(_workflow_from_api(o) for o in objects)
            else:
                if _csv_kind(f) != "workflows":
                    raise ValueError(f"{f} is not a Zooniverse workflow export")
                workflows.extend(_workflow_from_row(r) for r in _read_csv(f))
        workflows = [w for w in workflows if w.tasks]
        if not workflows:
            raise ValueError("The workflow export holds no workflow with tasks")
        return workflows

    @staticmethod
    def _choose(workflows: List[Workflow], rows: List[dict], options: dict,
                result: ProjectImportResult) -> Workflow:
        ids = sorted({w.workflow_id for w in workflows})
        wanted = options.get("workflow_id")
        if wanted is not None and str(wanted) != "":
            wanted = str(wanted)
            if wanted not in ids:
                raise ValueError(f"Workflow {wanted} is not in the workflow export "
                                 f"(it has {', '.join(ids)})")
        else:
            used = Counter(str(r.get("workflow_id") or "") for r in rows)
            in_both = [wid for wid, _ in used.most_common() if wid in ids]
            if in_both:
                wanted = in_both[0]
                if len(in_both) > 1:
                    result.warn(f"The classifications cover workflows {', '.join(in_both)}; "
                                f"workflow {wanted} (the most classified) was imported. "
                                "Pass workflow_id to choose another.")
            elif len(ids) == 1:
                wanted = ids[0]
            else:
                wanted = ids[0]
                result.warn(f"The workflow file holds workflows {', '.join(ids)}; "
                            f"workflow {wanted} was imported. Pass workflow_id to "
                            "choose another.")
        candidates = [w for w in workflows if w.workflow_id == wanted]
        majors = {w.major for w in candidates}

        major, minor = _version(options.get("workflow_version"))
        if major is not None:
            if major not in majors:
                raise ValueError(f"Workflow {wanted} has no version {major} in the "
                                 f"workflow export (it has "
                                 f"{', '.join(str(m) for m in sorted(majors, key=lambda m: m or 0))})")
        else:
            seen = [_version(r.get("workflow_version")) for r in rows
                    if str(r.get("workflow_id") or "") == wanted]
            usable = [v for v in seen if v[0] in majors]
            if usable:
                major, minor = max(usable, key=lambda v: (v[0], v[1] or 0))
            else:
                major = max(majors, key=lambda m: m or 0)
                if seen:
                    result.warn("None of the classifications were made with a workflow "
                                "version the workflow export has; the latest version "
                                f"there ({major}) was used, and no answers match it.")
        same = [w for w in candidates if w.major == major]
        exact = [w for w in same if minor is not None and w.minor == minor]
        return exact[0] if exact else max(same, key=lambda w: w.minor or 0)

    # ------------------------------------------------------------ schemes
    def _schemes(self, workflow: Workflow, result: ProjectImportResult) -> Dict[str, dict]:
        """One converter per task that became a scheme, keyed by task key."""
        tasks = workflow.tasks
        nodes, entry = self._nodes(workflow, result)
        conditions, order = self._conditions(nodes, entry, tasks, result)

        shown = [t for key in order for t in nodes[key].tasks]
        for key in tasks:
            if key not in shown and not self._is_subtask(key, tasks):
                result.skipped["tasks no path reaches (never shown)"] += 1
                result.warn(f"Task {key} is not reached from the first task "
                            f"({workflow.first_task}) by any answer, so volunteers "
                            "never saw it; it was left out.")

        converters: Dict[str, dict] = {}
        node_of = {t: key for key in order for t in nodes[key].tasks}
        for task_key in shown:
            task = tasks.get(task_key)
            if not isinstance(task, dict):
                continue
            converter = self._scheme_for(task_key, task, result)
            if converter is None:
                continue
            converters[task_key] = converter
        # display_logic after every scheme exists: a rule may only name radios.
        for task_key, converter in converters.items():
            rule = self._display_logic(conditions[node_of[task_key]], tasks, converters)
            if rule:
                converter["scheme"]["display_logic"] = rule
            result.schemes.append(converter["scheme"])
        return converters

    @staticmethod
    def _is_subtask(key: str, tasks: Dict[str, dict]) -> bool:
        for task in tasks.values():
            if not isinstance(task, dict):
                continue
            if task.get("type") == "combo" and key in (task.get("tasks") or []):
                return True
            if task.get("unlinkedTask") == key:
                return True
        return False

    def _nodes(self, workflow: Workflow, result) -> Tuple[Dict[str, _Node], Optional[str]]:
        tasks = workflow.tasks
        steps = [s for s in workflow.steps or []
                 if isinstance(s, (list, tuple)) and len(s) == 2 and isinstance(s[1], dict)]
        nodes: Dict[str, _Node] = {}

        def members(task_key: str) -> List[str]:
            task = tasks.get(task_key) or {}
            keys = list(task.get("tasks") or []) if task.get("type") == "combo" else [task_key]
            out = []
            for k in keys:
                out.append(k)
                linked = (tasks.get(k) or {}).get("unlinkedTask")
                if linked and linked in tasks and linked not in out:
                    out.append(linked)
            return out

        if steps:
            step_of_task = {}
            for key, body in steps:
                nodes[key] = _Node(key=key, tasks=[t for k in body.get("taskKeys") or []
                                                   for t in members(k)])
                for t in body.get("taskKeys") or []:
                    step_of_task.setdefault(t, key)

            def target(ref):
                if not ref:
                    return None
                if ref in nodes:
                    return ref
                return step_of_task.get(ref)

            for key, body in steps:
                self._edges(nodes[key], body.get("next"), tasks, target, result)
            entry = steps[0][0]
            if workflow.first_task and workflow.first_task in step_of_task:
                entry = step_of_task[workflow.first_task]
            return nodes, entry

        for key, task in tasks.items():
            if isinstance(task, dict) and not self._is_subtask(key, tasks):
                nodes[key] = _Node(key=key, tasks=members(key))

        def target(ref):
            return ref if ref in nodes else None

        for key, node in nodes.items():
            self._edges(node, tasks[key].get("next"), tasks, target, result)
        entry = workflow.first_task if workflow.first_task in nodes else None
        if entry is None and nodes:
            entry = next(iter(nodes))
            result.warn(f"The workflow names no usable first task; {entry} was used.")
        return nodes, entry

    @staticmethod
    def _edges(node: _Node, default_next, tasks, target, result) -> None:
        """Conditional edges from the branching single task, else default_next."""
        for task_key in node.tasks:
            task = tasks.get(task_key) or {}
            answers = task.get("answers") or []
            if task.get("type") != "single" or not any(
                    isinstance(a, dict) and a.get("next") for a in answers):
                continue
            for index, answer in enumerate(answers):
                ref = (answer.get("next") if isinstance(answer, dict) else None) or default_next
                dest = target(ref)
                if ref and dest is None:
                    result.warn(f"Task {task_key} answer {index + 1} leads to {ref}, "
                                "which the workflow does not define; that path ends there.")
                if dest:
                    node.edges.append((dest, (task_key, index)))
            return
        dest = target(default_next)
        if default_next and dest is None:
            result.warn(f"{node.key} leads to {default_next}, which the workflow "
                        "does not define; that path ends there.")
        if dest:
            node.edges.append((dest, None))

    @staticmethod
    def _conditions(nodes: Dict[str, _Node], entry: Optional[str], tasks,
                    result) -> Tuple[Dict[str, List[dict]], List[str]]:
        """For each reachable node, the paths (task -> allowed answers) to it."""
        if entry is None:
            return {}, []
        # Depth-first order; an edge back to a node on the current path is a
        # cycle, which a show/hide page cannot express. It is reported and
        # dropped, so every other path still counts.
        state: Dict[str, int] = {}
        post: List[str] = []
        dropped = set()

        def visit(key: str) -> None:
            stack = [(key, iter(nodes[key].edges))]
            state[key] = 1
            while stack:
                current, edges = stack[-1]
                advanced = False
                for index_edge in edges:
                    dest, cond = index_edge
                    if state.get(dest) == 1:
                        dropped.add((current, dest, cond))
                        result.skipped["branches that loop back (cycles)"] += 1
                        result.warn(f"{current} leads back to {dest}, an earlier "
                                    "task on the same path. Potato shows each "
                                    "question once, so the loop was dropped.")
                        continue
                    if dest not in state:
                        state[dest] = 1
                        stack.append((dest, iter(nodes[dest].edges)))
                        advanced = True
                        break
                if not advanced:
                    state[current] = 2
                    post.append(current)
                    stack.pop()

        visit(entry)
        # Topological order over the kept edges, ties broken by where each
        # node sits in the workflow, so the questions keep the source's order.
        position = {key: i for i, key in enumerate(nodes)}
        indegree = {key: 0 for key in post}
        for key in post:
            for dest, cond in nodes[key].edges:
                if (key, dest, cond) not in dropped:
                    indegree[dest] += 1
        ready = sorted((k for k, n in indegree.items() if n == 0), key=position.get)
        order: List[str] = []
        while ready:
            key = ready.pop(0)
            order.append(key)
            for dest, cond in nodes[key].edges:
                if (key, dest, cond) in dropped:
                    continue
                indegree[dest] -= 1
                if indegree[dest] == 0:
                    ready.append(dest)
                    ready.sort(key=position.get)
        paths: Dict[str, List[dict]] = {key: [] for key in order}
        paths[entry] = [{}]
        for key in order:
            paths[key] = _simplify(paths[key], tasks)
            for dest, cond in nodes[key].edges:
                if (key, dest, cond) in dropped:
                    continue
                for path in paths[key]:
                    new = dict(path)
                    if cond is not None:
                        task_key, index = cond
                        new[task_key] = frozenset({index})
                    paths[dest].append(new)
        return paths, order

    @staticmethod
    def _display_logic(paths: List[dict], tasks, converters) -> Optional[dict]:
        if not paths or any(not p for p in paths):
            return None

        def condition(task_key: str, allowed) -> Optional[dict]:
            converter = converters.get(task_key)
            if converter is None:
                return None
            labels = converter["labels"]
            values = [labels[i] for i in sorted(allowed) if i < len(labels)]
            if not values:
                return None
            return {"schema": converter["scheme"]["name"], "operator": "equals",
                    "value": values[0] if len(values) == 1 else values}

        items = []
        for path in paths:
            conds = [c for c in (condition(t, s) for t, s in sorted(
                path.items(), key=lambda kv: list(tasks).index(kv[0])
                if kv[0] in tasks else 0)) if c]
            if not conds:
                return None
            items.append(conds[0] if len(conds) == 1 else {"all": conds})
        if len(items) == 1:
            only = items[0]
            return {"show_when": only["all"] if "all" in only else [only], "logic": "all"}
        return {"show_when": items, "logic": "any"}

    def _scheme_for(self, key: str, task: dict, result: ProjectImportResult) -> Optional[dict]:
        kind = task.get("type")
        text = task.get("question") or task.get("instruction") or ""
        description = clean_text(text) or humanize(key)
        scheme: Dict[str, Any] = {"name": key, "description": description}
        required = _truthy(task.get("required"))
        what = f"Task {key} ({kind})"

        if kind in ("single", "multiple", "shortcut"):
            raw = [a.get("label") if isinstance(a, dict) else a
                   for a in task.get("answers") or []]
            if not raw:
                result.warn(f"{what} has no answers; left out.")
                result.skipped["tasks with no answers"] += 1
                return None
            labels = _unique_labels(raw, what, result)
            scheme["annotation_type"] = "radio" if kind == "single" else "multiselect"
            scheme["labels"] = labels
            if required and kind != "shortcut":
                scheme["label_requirement"] = {"required": True}
            if kind == "shortcut":
                result.warn(f"{what}: in Zooniverse choosing a shortcut option "
                            "ends the classification; in Potato the other "
                            "questions stay on the page.")
            return {"kind": kind, "scheme": scheme, "labels": labels}

        if kind in ("dropdown-simple", "dropdown"):
            options = self._dropdown_options(task, what, result)
            if options is None:
                return None
            labels = _unique_labels([o.get("label") for o in options], what, result)
            # select answers are not yet stored by the project writer; until
            # they are, a dropdown comes across as radio buttons.
            scheme["annotation_type"] = "select" if "select" in SUPPORTED_TYPES else "radio"
            if scheme["annotation_type"] == "radio":
                result.warn(f"{what} became radio buttons; Potato's select scheme "
                            "cannot yet be imported with answers.")
            scheme["labels"] = labels
            if required:
                scheme["label_requirement"] = {"required": True}
            return {"kind": kind, "scheme": scheme, "labels": labels,
                    "option_values": [o.get("value") for o in options]}

        if kind == "text":
            scheme["annotation_type"] = "text"
            scheme["multiline"] = True
            if required:
                scheme["label_requirement"] = {"required": True}
            return {"kind": kind, "scheme": scheme, "labels": []}

        if kind == "slider":
            low, high = _number(task.get("min", 0)), _number(task.get("max", 1))
            if low is None or high is None or low >= high:
                result.warn(f"{what} has an unusable range ({task.get('min')!r} to "
                            f"{task.get('max')!r}); left out.")
                result.skipped["slider tasks with no usable range"] += 1
                return None
            step = _number(task.get("step")) or 1
            start = _number(task.get("defaultValue"))
            scheme.update(annotation_type="slider", min_value=low, max_value=high,
                          starting_value=start if start is not None else low, step=step)
            if any(isinstance(v, float) for v in (low, high, step)):
                result.warn(f"{what} runs {low} to {high} in steps of {step}. Potato's "
                            "slider reads its range and step as whole numbers, so check "
                            "the control before annotating with it; the imported "
                            "values are stored as given.")
            return {"kind": kind, "scheme": scheme, "labels": []}

        if kind == "drawing":
            return self._drawing_scheme(key, task, scheme, what, result)

        if kind == "highlighter":
            raw = [h.get("label") for h in task.get("highlighterLabels") or []
                   if isinstance(h, dict)]
            if not raw:
                result.warn(f"{what} has no labels; left out.")
                result.skipped["tasks with no answers"] += 1
                return None
            labels = _unique_labels(raw, what, result)
            scheme.update(annotation_type="span", labels=labels)
            return {"kind": kind, "scheme": scheme, "labels": labels}

        reason = REPORTED_TASKS.get(kind, f"'{kind}' tasks have no Potato equivalent "
                                          "in this importer")
        detail = ""
        if kind == "survey":
            detail = (f" ({len(task.get('choices') or {})} choices, "
                      f"{len(task.get('questions') or {})} follow-up questions)")
        result.skipped[f"{kind} tasks"] += 1
        result.warn(f"{what}{detail}: {reason}; it was left out, with its answers.")
        return None

    @staticmethod
    def _dropdown_options(task: dict, what: str, result) -> Optional[List[dict]]:
        if task.get("type") == "dropdown-simple":
            options = [o for o in task.get("options") or [] if isinstance(o, dict)]
            if not options:
                result.warn(f"{what} has no options; left out.")
                result.skipped["tasks with no answers"] += 1
                return None
            if task.get("allowCreate"):
                result.warn(f"{what} lets volunteers type their own option; typed "
                            "answers are counted and left out.")
            return options
        selects = [s for s in task.get("selects") or [] if isinstance(s, dict)]
        if len(selects) != 1 or set((selects[0].get("options") or {})) != {"*"} \
                or selects[0].get("condition"):
            result.skipped["dropdown tasks with several or dependent lists"] += 1
            result.warn(f"{what} has {len(selects)} linked lists; only a single "
                        "list with no conditions is imported, so it was left out.")
            return None
        options = [o for o in selects[0]["options"]["*"] if isinstance(o, dict)]
        if not options:
            result.warn(f"{what} has no options; left out.")
            result.skipped["tasks with no answers"] += 1
            return None
        return options

    @staticmethod
    def _drawing_scheme(key, task, scheme, what, result) -> Optional[dict]:
        tools = [t for t in task.get("tools") or [] if isinstance(t, dict)]
        potato_tools: List[str] = []
        labels: List[dict] = []
        tool_map: List[Optional[Tuple[str, str]]] = []
        raw_labels = [t.get("label") for t in tools]
        names = _unique_labels(raw_labels, what, result) if tools else []
        colors = [t.get("color") for t in tools]
        use_colors = (all(isinstance(c, str) and c.startswith("#") for c in colors)
                      and len(set(c.lower() for c in colors)) == len(colors))
        for tool, name, color in zip(tools, names, colors):
            mapped = DRAWING_TOOLS.get(tool.get("type"))
            if mapped is None:
                tool_map.append(None)
                result.skipped[f"drawing tools of type '{tool.get('type')}'"] += 1
                result.warn(f"{what}: the '{tool.get('type')}' tool ({name}) has no "
                            "image_annotation equivalent; its marks were left out.")
                continue
            tool_map.append((mapped, name))
            if mapped not in potato_tools:
                potato_tools.append(mapped)
            if name not in [label["name"] for label in labels]:
                label = {"name": name}
                if use_colors:
                    label["color"] = color
                labels.append(label)
            details = tool.get("details") or []
            if details:
                result.skipped["drawing detail questions"] += len(details)
                result.warn(f"{what}: the {name} tool asks {len(details)} follow-up "
                            "question(s) about each mark; Potato has no per-mark "
                            "questions on image_annotation in this importer, so they "
                            "and their answers were left out.")
        if not potato_tools:
            result.warn(f"{what} has no tool Potato can draw with; left out.")
            result.skipped["drawing tasks with no usable tool"] += 1
            return None
        if len(potato_tools) > 1:
            result.warn(f"{what}: in Zooniverse each tool draws one label; in Potato "
                        "any label can be drawn with any of the scheme's tools.")
        scheme.update(annotation_type="image_annotation", source_field="image",
                      tools=potato_tools, labels=labels)
        return {"kind": "drawing", "scheme": scheme, "labels": [l["name"] for l in labels],
                "tool_map": tool_map}

    @staticmethod
    def _guidelines(workflow: Workflow, converters: Dict[str, dict]) -> str:
        parts = []
        if workflow.name:
            parts.append(f"Workflow: {workflow.name} (id {workflow.workflow_id}, "
                         f"version {workflow.version})")
        for key, task in workflow.tasks.items():
            help_text = (task or {}).get("help") if isinstance(task, dict) else None
            if key in converters and isinstance(help_text, str) and help_text.strip():
                parts.append(f"### {key}: {converters[key]['scheme']['description']}"
                             f"\n\n{help_text.strip()}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------ subjects
    @staticmethod
    def _read_subjects(files: List[Path], workflow: Workflow,
                       result: ProjectImportResult) -> Dict[str, dict]:
        """subject id -> {"metadata": {...}, "locations": [(type, url)]}."""
        subjects: Dict[str, dict] = {}
        other_workflow = 0
        for f in files:
            for row in _read_csv(f):
                sid = str(row.get("subject_id") or "").strip()
                if not sid:
                    continue
                wid = str(row.get("workflow_id") or "").strip()
                entry = subjects.get(sid)
                if wid and wid != workflow.workflow_id and entry is None:
                    other_workflow += 1
                    continue
                metadata = _json(row.get("metadata"), {}) or {}
                if entry is None:
                    entry = subjects[sid] = {"metadata": {}, "locations": [],
                                             "from_export": True, "dims": None}
                entry["from_export"] = True
                if isinstance(metadata, dict):
                    entry["metadata"].update(metadata)
                if not entry["locations"]:
                    entry["locations"] = _locations(row.get("locations"))
        if other_workflow:
            result.skipped["subjects linked only to other workflows"] += other_workflow
        return subjects

    def _items(self, subjects: Dict[str, dict], converters: Dict[str, dict],
               responses: Dict[str, Dict[str, Dict[str, Any]]],
               result: ProjectImportResult) -> None:
        kinds = Counter(loc[0][0] for loc in (s["locations"] for s in subjects.values()) if loc)
        media = kinds.most_common(1)[0][0] if kinds else None
        if len(kinds) > 1:
            result.warn(f"Subjects mix media types ({', '.join(f'{k}: {n}' for k, n in kinds.items())}); "
                        f"the project shows them as {media}.")
        has_drawing = any(c["kind"] == "drawing" for c in converters.values())
        has_spans = any(c["kind"] == "highlighter" for c in converters.values())
        key = {"image": "image", "audio": "audio", "video": "video",
               "text": "text_url"}.get(media or "", "subject_file")
        if has_drawing and media not in (None, "image"):
            result.warn(f"The workflow draws on images but the subjects are {media}.")
        for converter in converters.values():
            if converter["kind"] == "drawing":
                converter["scheme"]["source_field"] = key

        missing_media = 0
        multi_frame = 0
        no_text = 0
        for sid, subject in subjects.items():
            fields: Dict[str, Any] = {}
            locations = subject["locations"]
            urls = [url for _, url in locations]
            text = self._subject_text(subject) if has_spans else ""
            if urls:
                fields[key] = urls[0]
                if len(urls) > 1:
                    multi_frame += 1
                    fields["locations"] = urls
            elif not text and has_drawing:
                # Nothing to draw on (a subject the classifications name but
                # the subject export lacks): an item would be an empty image.
                missing_media += 1
                result.skipped["subjects with no image to draw on"] += 1
                continue
            elif not text:
                missing_media += 1
                fields[key] = ((self._filename(subject["metadata"]) or f"Zooniverse subject {sid}")
                               if key == "subject_file" else "")
            if has_spans:
                fields["text"] = text
                if not text:
                    no_text += 1
            for name, value in subject["metadata"].items():
                if name == "retired" or (text and name in TEXT_KEYS):
                    continue
                column = name if name not in ("id", key, "locations", "text") else f"metadata_{name}"
                fields[column] = value
            if has_drawing and subject.get("dims"):
                # The size the marks were converted with. Potato stores marks as
                # fractions of the image, and an export that works in pixels
                # (consensus point clustering, COCO) cannot open a remote image
                # to measure it.
                width, height = subject["dims"][0]
                fields.setdefault("image_width", int(width) if float(width).is_integer() else width)
                fields.setdefault("image_height", int(height) if float(height).is_integer() else height)
            item = ProjectItem(instance_id=sid, fields=fields)
            item.responses = responses.get(sid, {})
            result.items.append(item)

        if has_spans:
            result.text_key = "text"
        else:
            result.text_key = key
        if media and not has_drawing and not has_spans and media != "text":
            result.instance_display = {"fields": [{"key": key, "type": media,
                                                   "label": "Subject"}]}
        if missing_media:
            if not any(s.get("from_export") for s in subjects.values()):
                result.warn(f"{missing_media} subject(s) have no media URL: the "
                            "classification export names subjects' files but not "
                            "where they are. Add the subject export "
                            "(*subjects*.csv, or options subjects=<path>) to bring "
                            "the URLs across.")
            else:
                result.warn(f"{missing_media} subject(s) have no media URL in the "
                            "subject export.")
        if multi_frame:
            result.warn(f"{multi_frame} subject(s) have more than one frame; the "
                        f"first is shown and all are kept in the 'locations' column.")
        if no_text:
            result.warn(f"{no_text} subject(s) have no text for the highlighter task "
                        "(Zooniverse keeps a text subject's content at its URL); "
                        "fill in the data file's 'text' column before annotating.")

    @staticmethod
    def _filename(metadata: dict) -> str:
        for name, value in metadata.items():
            if "file" in str(name).lower() or "image" in str(name).lower():
                if isinstance(value, str) and value:
                    return value
        return ""

    @staticmethod
    def _subject_text(subject: dict) -> str:
        for name in TEXT_KEYS:
            value = subject["metadata"].get(name)
            if isinstance(value, str) and value:
                return value
        return ""

    # ------------------------------------------------------------ classifications
    def _classifications(self, rows, workflow: Workflow, same_major: Dict[Any, Workflow],
                         converters, subjects: Dict[str, dict],
                         result) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """subject id -> annotator -> scheme name -> answer."""
        responses: Dict[str, Dict[str, Dict[str, Any]]] = {}
        other_versions: Counter = Counter()
        anonymous = 0
        names_by_id: Dict[str, str] = {}
        label_maps = {minor: self._label_maps(w, converters) for minor, w in same_major.items()}
        current_maps = self._label_maps(workflow, converters)
        kept_skips: Dict[Tuple[str, str], Counter] = {}

        for row in rows:
            wid = str(row.get("workflow_id") or "")
            if wid != workflow.workflow_id:
                result.skipped["classifications of other workflows"] += 1
                continue
            major, minor = _version(row.get("workflow_version"))
            if major != workflow.major:
                other_versions[str(row.get("workflow_version"))] += 1
                continue
            subject_ids = [s for s in re.split(r"[;,\s]+", str(row.get("subject_ids") or ""))
                           if s]
            subject_data = _json(row.get("subject_data"), {}) or {}
            if not subject_ids and isinstance(subject_data, dict):
                subject_ids = list(subject_data)
            if len(subject_ids) != 1:
                result.skipped["classifications of several subjects at once"] += 1
                continue
            sid = subject_ids[0]
            subject = subjects.setdefault(sid, {"metadata": {}, "locations": [],
                                                "from_export": False, "dims": None})
            data = subject_data.get(sid) if isinstance(subject_data, dict) else None
            if isinstance(data, dict):
                for name, value in data.items():
                    subject["metadata"].setdefault(name, value)
                if not subject["locations"] and data.get("locations"):
                    subject["locations"] = _locations(data["locations"])
            metadata = _json(row.get("metadata"), {}) or {}
            dims = self._dimensions(metadata)
            if dims and not subject.get("dims"):
                subject["dims"] = dims

            user, anon = self._user(row, names_by_id, result)
            anonymous += anon
            annotations = _json(row.get("annotations"), []) or []
            maps = label_maps.get(minor, current_maps)
            # Skips are counted per classification and kept only for the ones
            # imported, so a repeat that is replaced does not count its marks.
            sink = SimpleNamespace(skipped=Counter(), warn=result.warn)
            answers = self._answers(annotations, workflow, converters, maps, current_maps,
                                    dims or subject.get("dims") or self._metadata_dims(subject),
                                    subject, sink)
            if not answers:
                result.skipped.update(sink.skipped)
                result.skipped["classifications with no importable answer"] += 1
                continue
            per_subject = responses.setdefault(sid, {})
            if user in per_subject:
                result.skipped["repeat classifications of a subject by one person "
                               "(latest kept)"] += 1
            per_subject[user] = answers
            kept_skips[(sid, user)] = sink.skipped

        for skipped in kept_skips.values():
            result.skipped.update(skipped)
        if other_versions:
            versions = ", ".join(sorted(other_versions, key=lambda v: _version(v)[0] or 0))
            result.skipped["classifications from other workflow versions"] += sum(
                other_versions.values())
            result.warn(f"Imported workflow version {workflow.version}; "
                        f"{sum(other_versions.values())} classification(s) made with "
                        f"other versions ({versions}) were left out. Pass "
                        "workflow_version to import another.")
        if anonymous:
            result.warn(f"{anonymous} classification(s) came from volunteers who were "
                        "not logged in. Each not-logged-in id (Zooniverse derives it "
                        "from the IP address) became one anon_ annotator, so one person "
                        "can appear as several, and people sharing an address as one.")
        return responses

    @staticmethod
    def _label_maps(workflow: Workflow, converters) -> Dict[str, Dict[str, int]]:
        """task key -> answer text (raw and cleaned) -> answer index."""
        maps: Dict[str, Dict[str, int]] = {}
        for key, converter in converters.items():
            task = workflow.tasks.get(key) or {}
            if converter["kind"] in ("single", "multiple", "shortcut"):
                raw = [a.get("label") if isinstance(a, dict) else a
                       for a in task.get("answers") or []]
            elif converter["kind"] in ("dropdown-simple", "dropdown"):
                raw = []
            else:
                continue
            table: Dict[str, int] = {}
            for index, text in enumerate(raw):
                if isinstance(text, str):
                    table.setdefault(text, index)
                    table.setdefault(text.strip(), index)
                    table.setdefault(clean_text(text), index)
            for index, label in enumerate(converter["labels"]):
                table.setdefault(label, index)
            maps[key] = table
        return maps

    @staticmethod
    def _dimensions(metadata: dict) -> Optional[List[Tuple[float, float]]]:
        dims = metadata.get("subject_dimensions") if isinstance(metadata, dict) else None
        if not isinstance(dims, list):
            return None
        out = []
        for frame in dims:
            if isinstance(frame, dict) and frame.get("naturalWidth") and frame.get("naturalHeight"):
                out.append((float(frame["naturalWidth"]), float(frame["naturalHeight"])))
            else:
                out.append(None)
        return out if any(out) else None

    @staticmethod
    def _metadata_dims(subject: dict) -> Optional[List[Tuple[float, float]]]:
        meta = subject.get("metadata") or {}
        for w_key, h_key in (("width", "height"), ("#width", "#height"),
                             ("image_width", "image_height"), ("#image_width", "#image_height"),
                             ("Width", "Height")):
            w, h = _number(meta.get(w_key)), _number(meta.get(h_key))
            if w and h and w > 0 and h > 0:
                return [(float(w), float(h))]
        return None

    @staticmethod
    def _user(row: dict, names_by_id: Dict[str, str], result) -> Tuple[str, int]:
        user_name = (row.get("user_name") or "").strip()
        user_id = (row.get("user_id") or "").strip()
        if not user_name or user_name.startswith("not-logged-in"):
            basis = user_name or row.get("user_ip") or row.get("classification_id") or ""
            name = "anon_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
            result.annotator_ids[name] = user_name or "not logged in"
            return name, 1
        key = user_id or user_name
        if key in names_by_id:
            return names_by_id[key], 0
        name = safe_username(user_name)
        if name in result.annotator_ids:
            name = safe_username(f"{user_name}_{user_id or len(names_by_id)}")
        names_by_id[key] = name
        result.annotator_ids[name] = (f"{user_name} (user id {user_id})" if user_id
                                      else user_name)
        return name, 0

    def _answers(self, annotations, workflow, converters, maps, current_maps, dims,
                 subject, result) -> Dict[str, Any]:
        answers: Dict[str, Any] = {}
        flat: List[dict] = []
        for annotation in annotations if isinstance(annotations, list) else []:
            if not isinstance(annotation, dict):
                continue
            task = workflow.tasks.get(annotation.get("task")) or {}
            if task.get("type") == "combo" and isinstance(annotation.get("value"), list):
                flat.extend(a for a in annotation["value"] if isinstance(a, dict))
            else:
                flat.append(annotation)

        for annotation in flat:
            key = annotation.get("task")
            value = annotation.get("value")
            converter = converters.get(key)
            if converter is None:
                if key in workflow.tasks:
                    kind = (workflow.tasks.get(key) or {}).get("type")
                    if value not in (None, "", []):
                        result.skipped[f"answers to {kind} tasks"] += 1
                elif annotation.get("markIndex") is not None or "." in str(key):
                    result.skipped["drawing detail answers"] += 1
                else:
                    result.skipped["answers to tasks the workflow version lacks"] += 1
                continue
            if value is None or value == "" or value == []:
                continue
            converted = self._convert(key, converter, value, maps.get(key) or {},
                                      current_maps.get(key) or {}, dims, subject, result)
            if converted is not None and converted != []:
                answers[converter["scheme"]["name"]] = converted
        return answers

    def _option(self, value, labels, table, fallback, result) -> Optional[str]:
        """One answer (index, label text or ``{"label"}``) -> option name."""
        if isinstance(value, dict):
            value = value.get("label", value.get("value", value.get("index")))
        if isinstance(value, bool):
            value = None
        index: Optional[int] = None
        if isinstance(value, (int, float)) and float(value).is_integer():
            index = int(value)
        elif isinstance(value, str):
            for candidate in (value, value.strip(), clean_text(value)):
                if candidate in table:
                    index = table[candidate]
                    break
                if candidate in fallback:
                    index = fallback[candidate]
                    break
            if index is None and value.strip().isdigit():
                index = int(value.strip())
        if index is None or not 0 <= index < len(labels):
            result.skipped["answers that match no option"] += 1
            return None
        return labels[index]

    def _convert(self, key, converter, value, table, fallback, dims, subject, result):
        kind = converter["kind"]
        labels = converter["labels"]
        if kind == "single":
            if isinstance(value, list):
                value = value[0] if value else None
            return self._option(value, labels, table, fallback, result)
        if kind in ("multiple", "shortcut"):
            values = value if isinstance(value, list) else [value]
            chosen = []
            for v in values:
                name = self._option(v, labels, table, fallback, result)
                if name is not None and name not in chosen:
                    chosen.append(name)
            return chosen
        if kind in ("dropdown-simple", "dropdown"):
            return self._dropdown_value(converter, value, result)
        if kind == "text":
            return value if isinstance(value, str) else json.dumps(value)
        if kind == "slider":
            number = _number(value)
            if number is None:
                result.skipped["slider answers that are not numbers"] += 1
            return number
        if kind == "drawing":
            return self._marks(converter, value, dims, result)
        if kind == "highlighter":
            return self._spans(converter, value, subject, result)
        return None

    @staticmethod
    def _dropdown_value(converter, value, result) -> Optional[str]:
        labels, values = converter["labels"], converter["option_values"]
        if isinstance(value, list):  # dropdown v1: [{"value", "option"}] per list
            value = value[0] if value else None
        if not isinstance(value, dict):
            return None
        if value.get("option") is False:
            result.skipped["typed dropdown answers (not an option)"] += 1
            return None
        picked = value.get("selection", value.get("value"))
        if picked is None:
            return None
        if picked in values:
            return labels[values.index(picked)]
        if isinstance(picked, int) and not isinstance(picked, bool) and 0 <= picked < len(labels):
            return labels[picked]
        if isinstance(picked, str) and picked in labels:
            return picked
        result.skipped["answers that match no option"] += 1
        return None

    def _marks(self, converter, marks, dims, result) -> List[dict]:
        objects: List[dict] = []
        if not isinstance(marks, list):
            return objects
        tool_map = converter["tool_map"]
        for mark in marks:
            if not isinstance(mark, dict):
                continue
            tool = mark.get("tool", mark.get("toolIndex"))
            tool = int(tool) if isinstance(tool, (int, float)) and not isinstance(tool, bool) else None
            if tool is None or not 0 <= tool < len(tool_map) or tool_map[tool] is None:
                result.skipped["marks from tools that were not imported"] += 1
                continue
            frame = int(_number(mark.get("frame")) or 0)
            if frame != 0:
                result.skipped["marks on frames after the first"] += 1
                continue
            size = dims[0] if dims else None
            if not size:
                result.skipped["marks on subjects of unknown size"] += 1
                result.warn("Some marks are on subjects whose image size is unknown "
                            "(no subject_dimensions in the classification metadata "
                            "and no width/height in the subject metadata); they were "
                            "left out, since Potato stores marks as fractions of the "
                            "image.")
                continue
            if mark.get("details"):
                if any(isinstance(d, dict) and d.get("value") not in (None, "", [])
                       for d in mark["details"]):
                    result.skipped["drawing detail answers"] += 1
            obj = self._mark_object(tool_map[tool], mark, size, result)
            if obj is None:
                result.skipped["marks with unusable geometry"] += 1
                continue
            # The label's colour from the config (the tool's own), not "".
            colors = {l.get("name"): l.get("color") for l in converter["scheme"].get("labels") or []
                      if isinstance(l, dict)}
            if not obj.get("color") and colors.get(obj.get("label")):
                obj["color"] = colors[obj["label"]]
            objects.append(obj)
        return objects

    @staticmethod
    def _mark_object(tool, mark, size, result) -> Optional[dict]:
        potato_tool, label = tool
        width, height = size
        num = lambda k: _number(mark.get(k))  # noqa: E731
        try:
            if potato_tool == "landmark":
                x, y = num("x"), num("y")
                if x is None or y is None:
                    return None
                return to_client_object("landmark", label, img_w=width, img_h=height,
                                        provenance=PROVENANCE, points=[[x, y]])
            if potato_tool == "bbox":
                w, h = num("width"), num("height")
                if w is None or h is None:
                    return None
                if mark.get("x_center") is not None:
                    x, y = num("x_center") - w / 2, num("y_center") - h / 2
                else:
                    x, y = num("x"), num("y")
                if x is None or y is None:
                    return None
                # A box dragged up or left has a negative size in some clients.
                if w < 0:
                    x, w = x + w, -w
                if h < 0:
                    y, h = y + h, -h
                if num("angle"):
                    result.skipped["rotated rectangles (imported unrotated)"] += 1
                if width and height:
                    # A box dragged past the image edge: keep the part on the image.
                    x0, y0 = max(0.0, x), max(0.0, y)
                    x1, y1 = min(float(width), x + w), min(float(height), y + h)
                    if x1 <= x0 or y1 <= y0:
                        result.skipped["boxes entirely outside the image"] += 1
                        return None
                    if (x0, y0, x1, y1) != (x, y, x + w, y + h):
                        result.skipped["boxes clipped to the image edge"] += 1
                    x, y, w, h = x0, y0, x1 - x0, y1 - y0
                return to_client_object("bbox", label, img_w=width, img_h=height,
                                        provenance=PROVENANCE, bbox=[x, y, w, h])
            if potato_tool == "ellipse":
                cx = num("x_center") if mark.get("x_center") is not None else num("x")
                cy = num("y_center") if mark.get("y_center") is not None else num("y")
                if mark.get("r") is not None:
                    rx = ry = num("r")
                else:
                    rx, ry = num("rx"), num("ry")
                if None in (cx, cy, rx, ry):
                    return None
                # Zooniverse measures the angle counter-clockwise (the SVG is
                # drawn with rotate(-angle)); fabric, and so Potato, clockwise.
                angle = -(num("angle") or 0)
                return to_client_object("ellipse", label, img_w=width, img_h=height,
                                        provenance=PROVENANCE,
                                        ellipse={"cx": cx, "cy": cy, "rx": abs(rx),
                                                 "ry": abs(ry), "angle": angle})
            if potato_tool == "polyline":
                if mark.get("x1") is not None:
                    points = [[num("x1"), num("y1")], [num("x2"), num("y2")]]
                else:
                    points = _points(mark)
                if not points or any(None in p for p in points):
                    return None
                if len(points) < 2:
                    result.skipped["lines with fewer than 2 points"] += 1
                    return None
                return to_client_object("polyline", label, img_w=width, img_h=height,
                                        provenance=PROVENANCE, points=points)
            if potato_tool in ("polygon", "freeform"):
                points = _points(mark)
                if not points or any(None in p for p in points):
                    return None
                if potato_tool == "polygon" and len(points) > 3 and points[0] == points[-1]:
                    points = points[:-1]
                if len(points) < (3 if potato_tool == "polygon" else 2):
                    result.skipped[f"{potato_tool} shapes with too few points"] += 1
                    return None
                return to_client_object(potato_tool, label, img_w=width, img_h=height,
                                        provenance=PROVENANCE, points=points)
        except (TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _spans(converter, value, subject, result) -> List[dict]:
        text = ZooniverseImporter._subject_text(subject)
        spans = []
        for entry in value if isinstance(value, list) else []:
            if not isinstance(entry, dict):
                continue
            info = entry.get("labelInformation") or {}
            label = clean_text(info.get("label")) if isinstance(info, dict) else ""
            start, end = _number(entry.get("start")), _number(entry.get("end"))
            if label not in converter["labels"] or start is None or end is None:
                result.skipped["highlights that match no label"] += 1
                continue
            if text:
                start, end = utf16_to_code_points(text, int(start)), utf16_to_code_points(text, int(end))
            spans.append({"start": int(start), "end": int(end), "label": label})
        return spans


def _points(mark: dict) -> List[List[Optional[float]]]:
    if isinstance(mark.get("points"), list):
        return [[_number(p.get("x")), _number(p.get("y"))] for p in mark["points"]
                if isinstance(p, dict)]
    xs, ys = mark.get("pathX"), mark.get("pathY")
    if isinstance(xs, list) and isinstance(ys, list):
        return [[_number(x), _number(y)] for x, y in zip(xs, ys)]
    return []


def _simplify(paths: List[dict], tasks: Dict[str, dict]) -> List[dict]:
    """Smallest equivalent set of paths (an OR of ANDs of answer sets).

    A constraint allowing every answer of its task is dropped (reaching the
    task was already required by the rest of the path); a path implied by a
    looser one is dropped; two paths differing only in one task's answers
    merge into one.
    """
    def n_answers(key):
        return len((tasks.get(key) or {}).get("answers") or [])

    current = []
    for path in paths:
        clean = {k: frozenset(v) for k, v in path.items()
                 if len(v) < n_answers(k)}
        if any(not v for v in clean.values()):
            continue  # contradictory: no answer satisfies it
        current.append(clean)
    changed = True
    while changed:
        changed = False
        if any(not p for p in current):
            return [{}]
        kept: List[dict] = []
        for i, path in enumerate(current):
            absorbed = False
            for j, other in enumerate(current):
                if i == j:
                    continue
                looser = (set(other) <= set(path)
                          and all(path[k] <= other[k] for k in other))
                if looser and (other != path or j < i):
                    absorbed = True
                    break
            if not absorbed:
                kept.append(path)
        if len(kept) != len(current):
            changed = True
        current = kept
        merged = False
        for i in range(len(current)):
            for j in range(i + 1, len(current)):
                a, b = current[i], current[j]
                if set(a) != set(b):
                    continue
                diff = [k for k in a if a[k] != b[k]]
                if len(diff) != 1:
                    continue
                k = diff[0]
                union = a[k] | b[k]
                new = dict(a)
                if len(union) >= n_answers(k):
                    del new[k]
                else:
                    new[k] = union
                current = [p for n, p in enumerate(current) if n not in (i, j)] + [new]
                merged = True
                break
            if merged:
                break
        if merged:
            changed = True
    return current
