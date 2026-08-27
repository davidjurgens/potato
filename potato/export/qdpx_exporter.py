"""
REFI-QDA ``.qdpx`` exporter.

The counterpart to :mod:`potato.importers.text.qdpx_importer`. ``.qdpx`` is how
a qualitative project moves between NVivo, ATLAS.ti, MAXQDA, Quirkos and QDA
Miner, so writing it is what lets a Potato project be handed to a colleague who
uses one of those -- or archived in a form that outlives this tool.

Layout
------
A ZIP holding ``project.qde`` (REFI-QDA XML, namespace
``urn:QDA-XML:project:1.0``) and ``sources/<guid>.txt``, one UTF-8 text file
per annotated item, exactly as §8.3 requires.

Offsets
-------
``endPosition`` names the *last character* (REFI-QDA 1.5 §10.2), so it is
written as ``end - 1`` against Potato's exclusive end. See the importer's
module docstring for the full quotation and for why the reading is checked
rather than assumed on the way back in.

``flatten_subcodes``
--------------------
Not optional polish. REFI-QDA nests ``<Code>`` inside ``<Code>`` to any depth
and Potato's hierarchical schemas do too, but ATLAS.ti supports a single level
of subcode -- so a three-deep codebook exported faithfully is a codebook
ATLAS.ti mangles on import, with no warning to the researcher. Passing
``flatten_subcodes`` re-parents every code to its top-level ancestor and names
it ``Parent > Child > Grandchild``, which loses the tree but keeps the
identity of every code legible.
"""

from __future__ import annotations

import logging
import os
import uuid
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .codebook_exporter import CODEBOOK_SCHEMA_TYPES, CodebookExporter

logger = logging.getLogger(__name__)

QDA_NS = "urn:QDA-XML:project:1.0"

#: Schema types whose labels become REFI-QDA codes. Reusing the codebook
#: exporter's set rather than restating it means a schema that starts counting
#: as codeable does so in both places at once.
CODEABLE = CODEBOOK_SCHEMA_TYPES

#: Separator used by ``flatten_subcodes``. ``>`` is what ATLAS.ti and MAXQDA
#: both display for a code path, so a flattened name reads naturally there.
PATH_SEPARATOR = " > "


def _deterministic_guid(*parts: str) -> str:
    """
    A stable GUID derived from what it names.

    REFI-QDA requires a GUID on every code, source and selection.
    ``uuid.uuid4()`` would satisfy the schema while making two exports of an
    unchanged project differ in every line, which destroys the ability to diff
    an export -- the cheapest way there is to see what an edit actually did.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "potato:qdpx:" + "|".join(parts)))


class QDPXExporter(BaseExporter):
    format_name = "qdpx"
    description = ("REFI-QDA project exchange (.qdpx) for NVivo, ATLAS.ti, "
                   "MAXQDA, Quirkos and QDA Miner")
    file_extensions = [".qdpx"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(s.get("annotation_type") in CODEABLE for s in context.schemas):
            return False, ("No codeable schema (span/radio/multiselect/...) in "
                           "config, so there is no codebook to export")
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        flatten = bool(options.get("flatten_subcodes", False))
        warnings: List[str] = []

        os.makedirs(output_path, exist_ok=True)
        project_name = context.config.get("annotation_task_name", "Potato project")
        out_file = os.path.join(output_path, f"{_safe_stem(project_name)}.qdpx")

        codes, code_guid = self._build_codes(context, flatten, warnings)
        users, user_guid = self._build_users(context)

        root = ET.Element(f"{{{QDA_NS}}}Project", {
            "name": project_name,
            "origin": "Potato",
        })
        if users:
            root.append(users)
        root.append(codes)

        sources_element = ET.SubElement(root, f"{{{QDA_NS}}}Sources")
        payloads: Dict[str, str] = {}
        num_selections = 0

        for instance_id, text in self._iter_texts(context, warnings):
            guid = _deterministic_guid("source", instance_id)
            member = f"{guid}.txt"
            payloads[member] = text

            source = ET.SubElement(sources_element, f"{{{QDA_NS}}}TextSource", {
                "guid": guid,
                "name": instance_id,
                # internal:// is the naming scheme §8.3 fixes for embedded
                # files. A bare filename here is read as an external path and
                # the importing tool then asks the user to locate a file that
                # is already inside the archive.
                "plainTextPath": f"internal://{member}",
            })
            num_selections += self._write_selections(
                source, context, instance_id, text, code_guid, user_guid,
                warnings)

        self._write_archive(out_file, root, payloads)

        logger.info("QDPX exported to %s: %d source(s), %d selection(s)",
                    out_file, len(payloads), num_selections)
        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[out_file],
            warnings=warnings,
            stats={
                "num_sources": len(payloads),
                "num_selections": num_selections,
                "num_codes": len(code_guid),
                "flattened": flatten,
            },
        )

    # -------------------------------------------------------------- internals

    @staticmethod
    def _build_codes(context: ExportContext, flatten: bool,
                     warnings: List[str]) -> Tuple[ET.Element, Dict[str, str]]:
        """
        Build ``<CodeBook><Codes>`` and a ``code name -> guid`` index.

        The tree is walked through ``CodebookExporter._iter_codes``, which
        already knows how each schema type nests, so the two exporters cannot
        disagree about what the codebook contains.
        """
        codebook = ET.Element(f"{{{QDA_NS}}}CodeBook")
        codes_element = ET.SubElement(codebook, f"{{{QDA_NS}}}Codes")

        # name -> (parent name, description, colour), in declaration order.
        entries: Dict[str, Tuple[str, str, str]] = {}
        for scheme in context.schemas:
            if scheme.get("annotation_type") not in CODEABLE:
                continue
            for row in CodebookExporter._iter_codes(scheme):
                name = row.get("code") or ""
                if name and name not in entries:
                    entries[name] = (row.get("parent") or "",
                                     row.get("description") or "",
                                     row.get("color") or "")

        guid_by_name: Dict[str, str] = {}
        element_by_name: Dict[str, ET.Element] = {}
        depth_warned = False

        def path_of(name: str) -> str:
            parts = [name]
            seen = {name}
            parent = entries.get(name, ("", "", ""))[0]
            while parent and parent not in seen:
                parts.append(parent)
                seen.add(parent)
                parent = entries.get(parent, ("", "", ""))[0]
            return PATH_SEPARATOR.join(reversed(parts))

        def depth_of(name: str) -> int:
            return path_of(name).count(PATH_SEPARATOR)

        for name, (parent, description, colour) in entries.items():
            if flatten:
                display = path_of(name)
                container = codes_element
            else:
                display = name
                container = element_by_name.get(parent, codes_element)
                if parent and parent not in element_by_name:
                    # A child declared before its parent, which the schema
                    # config allows. Hanging it off the root keeps the code
                    # rather than dropping it, and the name still says where
                    # it belongs.
                    display = path_of(name)
                if not depth_warned and depth_of(name) >= 2:
                    warnings.append(
                        "This codebook nests more than one level deep. "
                        "ATLAS.ti supports a single level of subcode and will "
                        "flatten or drop the rest on import -- pass "
                        "flatten_subcodes to control how that happens.")
                    depth_warned = True

            guid = _deterministic_guid("code", display)
            guid_by_name[name] = guid
            element = ET.SubElement(container, f"{{{QDA_NS}}}Code", {
                "guid": guid,
                "name": display,
                # Required by the schema. Every code Potato exports is one an
                # annotator can apply, so it is always true.
                "isCodable": "true",
            })
            if colour:
                element.set("color", colour)
            if description:
                ET.SubElement(element, f"{{{QDA_NS}}}Description").text = description
            element_by_name[name] = element

        return codebook, guid_by_name

    @staticmethod
    def _build_users(context: ExportContext) -> Tuple[Optional[ET.Element],
                                                      Dict[str, str]]:
        names = []
        for annotation in context.annotations:
            user = annotation.get("user_id")
            if user and user not in names:
                names.append(user)
        if not names:
            return None, {}

        element = ET.Element(f"{{{QDA_NS}}}Users")
        guids = {}
        for user in names:
            guid = _deterministic_guid("user", user)
            guids[user] = guid
            ET.SubElement(element, f"{{{QDA_NS}}}User",
                          {"guid": guid, "name": user, "id": user})
        return element, guids

    @staticmethod
    def _iter_texts(context: ExportContext, warnings: List[str]):
        """Yield ``(instance_id, text)`` for every item that has text."""
        text_key = context.config.get("item_properties", {}).get("text_key", "text")
        annotated = {a.get("instance_id") for a in context.annotations}

        for instance_id, item in context.items.items():
            if not isinstance(item, dict):
                continue
            value = item.get(text_key)
            if value is None:
                for alternative in ("text", "sentence", "content"):
                    if alternative in item:
                        value = item[alternative]
                        break
            if isinstance(value, list):
                value = " ".join(str(part) for part in value)
            if not isinstance(value, str) or not value:
                if instance_id in annotated:
                    warnings.append(
                        f"{instance_id} has annotations but no text under "
                        f"'{text_key}', so its codings have nothing to attach "
                        f"to and were not exported")
                continue
            yield instance_id, value

    @staticmethod
    def _write_selections(source: ET.Element, context: ExportContext,
                          instance_id: str, text: str,
                          code_guid: Dict[str, str], user_guid: Dict[str, str],
                          warnings: List[str]) -> int:
        written = 0
        for annotation in context.annotations:
            if annotation.get("instance_id") != instance_id:
                continue
            user = annotation.get("user_id") or ""

            for schema_name, span_list in (annotation.get("spans") or {}).items():
                for span in span_list or []:
                    start = int(span.get("start", 0))
                    end = int(span.get("end", 0))
                    label = span.get("name") or span.get("label") or ""
                    if end <= start or end > len(text):
                        warnings.append(
                            f"{instance_id}: span [{start},{end}) does not fit "
                            f"its {len(text)}-character text; skipped")
                        continue
                    guid = code_guid.get(label)
                    if guid is None:
                        warnings.append(
                            f"{instance_id}: span label '{label}' is not in "
                            f"the codebook, so no CodeRef could be written")
                        continue

                    selection = ET.SubElement(
                        source, f"{{{QDA_NS}}}PlainTextSelection", {
                            "guid": _deterministic_guid(
                                "selection", instance_id, user, schema_name,
                                label, str(start), str(end)),
                            # Tools display this, and it is also the only
                            # ground truth an importer has for checking which
                            # end-position convention a file used.
                            "name": text[start:end],
                            "startPosition": str(start),
                            # REFI-QDA 1.5 §10.2: the LAST character, not one
                            # past it.
                            "endPosition": str(end - 1),
                        })
                    if user and user in user_guid:
                        selection.set("creatingUser", user_guid[user])
                    ET.SubElement(
                        selection, f"{{{QDA_NS}}}Coding",
                        {"guid": _deterministic_guid(
                            "coding", instance_id, user, label,
                            str(start), str(end))},
                    ).append(ET.Element(f"{{{QDA_NS}}}CodeRef",
                                        {"targetGUID": guid}))
                    written += 1

            # Document-level labels become codings on the source itself, which
            # is how REFI-QDA expresses "this code applies to the whole thing".
            for schema_name, payload in (annotation.get("labels") or {}).items():
                for label in _label_names(payload):
                    guid = code_guid.get(label)
                    if guid is None:
                        continue
                    coding = ET.SubElement(
                        source, f"{{{QDA_NS}}}Coding",
                        {"guid": _deterministic_guid(
                            "doc-coding", instance_id, user, schema_name,
                            label)})
                    ET.SubElement(coding, f"{{{QDA_NS}}}CodeRef",
                                  {"targetGUID": guid})
        return written

    @staticmethod
    def _write_archive(out_file: str, root: ET.Element,
                       payloads: Dict[str, str]) -> None:
        ET.register_namespace("", QDA_NS)
        xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project.qde", xml)
            for member, text in payloads.items():
                # §9.1.2 requires UTF-8 for plain text sources, and the
                # offsets in project.qde are code-point positions into exactly
                # these bytes.
                archive.writestr(f"sources/{member}", text.encode("utf-8"))


def _label_names(payload) -> List[str]:
    """The label names in one schema's stored value, whatever shape it is in."""
    if isinstance(payload, dict):
        return [name for name, value in payload.items() if value]
    if isinstance(payload, list):
        return [str(entry) for entry in payload]
    if payload in (None, ""):
        return []
    return [str(payload)]


def _safe_stem(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    return cleaned.strip().replace(" ", "_") or "project"
