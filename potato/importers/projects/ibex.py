"""
Ibex and PCIbex (PennController) experiments as Potato projects.

Ibex studies are JavaScript, so this reads the experiment's data side and
the common trial types, and reports everything else:

* **PCIbex**: each ``Template("table.csv", row => newTrial(...))`` becomes a
  set of items, one per CSV row (from ``chunk_includes/``). Inside the trial,
  ``newController("DashedSentence", {s: row.X})`` becomes self-paced
  reading, ``newController("Maze", {s: row.X, a: row.Y})`` the maze task,
  ``newScale(N)`` an N-point rating (its ``.before`` / ``.after`` texts as
  the end labels), and ``newKey("FJ")`` with a ``newText(row.X)`` a timed
  two-key choice. A ``Group`` or ``List`` column is the Latin-square list.
* **Classic Ibex**: the ``var items = [...]`` array, for ``DashedSentence``
  (with an optional following ``Question``) and ``AcceptabilityJudgment``.
  Items labelled ``["condition", N]`` share group N and are rotated across
  lists the standard Latin-square way.

A Latin square becomes a between-subjects factor ``list`` with one data
file per list and ``batch_assignment.group_by_condition: list``, so each
participant gets one list. Items outside the square (fillers) go in every
list. Practice items, ``Message`` / ``Form`` / ``Html`` screens, timers,
``Sequence`` ordering, ``Header`` / ``Footer`` commands and custom
JavaScript are reported, not translated.
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

GROUP_COLUMNS = ("group", "list", "latinsquare", "lst")
PRACTICE = re.compile(r"^(prac|practice|exercise|train|intro|instructions?)", re.I)


@dataclass
class IbexImport:
    source_format: str
    kind: str = ""                        # spr | maze | rating | keys
    items: List[Dict[str, Any]] = field(default_factory=list)   # {id, group?, condition?, ...}
    scale: Dict[str, Any] = field(default_factory=dict)
    keys: List[str] = field(default_factory=list)
    has_question: bool = False
    question_answers: List[str] = field(default_factory=list)
    lists: int = 1
    report: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summarize(self):
        return {"num_items": len(self.items), "kind": self.kind, "lists": self.lists}


def _natural_key(name: str) -> List[Any]:
    """Sort L2 before L10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _template_blocks(js: str) -> List[Tuple[str, str, str]]:
    """(csv name, row variable, body) for each Template(...) call."""
    out = []
    pattern = re.compile(
        r"Template\(\s*(?:GetTable\(\s*)?[\"'`]([^\"'`]+)[\"'`]\s*\)?\s*,\s*\(?\s*(\w+)\s*\)?\s*=>")
    matches = list(pattern.finditer(js))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(js)
        out.append((m.group(1), m.group(2), js[m.end():end]))
    return out


class IbexImporter:
    format_name = "ibex"
    description = "Ibex / PCIbex experiments (CSV templates and the items array) as Potato projects"
    file_extensions = [".js"]

    def _main_js(self, path: Path) -> Optional[Path]:
        if path.is_file() and path.suffix == ".js":
            return path
        d = path / "data_includes" if (path / "data_includes").is_dir() else path
        if not d.is_dir():
            return None
        files = sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith("."))
        for p in files:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "newTrial(" in text or "var items" in text or "PennController" in text:
                return p
        return None

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        js = self._main_js(path)
        if js is None:
            return False
        text = js.read_text(encoding="utf-8", errors="replace")
        return ("Template(" in text and "newTrial(" in text) or bool(re.search(r"var\s+items\s*=\s*\[", text))

    def parse_path(self, path: Path, options: Optional[dict] = None) -> IbexImport:
        path = Path(path)
        js_path = self._main_js(path)
        if js_path is None:
            raise ValueError(f"no Ibex or PCIbex experiment script at {path}")
        js = js_path.read_text(encoding="utf-8", errors="replace")
        root = js_path.parent.parent if js_path.parent.name == "data_includes" else js_path.parent
        res = self._pcibex(js, root) if "Template(" in js else self._classic(js)
        if not res.items:
            where = "its table has no rows" if res.source_format == "PCIbex" else \
                "no DashedSentence or AcceptabilityJudgment items outside practice"
            raise ValueError(f"nothing to import from {js_path.name}: {where}")
        return res

    # ------------------------------------------------------------------ PCIbex

    def _pcibex(self, js: str, root: Path) -> IbexImport:
        res = IbexImport(source_format="PCIbex")
        chunks = root / "chunk_includes"
        chosen = None
        for name, var, body in _template_blocks(js):
            if not (chunks / name).is_file() and not (chunks / f"{name}.csv").is_file():
                res.report.append(f"template {name}: its table is not in chunk_includes/ "
                                  "(an inline or remote table), so it was not imported")
                continue
            trial = re.search(r"newTrial\(\s*([\"'`][^\"'`]*[\"'`]|[^,]+?)\s*,", body)
            label = trial.group(1).strip("\"'`") if trial else ""
            if PRACTICE.match(label) or PRACTICE.match(name):
                res.report.append(f"practice template {name} ({label}) was not imported")
                continue
            if chosen is not None:
                res.report.append(f"template {name}: only one template is imported ({chosen[0]} was)")
                continue
            chosen = (name, var, body)
        if chosen is None:
            raise ValueError("no non-practice Template(...) found")
        name, var, body = chosen
        table = chunks / name if (chunks / name).is_file() else chunks / f"{name}.csv"
        with open(table, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        col = lambda pat: re.findall(pat.replace("ROW", re.escape(var)), body)  # noqa: E731
        dashed = col(r"newController\(\s*[\"']DashedSentence[\"']\s*,\s*\{\s*s\s*:\s*ROW\.(\w+)")
        maze = col(r"newController\(\s*[\"']Maze[\"']\s*,\s*\{\s*s\s*:\s*ROW\.(\w+)\s*,\s*a\s*:\s*ROW\.(\w+)")
        texts = col(r"newText\(\s*(?:[\"'`][^\"'`]*[\"'`]\s*,\s*)?ROW\.(\w+)")
        scale = re.search(r"newScale\(\s*(?:[\"'`][^\"'`]*[\"'`]\s*,\s*)?(\d+)\s*\)", body)
        key_args = re.search(r"newKey\(([^)]*)\)", body)
        keys = None
        if key_args:
            strings = re.findall(r"[\"'`]([^\"'`]*)[\"'`]", key_args.group(1))
            singles = [k for k in strings if len(k) == 1]
            # newKey("name", "F", "J") or newKey("FJ") / newKey("name", "FJ")
            keys = singles if len(singles) >= 2 else next(
                (list(k) for k in strings[::-1] if k.isalnum() and 2 <= len(k) <= 4), None)
        audio = col(r"newAudio\(\s*(?:[\"'`][^\"'`]*[\"'`]\s*,\s*)?ROW\.(\w+)")
        if maze:
            res.kind, text_col, extra = "maze", maze[0][0], {"distractors": maze[0][1]}
        elif dashed:
            res.kind, text_col, extra = "spr", dashed[0], {}
            # A comprehension question after the sentence: newText(row.Question)
            # with a newKey to answer it. The DashedSentence branch read only
            # the sentence, so the question was dropped without a word.
            questions = [c for c in texts if c != dashed[0]]
            if questions and keys:
                extra["question"] = questions[-1]
                res.has_question = True
                res.keys = [k.lower() for k in keys][:2]
                res.report.append(
                    f"the question in column {questions[-1]} is answered with "
                    f"{' / '.join(k.upper() for k in res.keys)}, imported as "
                    f"{' / '.join(res.question_answers or ['Yes', 'No'])}; rename the "
                    "answers if the keys mean something else")
            elif questions:
                res.report.append(f"column {questions[-1]} is shown with newText but has no "
                                  "newKey to answer it, so it was not imported as a question")
        elif scale:
            res.kind, text_col, extra = "rating", (texts[0] if texts else None), {}
            n = int(scale.group(1))
            labels = re.findall(r"\.(?:before|after)\(\s*newText\(\s*(?:[\"'`][^\"'`]*[\"'`]\s*,\s*)?[\"'`](.*?)[\"'`]\s*\)", body)
            res.scale = {"size": n, "min_label": _strip_tags(labels[0]) if labels else "1",
                         "max_label": _strip_tags(labels[1]) if len(labels) > 1 else str(n)}
        elif keys and (texts or audio):
            res.kind, text_col, extra = "keys", (texts[-1] if texts else audio[0]), {}
            res.keys = [k.lower() for k in keys][:4]
            if audio and not texts:
                res.report.append(f"audio stimuli (column {audio[0]}): copy the files into the "
                                  "project's media/ and show them with instance_display; the "
                                  "item text is the file name. For audio onsets that matter, "
                                  "run the trials in a type: jspsych phase")
        else:
            raise ValueError("the template's trial is not DashedSentence, Maze, a newScale "
                             "rating or a newKey choice; nothing to import")
        if not text_col:
            raise ValueError("could not tell which column holds the stimulus text")
        with open(table, newline="", encoding="utf-8-sig") as f:
            headers = next(csv.reader(f), [])
        if text_col not in headers:
            raise ValueError(f"the template reads {var}.{text_col}, but {table.name} has no "
                             f"{text_col} column (it has: {', '.join(headers) or 'none'})")
        named = sorted(set(re.findall(r"\b" + re.escape(var) + r"\.(\w+)", body)) - set(headers))
        if named:
            res.warnings.append(f"the template reads {', '.join(var + '.' + c for c in named)}, "
                                f"which {table.name} does not have; those values are empty")
        empty = sum(1 for row in rows if not str(row.get(text_col) or "").strip())
        if empty:
            res.warnings.append(f"{empty} row(s) of {table.name} have an empty {text_col}")
        group_col = next((h for h in headers if h.lower() in GROUP_COLUMNS), None)
        for i, row in enumerate(rows):
            item = {"id": f"{Path(name).stem}_{i + 1}", "text": row.get(text_col, "")}
            for k, v in row.items():
                if k and k not in item:
                    item[k] = v
            if extra.get("distractors"):
                item["distractors"] = row.get(extra["distractors"], "")
            if extra.get("question"):
                item["question"] = row.get(extra["question"], "")
            if group_col and str(row.get(group_col, "")).strip():
                item["_group"] = str(row[group_col]).strip()
            res.items.append(item)
        if group_col:
            res.lists = len({it["_group"] for it in res.items if "_group" in it})
        for what, pat in (("Header/Footer commands", r"\b(Header|Footer)\("),
                          ("Sequence ordering", r"\bSequence\("), ("timers", r"newTimer\("),
                          ("custom JavaScript (newFunction)", r"newFunction\("),
                          ("Html screens (newHtml)", r"newHtml\("),
                          ("Message and Form controllers",
                           r"newController\(\s*(?:[\"'`][^\"'`]*[\"'`]\s*,\s*)?[\"'`](Message|Form)[\"'`]"),
                          ("audio, image or video elements", r"new(Audio|Image|Video)\(")):
            if re.search(pat, js):
                res.report.append(what)
        return res

    # ------------------------------------------------------------------ classic

    def _classic(self, js: str) -> IbexImport:
        res = IbexImport(source_format="Ibex")
        entry = re.compile(
            r"\[\s*(\"[^\"]*\"|'[^']*'|\[\s*[\"'][^\"']*[\"']\s*,\s*\d+\s*\])\s*,\s*[\"']?(\w+)[\"']?\s*,\s*\{")
        # A group's items in source order: Ibex rotates a group by position,
        # so two items with the same label are two conditions, not one.
        groups: Dict[int, List[Tuple[str, dict]]] = {}
        kinds = set()
        skipped: Dict[str, int] = {}          # controller -> items not imported
        for m in entry.finditer(js):
            label_raw, controller = m.group(1), m.group(2)
            group = None
            lm = re.match(r"\[\s*[\"']([^\"']*)[\"']\s*,\s*(\d+)\s*\]", label_raw)
            label = lm.group(1) if lm else label_raw.strip("\"'")
            if lm:
                group = int(lm.group(2))
            body = js[m.end() - 1: m.end() + 4000]
            if controller not in ("DashedSentence", "AcceptabilityJudgment"):
                if not controller.startswith("__"):     # __SetCounter__ and the like
                    skipped[controller] = skipped.get(controller, 0) + 1
                continue
            if PRACTICE.match(label):
                res.report.append(f"practice item ({label}) was not imported")
                continue
            sentence = self._js_value(body, "s")
            if sentence is None:
                res.report.append(f"an item labelled {label} had no readable `s`")
                continue
            item: Dict[str, Any] = {"condition": label, "_controller": controller,
                                    "text": " | ".join(sentence) if isinstance(sentence, list) else sentence}
            kinds.add(controller)
            if controller == "DashedSentence":
                q = re.search(r"[\"']Question[\"']\s*,\s*\{", body[:800])
                if q:
                    qbody = body[q.end() - 1:]
                    item["question"] = self._js_value(qbody, "q") or ""
                    answers = self._js_value(qbody, "as")
                    if isinstance(answers, list) and answers:
                        res.question_answers = [str(a) for a in answers][:2]
                    res.has_question = True
            else:
                q = self._js_value(body, "q")
                if q:
                    item["text"] = f"{item['text']} | {q}"
            if group is None:
                res.items.append(item)
            else:
                members = groups.setdefault(group, [])
                if any(lab == label for lab, _ in members):
                    res.warnings.append(f"group {group} has two items labelled {label}; both were "
                                        f"kept (Ibex rotates a group by position)")
                members.append((label, item))
        for controller, n in sorted(skipped.items()):
            res.report.append(f"{n} {controller} screen(s) were not imported")
        if len(kinds) > 1:
            res.warnings.append("the experiment mixes DashedSentence and AcceptabilityJudgment; "
                                "only DashedSentence items were kept")
            res.items = [i for i in res.items if i.get("_controller") != "AcceptabilityJudgment"]
        res.kind = "spr" if "DashedSentence" in kinds else "rating"
        if res.kind == "rating":
            res.scale = {"size": 7, "min_label": "1", "max_label": "7"}
            res.report.append("AcceptabilityJudgment scale and comments: imported as a 7-point "
                              "scale (Ibex's default); check `as`, `leftComment`, `rightComment`")
        # Latin square: list k gets, from group g, the condition at (k + g) mod n.
        n_cond = max((len(g) for g in groups.values()), default=0)
        res.lists = max(1, n_cond)
        for g, conds in sorted(groups.items()):
            for k in range(res.lists):
                if not conds:
                    continue
                pos = (k + g) % len(conds)
                label, source = conds[pos]
                item = dict(source)
                repeats = sum(1 for lab, _ in conds if lab == label)
                item["id"] = f"g{g}_{label}" + (f"_{pos + 1}" if repeats > 1 else "")
                item["_group"] = f"L{k + 1}"
                item["item_group"] = g
                res.items.append(item)
        for i, item in enumerate(res.items):
            item.setdefault("id", f"filler_{i + 1}")
        if re.search(r"shuffleSequence", js):
            res.report.append("shuffleSequence ordering is not translated (items are shown in "
                              "each list's order; set assignment_strategy: random to shuffle)")
        return res

    @staticmethod
    def _js_value(body: str, key: str):
        """The value of `key:` in a JS object literal: a string or a list of strings."""
        m = re.search(r"[{,]\s*[\"']?" + re.escape(key) + r"[\"']?\s*:\s*", body)
        if not m:
            return None
        rest = body[m.end():]
        sm = re.match(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'", rest)
        if sm:
            return (sm.group(1) if sm.group(1) is not None else sm.group(2)).replace('\\"', '"')
        lm = re.match(r"\[(.*?)\]", rest, re.S)
        if lm:
            return [a or b for a, b in re.findall(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'", lm.group(1))]
        return None

    # ------------------------------------------------------------------ writer

    def write_project(self, res: IbexImport, output_dir: str, source: str, **_kw) -> List[str]:
        from potato.server_utils.config_schema import SCHEMA_URL
        out = Path(output_dir)
        (out / "data").mkdir(parents=True, exist_ok=True)
        written: List[str] = []
        lists = [f"L{k + 1}" for k in range(res.lists)] if res.lists > 1 else []
        groups = sorted({i["_group"] for i in res.items if "_group" in i}, key=_natural_key)
        if res.lists > 1 and groups:
            # The list names in the data: L1..Ln for classic Ibex, the Group
            # column's values for PCIbex (A/B, L1/L2, List1/List2, ...). A
            # row whose list is not one of these would be in no data file.
            lists = groups
        files = {}
        if lists:
            for lst in lists:
                rows = []
                for it in res.items:
                    if it.get("_group") in (None, lst):
                        row = {k: v for k, v in it.items() if not k.startswith("_")}
                        if it.get("_group") is None:
                            row["id"] = f"{row['id']}_{lst}"   # IDs are unique across lists
                        row["list"] = lst
                        rows.append(row)
                files[lst] = rows
        else:
            files["all"] = [{k: v for k, v in it.items() if not k.startswith("_")} for it in res.items]
        for name, rows in files.items():
            p = out / "data" / f"{name}.jsonl"
            with p.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            written.append(str(p))

        config: Dict[str, Any] = {
            "annotation_task_name": f"{Path(source).name} (imported from {res.source_format})",
            "task_dir": ".", "output_annotation_dir": "annotation_output/",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
        }
        if lists:
            config["conditions"] = {"factors": {"list": list(files)}, "assignment": "balanced"}
            config["assignment_strategy"] = "batch"
            config["batch_assignment"] = {"auto_assign_annotators": True, "group_by_condition": "list",
                                          "groups": [{"name": n, "data_file": f"data/{n}.jsonl"}
                                                     for n in files]}
            config["data_files"] = []
        else:
            config["data_files"] = ["data/all.jsonl"]
            config["assignment_strategy"] = "fixed_order"
        if res.kind in ("spr", "maze"):
            presentation: Dict[str, Any] = {"mode": "maze" if res.kind == "maze" else "moving_window",
                                            "field": "text"}
            if any(" | " in str(i.get("text", "")) for i in res.items):
                presentation["region_separator"] = "|"
            if res.kind == "maze":
                presentation["distractor_field"] = "distractors"
            block: Dict[str, Any] = {"enabled": True, "fixation_ms": 0, "iti_ms": 500,
                                     "presentation": presentation}
            if res.has_question:
                answers = res.question_answers or ["Yes", "No"]
                presentation["question_field"] = "question"
                first, second = (res.keys + ["f", "j"])[:2] if len(res.keys or []) >= 2 else ("f", "j")
                block["response"] = {"schema": "comprehension",
                                     "keys": {first: answers[0], second: answers[1] if len(answers) > 1 else "No"}}
                config["annotation_schemes"] = [{"annotation_type": "radio", "name": "comprehension",
                                                 "description": "Answer the question",
                                                 "labels": answers[:2] if len(answers) > 1 else ["Yes", "No"]}]
            else:
                config["annotation_schemes"] = [{"annotation_type": "pure_display", "name": "reading",
                                                 "description": "Read each sentence."}]
            config["trial_timing"] = block
        elif res.kind == "rating":
            config["annotation_schemes"] = [{"annotation_type": "likert", "name": "rating",
                                             "description": "How natural does this sound?",
                                             **res.scale}]
        else:  # keys
            labels = [k.upper() for k in res.keys]
            config["annotation_schemes"] = [{"annotation_type": "radio", "name": "response",
                                             "description": "Response", "labels": labels}]
            config["trial_timing"] = {"enabled": True, "fixation_ms": 500, "iti_ms": 500,
                                      "response": {"schema": "response",
                                                   "keys": {k: k.upper() for k in res.keys}}}
            res.warnings.append(f"the keys {', '.join(labels)} are imported as the answers; "
                                "rename the labels to what they mean (word / nonword, ...)")
        p = out / "config.yaml"
        with p.open("w", encoding="utf-8") as f:
            f.write(f"# yaml-language-server: $schema={SCHEMA_URL}\n")
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
        written.append(str(p))
        rep = out / "IMPORT_REPORT.md"
        text = "# Import report\n\n" + (
            "\n".join(f"- {r}" for r in res.report) or "Everything was carried over.") + "\n"
        if res.warnings:
            text += "\n## Warnings\n\n" + "\n".join(f"- {w}" for w in res.warnings) + "\n"
        rep.write_text(text, encoding="utf-8")
        written.append(str(rep))
        return written
