"""
Network Canvas protocols into Potato survey pages with ``ego_network`` schemes.

Reads a ``.netcanvas`` file (a zip holding ``protocol.json`` and an
``assets/`` folder) or a bare ``protocol.json``. Written from the protocol
format (schema versions 7 to 9: ``stages``, ``codebook``, ``assetManifest``);
no Network Canvas code is used.

Mapped:

* ``EgoForm`` -> a survey page of ordinary questions, typed from the
  codebook's ego variables: text (``TextArea`` as a text area), number,
  categorical (multiselect; radio when the component is ``RadioGroup``),
  ordinal (horizontal radio), boolean (Yes/No radio), ``VisualAnalogScale``
  (vas). ``validation.required`` -> ``label_requirement``; number
  ``minValue``/``maxValue`` -> ``min``/``max``. The introduction panel becomes
  a ``pure_display`` at the top of the page.
* ``Information`` -> a ``pure_display`` page (text items; Markdown is reduced
  to plain text).
* Network stages (``NameGenerator``, ``NameGeneratorQuickAdd``,
  ``NameGeneratorRoster``, ``AlterForm``, ``OrdinalBin``, ``CategoricalBin``,
  ``DyadCensus``, ``OneToManyDyadCensus``, ``TieStrengthCensus``,
  ``Sociogram``) -> stages of one ``ego_network`` scheme per node type, on a
  page placed where the first such stage was. Each prompt of a multi-prompt
  stage becomes its own stage; ``additionalAttributes`` become the name
  generator's ``sets``. A roster comes from the protocol's CSV or JSON asset
  when the file is in the ``.netcanvas`` (or in ``assets/`` beside
  ``protocol.json``). Bins become radio questions in a name interpreter (the
  drag-to-bin interaction is lost; the data are the same). A tie-strength
  census becomes a dyad census with ``strength_labels`` from the edge
  variable's options.
* ``skipLogic`` on ego variables -> page ``show_when`` (``SHOW``) or its
  negation (``SKIP``); ``SKIP`` with a ``destination`` negates the rule on
  every page up to the destination, and a destination that is a
  ``FinishSession`` becomes ``exit_when`` on the page before.

Reported, not mapped: skip logic on node or edge rules, skip logic on a
network stage (the stages of one ego_network scheme are not skipped
individually), stage ``filter``\\ s, ``AlterEdgeForm``, ``Narrative``,
``Geospatial``, ``FamilyPedigree``, ``NetworkComposer``, ``Anonymisation``,
``LanguageChooser``, ``FinishSession`` (Potato has its own end page),
datetime variables, image/audio/video items, sociogram background images and
highlighting, external-data panels, and validation rules other than the ones
above.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    NameAllocator, SurveyImportResult, SurveyPage, Untranslatable, and_rules, combine)

NETWORK_STAGES = {
    "NameGenerator", "NameGeneratorQuickAdd", "NameGeneratorRoster", "NameGeneratorAutoComplete",
    "NameGeneratorList", "AlterForm", "OrdinalBin", "CategoricalBin", "DyadCensus",
    "OneToManyDyadCensus", "TieStrengthCensus", "Sociogram",
}
GENERATORS = {"NameGenerator", "NameGeneratorQuickAdd", "NameGeneratorRoster",
              "NameGeneratorAutoComplete", "NameGeneratorList"}
UNSUPPORTED_STAGES = {
    "AlterEdgeForm": "per-tie questions (edge attributes) have no ego_network equivalent",
    "Narrative": "the narrative/presentation interface",
    "Geospatial": "map-based questions",
    "FamilyPedigree": "family pedigree interface",
    "NarrativePedigree": "family pedigree narrative",
    "NetworkComposer": "network composer interface",
    "Anonymisation": "protocol-level encryption of identifying variables",
    "LanguageChooser": "language chooser (pass --survey-language instead)",
    "FinishSession": "end-of-interview screen (Potato shows its own end page)",
}
MAX_PROTOCOL_BYTES = 50 * 1024 * 1024
MAX_ASSET_BYTES = 20 * 1024 * 1024

_ID_RE = re.compile(r"[^A-Za-z0-9_]+")


def _ident(raw: Any, fallback: str = "v") -> str:
    """A plain identifier (letters, digits, _), starting with a letter."""
    s = _ID_RE.sub("_", str(raw or "")).strip("_") or fallback
    if not s[0].isalpha():
        s = f"{fallback}_{s}"
    return s[:60]


_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_EMPH = re.compile(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1")


def md_to_text(text: Any) -> str:
    """Plain text from the protocol's Markdown (headings, emphasis, links)."""
    s = str(text or "")
    s = _MD_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", s)
    for _ in range(2):
        s = _MD_EMPH.sub(r"\2", s)
    lines = []
    for line in s.splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s*(.*)$", line)
        if heading:
            # A heading run into the next sentence reads as one; end it.
            line = heading.group(1).rstrip()
            if line and line[-1] not in ".!?:":
                line += "."
        lines.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _one_line(text: Any) -> str:
    return re.sub(r"\s+", " ", md_to_text(text)).strip()


def _paragraphs(text: Any) -> List[str]:
    return [re.sub(r"\s+", " ", p).strip() for p in md_to_text(text).split("\n\n") if p.strip()]


def _value_name(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class NetworkCanvasImporter:
    format_name = "network_canvas"
    description = "Network Canvas protocol (.netcanvas or protocol.json): ego forms and network stages"
    file_extensions = [".netcanvas", ".json"]

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @staticmethod
    def _looks_like(data: Any) -> bool:
        return (isinstance(data, dict) and isinstance(data.get("stages"), list)
                and isinstance(data.get("codebook"), dict))

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file():
            return False
        suffix = path.suffix.lower()
        if suffix == ".netcanvas" or (suffix == ".zip" and zipfile.is_zipfile(path)):
            try:
                with zipfile.ZipFile(path) as zf:
                    return any(n.rsplit("/", 1)[-1] == "protocol.json" for n in zf.namelist())
            except (OSError, zipfile.BadZipFile):
                return False
        if suffix != ".json" or path.stat().st_size > MAX_PROTOCOL_BYTES:
            return False
        try:
            with path.open(encoding="utf-8") as f:
                return self._looks_like(json.load(f))
        except (OSError, ValueError):
            return False

    def parse_path(self, path: Path, options: Optional[dict] = None) -> SurveyImportResult:
        path = Path(path)
        assets: Dict[str, bytes] = {}
        if path.suffix.lower() in (".netcanvas", ".zip") and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == "protocol.json"]
                if not names:
                    raise ValueError(f"{path.name} has no protocol.json")
                main = min(names, key=len)
                info = zf.getinfo(main)
                if info.file_size > MAX_PROTOCOL_BYTES:
                    raise ValueError("protocol.json is larger than 50 MB")
                data = json.loads(zf.read(main).decode("utf-8"))
                prefix = main[: -len("protocol.json")]
                for info in zf.infolist():
                    if info.is_dir() or not info.filename.startswith(prefix + "assets/"):
                        continue
                    if info.file_size <= MAX_ASSET_BYTES:
                        assets[info.filename[len(prefix + "assets/"):]] = _LazyAsset(path, info.filename)
        else:
            if path.stat().st_size > MAX_PROTOCOL_BYTES:
                raise ValueError("protocol.json is larger than 50 MB")
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            folder = path.parent / "assets"
            if folder.is_dir():
                for f in folder.iterdir():
                    if f.is_file() and f.stat().st_size <= MAX_ASSET_BYTES:
                        assets[f.name] = _LazyAsset(f, None)
        return self.parse(data, options or {}, assets=assets, source_name=path.stem)

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def parse(self, data: Dict[str, Any], options: dict, assets: Optional[Dict[str, Any]] = None,
              source_name: str = "protocol") -> SurveyImportResult:
        if not self._looks_like(data):
            raise ValueError("not a Network Canvas protocol: expected `stages` and `codebook`")
        self.lang = options.get("language")
        self.languages: set = set()
        self.assets = assets or {}
        self.data = data
        self.codebook = data.get("codebook") or {}
        self.manifest = data.get("assetManifest") or {}
        title = self._text(data.get("name")) or source_name
        result = SurveyImportResult(source_format=f"Network Canvas (schema {data.get('schemaVersion', '?')})",
                                    title=title)
        self.result = result
        self.names = NameAllocator()
        self.page_names = NameAllocator(reserved={"annotation", "order", "counterbalance"})
        self.ego_vars: Dict[str, Dict[str, Any]] = {}   # NC variable id -> {"schema", "kind", "values"}
        self.groups: Dict[str, Dict[str, Any]] = {}      # node type -> {"scheme", "page", "qnames", "stage_ids"}
        self.stage_pages: Dict[int, SurveyPage] = {}     # stage index -> page it produced
        stages = data.get("stages") or []
        scripts = 0
        pending_instructions: List[str] = []

        for idx, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            stype = stage.get("type")
            where = f"stage {idx + 1} '{self._text(stage.get('label')) or stage.get('id')}'"
            if stage.get("interviewScript"):
                scripts += 1
            if stype in NETWORK_STAGES:
                page = self._network_stage(stage, where, pending_instructions)
                pending_instructions = []
                if page is not None:
                    self.stage_pages[idx] = page
                    if stage.get("skipLogic"):
                        result.skip(where, "skip logic on a network stage",
                                    "stages inside one ego_network scheme are not skipped individually")
                continue
            if stype == "Information":
                nxt = stages[idx + 1] if idx + 1 < len(stages) and isinstance(stages[idx + 1], dict) else {}
                if (nxt.get("type") in NETWORK_STAGES and self._node_type(nxt) in self.groups
                        and not stage.get("skipLogic")):
                    text = self._info_text(stage, where)
                    if text:
                        pending_instructions.append(text)
                        result.warnings.append(f"{where}: shown as instructions inside the network "
                                               "page, before the next network stage")
                    continue
                self.stage_pages[idx] = self._information_page(stage, where)
                continue
            if stype == "EgoForm":
                self.stage_pages[idx] = self._ego_form(stage, where)
                continue
            if stype in UNSUPPORTED_STAGES:
                if stype != "FinishSession":
                    result.skip(where, f"stage type {stype}", UNSUPPORTED_STAGES[stype])
                continue
            result.skip(where, f"stage type {stype!r}")

        self._finish_groups()
        self._skip_logic(stages)
        if scripts:
            result.warnings.append(f"{scripts} stage(s) carry interviewer notes (interviewScript); "
                                   "they are not shown to participants")
        if len(self.languages) > 1:
            result.warnings.append(
                f"The protocol has text in {', '.join(sorted(self.languages))}; imported "
                f"{self._chosen_language()} (choose another with --survey-language)")
        if data.get("experiments"):
            result.skip("protocol", "experiments", json.dumps(data["experiments"])[:200])
        result.pages = [p for p in result.pages if p.questions]
        return result

    # -- localized text -------------------------------------------------

    def _chosen_language(self) -> str:
        for key in ([self.lang] if self.lang else []) + ["en-US", "en", "en-GB"]:
            if key in self.languages:
                return key
        return sorted(self.languages)[0] if self.languages else "the default text"

    def _text(self, value: Any) -> str:
        if isinstance(value, dict):
            self.languages.update(value.keys())
            for key in ([self.lang] if self.lang else []) + ["en-US", "en", "en-GB"]:
                if key and key in value and value[key]:
                    return str(value[key])
            for v in value.values():
                if v:
                    return str(v)
            return ""
        return "" if value is None else str(value)

    # -- codebook ---------------------------------------------------------

    def _node_type(self, stage: dict) -> Optional[str]:
        subject = stage.get("subject") or {}
        return subject.get("type") if subject.get("entity", "node") == "node" else None

    def _node_var(self, node_type: str, var_id: str) -> Optional[dict]:
        return (((self.codebook.get("node") or {}).get(node_type) or {}).get("variables") or {}).get(var_id)

    def _edge(self, edge_type: str) -> dict:
        return (self.codebook.get("edge") or {}).get(edge_type) or {}

    def _relation(self, edge_type: Optional[str]) -> Optional[str]:
        if not edge_type:
            return None
        return _ident(self._edge(edge_type).get("name") or edge_type, "rel").lower()

    def _options(self, var: dict) -> List[Dict[str, str]]:
        out, seen = [], set()
        for o in var.get("options") or []:
            if isinstance(o, dict):
                name, text = _value_name(o.get("value")), _one_line(self._text(o.get("label"))) or _value_name(o.get("value"))
            else:
                name, text = _value_name(o), str(o)
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "text": text})
        return out

    def _bool_labels(self, var: dict) -> List[Dict[str, str]]:
        opts = self._options(var)
        if len(opts) == 2 and {o["name"] for o in opts} == {"true", "false"}:
            return sorted(opts, key=lambda o: o["name"] != "true")
        return [{"name": "true", "text": "Yes"}, {"name": "false", "text": "No"}]

    # -- ego form ---------------------------------------------------------

    def _new_page(self, stage: dict, title: str) -> SurveyPage:
        raw = self._text(stage.get("label")) or stage.get("id") or "page"
        page = SurveyPage(name=self.page_names.take(_ident(raw, "page").lower(), "page"), title=title)
        self.result.pages.append(page)
        return page

    def _ego_form(self, stage: dict, where: str) -> SurveyPage:
        label = self._text(stage.get("label"))
        form = stage.get("form") or {}
        page = self._new_page(stage, self._text(form.get("title")) or label)
        intro = stage.get("introductionPanel") or {}
        if intro.get("title") or intro.get("text"):
            q = {"name": self.names.take(f"{page.name}_intro", "intro"), "annotation_type": "pure_display",
                 "description": _one_line(self._text(intro.get("title"))) or label or "About you"}
            paras = _paragraphs(self._text(intro.get("text")))
            if paras:
                q["labels"] = paras
            page.questions.append(q)
        variables = (self.codebook.get("ego") or {}).get("variables") or {}
        for field in form.get("fields") or []:
            var_id = field.get("variable")
            var = variables.get(var_id)
            fwhere = f"{where} / {var_id}"
            if not isinstance(var, dict):
                self.result.skip(fwhere, "a form field whose variable is not in the codebook")
                continue
            q = self._ego_question(var_id, var, _one_line(self._text(field.get("prompt"))), fwhere)
            if q:
                page.questions.append(q)
        return page

    def _ego_question(self, var_id: str, var: dict, prompt: str, where: str) -> Optional[dict]:
        vtype, comp = var.get("type"), var.get("component")
        src = var.get("name") or var_id
        name = self.names.take(_ident(src, "q"), "q")
        q: Dict[str, Any] = {"name": name, "description": prompt or str(src)}
        kind = "text"
        if vtype == "text":
            q["annotation_type"] = "text"
            if comp == "TextArea":
                q["textarea"] = {"on": True, "rows": 4}
        elif vtype == "number":
            q["annotation_type"] = "number"
            kind = "number"
        elif vtype in ("categorical", "ordinal"):
            labels = self._options(var)
            if len(labels) < 2:
                self.names._used.discard(name)
                self.result.skip(where, f"{vtype} variable with fewer than two options")
                return None
            single = vtype == "ordinal" or comp == "RadioGroup"
            q["annotation_type"] = "radio" if single else "multiselect"
            q["labels"] = labels
            if vtype == "ordinal" and comp != "RadioGroup":
                q["horizontal"] = True
            kind = "single" if single else "multi"
        elif vtype == "boolean":
            q.update({"annotation_type": "radio", "labels": self._bool_labels(var), "horizontal": True})
            kind = "single"
        elif vtype == "scalar":
            params = var.get("parameters") or {}
            q.update({"annotation_type": "vas", "min_value": 0, "max_value": 1, "precision": 2,
                      "left_label": _one_line(self._text(params.get("minLabel"))) or "Low",
                      "right_label": _one_line(self._text(params.get("maxLabel"))) or "High"})
            kind = "number"
        else:
            self.names._used.discard(name)
            self.result.skip(where, f"variable type {vtype!r}" + (f" ({comp})" if comp else ""),
                             "no Potato question type stores it")
            return None
        self._validation(q, var.get("validation") or {}, where)
        self.ego_vars[var_id] = {"schema": name, "kind": kind}
        self.result.name_map[str(src)] = name
        return q

    def _validation(self, q: dict, validation: dict, where: str) -> None:
        for key, value in validation.items():
            if key == "required":
                if value:
                    q["label_requirement"] = {"required": True}
            elif key in ("minValue", "maxValue") and q["annotation_type"] == "number" \
                    and isinstance(value, (int, float)) and not isinstance(value, bool):
                q["min" if key == "minValue" else "max"] = value
            else:
                self.result.skip(where, f"validation rule {key}", json.dumps(value))

    # -- information ------------------------------------------------------

    def _info_text(self, stage: dict, where: str) -> str:
        parts = []
        title = _one_line(self._text(stage.get("title")))
        if title:
            parts.append(title)
        for item in stage.get("items") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(md_to_text(self._text(item.get("content"))))
            elif isinstance(item, dict):
                self.result.skip(where, f"{item.get('type')} item", "media items are not imported")
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def _information_page(self, stage: dict, where: str) -> SurveyPage:
        label = self._text(stage.get("label"))
        title = _one_line(self._text(stage.get("title"))) or label
        page = self._new_page(stage, title)
        paras: List[str] = []
        for item in stage.get("items") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                paras.extend(_paragraphs(self._text(item.get("content"))))
            elif isinstance(item, dict):
                self.result.skip(where, f"{item.get('type')} item", "media items are not imported")
        q = {"name": self.names.take(f"{page.name}_text", "info"), "annotation_type": "pure_display",
             "description": title or "Information"}
        if paras:
            q["labels"] = paras
        page.questions.append(q)
        return page

    # -- network stages -----------------------------------------------------

    def _group(self, stage: dict, where: str) -> Optional[Dict[str, Any]]:
        ntype = self._node_type(stage)
        if not ntype:
            self.result.skip(where, f"{stage.get('type')} on something other than nodes")
            return None
        group = self.groups.get(ntype)
        if group is None:
            if stage.get("type") not in GENERATORS:
                self.result.skip(where, f"{stage.get('type')} before any name generator for "
                                 f"'{ntype}'", "there is nobody to ask about yet")
                return None
            node = (self.codebook.get("node") or {}).get(ntype) or {}
            label = self._text(stage.get("label")) or "Your network"
            page = self._new_page(stage, label)
            scheme = {"name": self.names.take(f"network_{_ident(node.get('name') or ntype, 'n').lower()}",
                                              "network"),
                      "annotation_type": "ego_network",
                      "description": label, "stages": []}
            page.questions.append(scheme)
            group = {"type": ntype, "scheme": scheme, "page": page, "qnames": set(), "stage_ids": set(),
                     "required": False}
            self.groups[ntype] = group
        elif self.result.pages and self.result.pages[-1] is not group["page"]:
            self.result.warnings.append(
                f"{where}: shown on the '{group['page'].name}' network page with the earlier "
                "stages for the same people, so it now comes before the pages in between")
        return group

    def _stage_id(self, group: dict, raw: Any) -> str:
        base = _ident(raw, "s").lower()
        sid, n = base, 2
        while sid in group["stage_ids"]:
            sid, n = f"{base}_{n}", n + 1
        group["stage_ids"].add(sid)
        return sid

    def _add(self, group: dict, stage: dict, pending: List[str]) -> None:
        if pending:
            stage["instructions"] = " ".join(pending + ([stage["instructions"]] if stage.get("instructions") else []))
            pending.clear()
        group["scheme"]["stages"].append(stage)

    def _node_question(self, group: dict, var_id: str, prompt: str, where: str,
                       force_single: bool = False) -> Optional[dict]:
        var = self._node_var(group["type"], var_id)
        if not isinstance(var, dict):
            self.result.skip(where, f"variable {var_id} is not in the codebook for '{group['type']}'")
            return None
        name = _ident(var.get("name") or var_id, "v")
        if name in group["qnames"]:
            self.result.warnings.append(f"{where}: '{name}' is already asked in an earlier stage; "
                                        "not asked again")
            return None
        vtype, comp = var.get("type"), var.get("component")
        prompt = re.sub(r"\{\s*nodeLabel\s*\}", "{name}", prompt or "") or str(var.get("name") or var_id)
        q: Dict[str, Any] = {"name": name, "description": prompt}
        if vtype == "text":
            q["type"] = "text"
        elif vtype == "number":
            q["type"] = "number"
        elif vtype in ("categorical", "ordinal"):
            labels = self._options(var)
            if len(labels) < 2:
                self.result.skip(where, f"{vtype} variable {name} with fewer than two options")
                return None
            q["type"] = "radio" if (force_single or vtype == "ordinal" or comp == "RadioGroup") else "multiselect"
            q["labels"] = labels
        elif vtype == "boolean":
            q.update({"type": "radio", "labels": self._bool_labels(var)})
        elif vtype == "scalar":
            q.update({"type": "number", "min": 0, "max": 1, "step": 0.01})
            self.result.warnings.append(f"{where}: visual analogue scale '{name}' asked as a number from 0 to 1")
        else:
            self.result.skip(where, f"variable type {vtype!r} for '{name}'", "no per-person question type stores it")
            return None
        validation = var.get("validation") or {}
        if validation.get("required"):
            q["required"] = True
            group["required"] = True
        for key in validation:
            if key not in ("required",):
                if key in ("minValue", "maxValue") and q["type"] == "number":
                    q["min" if key == "minValue" else "max"] = validation[key]
                elif key != "unique":
                    self.result.skip(where, f"validation rule {key} on '{name}'", json.dumps(validation[key]))
        group["qnames"].add(name)
        return q

    def _sets(self, group: dict, attrs: Any, where: str) -> Dict[str, Any]:
        out = {}
        for a in attrs or []:
            if not isinstance(a, dict) or "variable" not in a:
                continue
            var = self._node_var(group["type"], a["variable"]) or {}
            value = a.get("value")
            if isinstance(value, (str, int, float, bool)) or value is None:
                out[_ident(var.get("name") or a["variable"], "v")] = value
            else:
                self.result.skip(where, "additional attribute with a non-scalar value", json.dumps(value))
        return out

    def _roster(self, stage: dict, where: str) -> Optional[List[Dict[str, str]]]:
        asset_id = stage.get("dataSource")
        entry = self.manifest.get(asset_id) if asset_id else None
        if not isinstance(entry, dict):
            self.result.skip(where, "roster data source", f"asset {asset_id!r} is not in the asset manifest")
            return None
        source = str(entry.get("source") or "")
        blob = self.assets.get(source)
        if blob is None:
            self.result.skip(where, "roster data source",
                             f"asset file {source!r} is not in the protocol file; names are typed instead")
            return None
        try:
            raw = blob.read()
        except Exception as e:  # unreadable member
            self.result.skip(where, "roster data source", f"{source}: {e}")
            return None
        names: List[str] = []
        try:
            if source.lower().endswith(".csv"):
                rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
                if rows:
                    cols = list(rows[0].keys())
                    col = next((c for c in cols if c and c.strip().lower() == "name"), cols[0])
                    names = [str(r.get(col) or "").strip() for r in rows]
            elif source.lower().endswith(".json"):
                doc = json.loads(raw.decode("utf-8"))
                for node in (doc.get("nodes") if isinstance(doc, dict) else doc) or []:
                    attrs = node.get("attributes", node) if isinstance(node, dict) else {}
                    value = attrs.get("name")
                    if value is None:
                        value = next((v for v in attrs.values() if isinstance(v, str) and v.strip()), "")
                    names.append(str(value).strip())
            else:
                self.result.skip(where, "roster data source", f"{source}: not a CSV or JSON file")
                return None
        except (ValueError, UnicodeDecodeError, AttributeError) as e:
            self.result.skip(where, "roster data source", f"{source}: {e}")
            return None
        roster, seen = [], set()
        for i, n in enumerate(names):
            if n and n.lower() not in seen:
                seen.add(n.lower())
                roster.append({"id": f"r{i + 1}", "name": n})
        if not roster:
            self.result.skip(where, "roster data source", f"{source}: no names found")
            return None
        if len(roster) > 500:
            self.result.warnings.append(f"{where}: the roster has {len(roster)} names; the page lists "
                                        "them all with a search box")
        return roster

    def _network_stage(self, stage: dict, where: str, pending: List[str]) -> Optional[SurveyPage]:
        group = self._group(stage, where)
        if group is None:
            return None
        stype = stage["type"]
        label = self._text(stage.get("label"))
        prompts = [p for p in stage.get("prompts") or [] if isinstance(p, dict)] or [{}]
        if stage.get("filter"):
            self.result.skip(where, "stage filter", "every alter is shown in every stage")

        if stype in GENERATORS:
            behaviours = stage.get("behaviours") or {}
            roster = self._roster(stage, where) if stype == "NameGeneratorRoster" else None
            for panel in stage.get("panels") or []:
                if isinstance(panel, dict) and panel.get("dataSource") not in (None, "existing"):
                    self.result.skip(where, "side panel with external data", str(panel.get("dataSource")))
            if len(prompts) > 1 and (behaviours.get("minNodes") or behaviours.get("maxNodes")):
                self.result.warnings.append(f"{where}: minNodes/maxNodes apply to the whole stage in "
                                            "Network Canvas; here minNodes is on the first prompt and "
                                            "maxNodes on each prompt")
            for k, prompt in enumerate(prompts):
                ng: Dict[str, Any] = {
                    "type": "name_generator",
                    "id": self._stage_id(group, prompt.get("id") or stage.get("id") or "names"),
                    "title": label + (f" ({k + 1} of {len(prompts)})" if len(prompts) > 1 else ""),
                    "prompt": _one_line(self._text(prompt.get("text"))) or label or "Name people",
                }
                if k == 0 and behaviours.get("minNodes"):
                    ng["min_alters"] = int(behaviours["minNodes"])
                    group["required"] = True
                if behaviours.get("maxNodes"):
                    ng["max_alters"] = int(behaviours["maxNodes"])
                if roster:
                    ng["roster"] = roster
                sets = self._sets(group, prompt.get("additionalAttributes"), where)
                if sets:
                    ng["sets"] = sets
                self._add(group, ng, pending)
            # Form fields beyond the name: asked per person right after.
            if stype == "NameGenerator":
                fields = (stage.get("form") or {}).get("fields") or []
                name_field = None
                for f in fields:
                    var = self._node_var(group["type"], f.get("variable")) or {}
                    if var.get("type") == "text":
                        name_field = f
                        break
                if name_field is None:
                    self.result.warnings.append(f"{where}: the add-person form has no text field; "
                                                "the typed name is stored as the alter's name")
                questions = []
                for f in fields:
                    if f is name_field:
                        continue
                    q = self._node_question(group, f.get("variable"), _one_line(self._text(f.get("prompt"))), where)
                    if q:
                        questions.append(q)
                if questions:
                    self._add(group, {"type": "name_interpreter",
                                      "id": self._stage_id(group, f"{stage.get('id') or 'names'}_details"),
                                      "title": f"{label}: details" if label else "Details",
                                      "prompt": "Answer these questions about each person you added.",
                                      "questions": questions}, pending)
                    self.result.warnings.append(f"{where}: questions on the add-person form are asked "
                                                "per person in a following step")
            return group["page"]

        if stype == "AlterForm":
            questions = []
            for f in (stage.get("form") or {}).get("fields") or []:
                q = self._node_question(group, f.get("variable"), _one_line(self._text(f.get("prompt"))), where)
                if q:
                    questions.append(q)
            intro = stage.get("introductionPanel") or {}
            if questions:
                st = {"type": "name_interpreter", "id": self._stage_id(group, stage.get("id") or "about"),
                      "title": label or "About each person",
                      "prompt": _one_line(self._text(intro.get("text"))) or "Answer these questions about each person.",
                      "questions": questions}
                self._add(group, st, pending)
            return group["page"]

        if stype in ("OrdinalBin", "CategoricalBin"):
            questions = []
            for prompt in prompts:
                if prompt.get("otherVariable"):
                    self.result.skip(where, "'other' bin with a follow-up text variable",
                                     str(prompt.get("otherVariable")))
                q = self._node_question(group, prompt.get("variable"),
                                        _one_line(self._text(prompt.get("text"))), where, force_single=True)
                if q:
                    questions.append(q)
            if questions:
                self._add(group, {"type": "name_interpreter", "id": self._stage_id(group, stage.get("id") or "bins"),
                                  "title": label or "Sort people", "prompt": "Choose one answer for each person.",
                                  "questions": questions}, pending)
                self.result.warnings.append(f"{where}: {stype} (drag each person into a bin) is asked as "
                                            "one choice per person; the answers are the same values")
            return group["page"]

        if stype in ("DyadCensus", "OneToManyDyadCensus", "TieStrengthCensus"):
            if stype == "OneToManyDyadCensus":
                self.result.warnings.append(f"{where}: one-to-many census asked pair by pair; "
                                            "the ties recorded are the same")
            for prompt in prompts:
                text = _one_line(self._text(prompt.get("text"))) or "Do {a} and {b} know each other?"
                if "{a}" not in text:
                    text = f"{text} ({{a}} and {{b}})"
                st: Dict[str, Any] = {"type": "dyad_census",
                                      "id": self._stage_id(group, prompt.get("id") or stage.get("id") or "census"),
                                      "title": label or "Who knows whom", "prompt": text}
                rel = self._relation(prompt.get("createEdge"))
                if rel:
                    st["relation"] = rel
                if stype == "TieStrengthCensus":
                    edge_var = ((self._edge(prompt.get("createEdge")).get("variables") or {})
                                .get(prompt.get("edgeVariable")) or {})
                    labels = self._options(edge_var)
                    if len(labels) >= 2:
                        st["strength_labels"] = labels
                        st["strength_variable"] = _ident(edge_var.get("name") or "strength", "v")
                    else:
                        self.result.skip(where, "tie strength variable", "no options in the codebook; "
                                         "asked as yes/no")
                    if prompt.get("negativeLabel"):
                        st["no_label"] = _one_line(self._text(prompt.get("negativeLabel")))
                self._add(group, st, pending)
            return group["page"]

        if stype == "Sociogram":
            background = stage.get("background") or {}
            if background.get("image"):
                self.result.skip(where, "sociogram background image", str(background["image"]))
            for prompt in prompts:
                edges = prompt.get("edges") or {}
                st = {"type": "sociogram", "id": self._stage_id(group, prompt.get("id") or stage.get("id") or "map"),
                      "title": label or "Arrange your network",
                      "prompt": _one_line(self._text(prompt.get("text"))) or "Arrange the people you named.",
                      "rings": max(0, min(6, int(background.get("concentricCircles") or 0)))}
                rel = self._relation(edges.get("create"))
                if rel:
                    st["relation"] = rel
                else:
                    st["allow_ties"] = False
                highlight = prompt.get("highlight") or {}
                if highlight.get("allowHighlighting") or highlight.get("variable"):
                    self.result.skip(where, "sociogram highlighting", str(highlight.get("variable") or ""))
                self._add(group, st, pending)
            return group["page"]
        return None

    def _finish_groups(self) -> None:
        from potato.server_utils.schemas.ego_network import EgoNetworkConfigError, normalize_scheme
        for group in self.groups.values():
            scheme = group["scheme"]
            if group["required"]:
                scheme["label_requirement"] = {"required": True}
            try:
                normalize_scheme(scheme)
            except EgoNetworkConfigError as e:
                group["page"].questions.remove(scheme)
                self.result.skip(f"network page '{group['page'].name}'", "ego_network scheme", str(e))

    # -- skip logic -----------------------------------------------------------

    def _rule_item(self, flt: dict, where: str) -> Optional[dict]:
        rules = [r for r in (flt or {}).get("rules") or [] if isinstance(r, dict)]
        if not rules:
            return None
        items = []
        for r in rules:
            if r.get("type") != "ego":
                raise Untranslatable(f"a rule on {r.get('type')} data (only ego variables can be "
                                     "tested on a Potato page)")
            items.append(self._ego_rule(r.get("options") or {}))
        join = "any" if str(flt.get("join") or "AND").upper() == "OR" else "all"
        return items[0] if len(items) == 1 else {join: items}

    def _ego_rule(self, opts: dict) -> dict:
        var_id = opts.get("attribute")
        info = self.ego_vars.get(var_id)
        if info is None:
            raise Untranslatable(f"variable {var_id} is not asked on an imported page")
        schema, kind = info["schema"], info["kind"]
        op = str(opts.get("operator") or "").upper().replace(" ", "_")
        value = opts.get("value")

        def names(v):
            return [_value_name(x) for x in v] if isinstance(v, list) else _value_name(v)

        def leaf(operator, val=None):
            item = {"schema": schema, "operator": operator}
            if val is not None:
                item["value"] = val
            return item

        if op == "EXISTS":
            return leaf("not_empty")
        if op == "NOT_EXISTS":
            return leaf("empty")
        if op in ("OPTIONS_GREATER_THAN", "OPTIONS_LESS_THAN", "OPTIONS_EQUALS", "OPTIONS_NOT_EQUALS"):
            operator = {"OPTIONS_GREATER_THAN": "count_gt", "OPTIONS_LESS_THAN": "count_lt"}.get(op, "count_equals")
            item = leaf(operator, value)
            return {"not": item} if op == "OPTIONS_NOT_EQUALS" else item
        if op in ("GREATER_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN", "LESS_THAN_OR_EQUAL"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise Untranslatable(f"{op} with a non-numeric value {value!r}")
            return leaf({"GREATER_THAN": "gt", "GREATER_THAN_OR_EQUAL": "gte", "LESS_THAN": "lt",
                         "LESS_THAN_OR_EQUAL": "lte"}[op], value)
        if kind == "multi":
            vals = names(value) if isinstance(value, list) else [names(value)]
            if op == "EXACTLY":
                return {"all": [leaf("contains", v) for v in vals] + [leaf("count_equals", len(vals))]}
            if op == "NOT":
                return {"not": {"all": [leaf("contains", v) for v in vals] + [leaf("count_equals", len(vals))]}}
            if op in ("INCLUDES", "EXCLUDES") and vals:
                operator = "contains" if op == "INCLUDES" else "not_contains"
                return leaf(operator, vals[0]) if len(vals) == 1 else {"all": [leaf(operator, v) for v in vals]}
        if kind == "single":
            if op in ("EXACTLY", "INCLUDES"):
                return leaf("equals", names(value))
            if op in ("NOT", "EXCLUDES"):
                return leaf("not_equals", names(value))
        if kind in ("text", "number"):
            if op == "EXACTLY":
                return leaf("equals", value)
            if op == "NOT":
                return leaf("not_equals", value)
            if op == "CONTAINS" and kind == "text":
                return leaf("contains", str(value))
            if op in ("DOES_NOT_CONTAIN", "DOES_NOT_CONTAINS") and kind == "text":
                return leaf("not_contains", str(value))
        raise Untranslatable(f"operator {op} on a {kind} question")

    def _skip_logic(self, stages: List[dict]) -> None:
        ids = {s.get("id"): i for i, s in enumerate(stages) if isinstance(s, dict)}
        for idx, stage in enumerate(stages):
            if not isinstance(stage, dict) or not stage.get("skipLogic"):
                continue
            if stage.get("type") in NETWORK_STAGES:
                continue  # reported where the stage was read
            logic = stage["skipLogic"]
            where = f"stage {idx + 1} '{self._text(stage.get('label')) or stage.get('id')}'"
            detail = json.dumps(logic.get("filter"))[:300]
            try:
                item = self._rule_item(logic.get("filter") or {}, where)
            except Untranslatable as e:
                self.result.skip(where, "skip logic", f"{e}: {detail}")
                continue
            if item is None:
                continue
            action = str(logic.get("action") or "SHOW").upper()
            if action == "SHOW":
                page = self.stage_pages.get(idx)
                if page is None:
                    self.result.skip(where, "skip logic on a stage that was not imported", detail)
                    continue
                page.show_when = and_rules(page.show_when, combine([item]))
                continue
            dest = (logic.get("destination") or {}).get("stageId")
            if dest is None:
                page = self.stage_pages.get(idx)
                if page is None:
                    self.result.skip(where, "skip logic on a stage that was not imported", detail)
                    continue
                page.show_when = and_rules(page.show_when, combine([{"not": item}]))
                continue
            j = ids.get(dest)
            if j is None or j <= idx:
                self.result.skip(where, "skip logic", f"destination {dest!r} is not a later stage")
                continue
            if stages[j].get("type") == "FinishSession":
                before = [p for i, p in sorted(self.stage_pages.items()) if i < idx]
                if not before:
                    self.result.skip(where, "skip to the end", "no page before this stage to end on")
                    continue
                target = before[-1]
                if target.exit_when:
                    self.result.skip(where, "a second skip-to-end on one page", detail)
                    continue
                message = _one_line(self._text(stages[j].get("content"))) or "Thank you. This is the end of the study."
                target.exit_when = {**combine([item]), "message": message}
                continue
            skipped = {id(p): p for i, p in self.stage_pages.items() if idx <= i < j}
            for page in skipped.values():
                page.show_when = and_rules(page.show_when, combine([{"not": item}]))


class _LazyAsset:
    """An asset file read on demand (from the zip or the assets folder)."""

    def __init__(self, path: Path, member: Optional[str]):
        self.path, self.member = path, member

    def read(self) -> bytes:
        if self.member is None:
            return Path(self.path).read_bytes()
        with zipfile.ZipFile(self.path) as zf:
            return zf.read(self.member)
