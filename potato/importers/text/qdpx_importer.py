"""
REFI-QDA ``.qdpx`` importer.

``.qdpx`` is how qualitative researchers move a project between NVivo,
ATLAS.ti, MAXQDA, Quirkos, Dedoose and QDA Miner. Potato had no mention of it
anywhere, which meant a researcher with a coded project had no way in --
the memos, the codebook and the cross-tabs we already have were unreachable to
anyone who had already started work somewhere else.

Container
---------
A ``.qdpx`` is a ZIP holding ``project.qde`` (the REFI-QDA XML) and a
``sources/`` folder whose members are named by GUID. Text sources are UTF-8
``.txt`` files referenced as ``internal://<guid>.txt``, or inlined in a
``<PlainTextContent>`` element -- the spec allows exactly one of the two.

The offset convention
---------------------
This is the part that silently corrupts a project if you get it wrong. REFI-QDA
1.5 §10.2 is explicit:

    Selections in a text file are defined by the first and the last character
    (Unicode codepoint) in the file. The first codepoint in the file has the
    number 0 (zero).

So positions are **0-based Unicode code points** -- the same unit Python
indexes strings in, which means no UTF-16 conversion is needed -- but
``endPosition`` names *the last character*, making it **inclusive**, where
Potato's ``end`` is exclusive. Import therefore adds one and export subtracts
one.

Exporting tools have not all read that paragraph the same way, and a file
written with an exclusive end loses its final character on import. Rather than
leave that to a flag nobody knows to set, :meth:`QDPXImporter.parse_path`
measures both readings against the source text and reports which one fits --
see :func:`_infer_end_convention`.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import BaseTextImporter, ImportedDocument, ImportedSpan, TextImportResult

logger = logging.getLogger(__name__)

#: The project-exchange namespace. Files in the wild are inconsistent about
#: declaring it, so every lookup goes through `_tag` rather than assuming.
QDA_NS = "urn:QDA-XML:project:1.0"

#: Name of the XML document inside the archive. The spec fixes it, but a few
#: exporters have shipped it capitalized, so lookup is case-insensitive.
PROJECT_MEMBER = "project.qde"

_NS_STRIP = re.compile(r"^\{[^}]*\}")


def _tag(element: ET.Element) -> str:
    """The element's local name, with any namespace stripped."""
    return _NS_STRIP.sub("", element.tag)


def _find(parent: ET.Element, name: str) -> Optional[ET.Element]:
    for child in parent:
        if _tag(child) == name:
            return child
    return None


def _findall(parent: ET.Element, name: str) -> List[ET.Element]:
    return [child for child in parent if _tag(child) == name]


def _infer_end_convention(pairs: List[Tuple[int, int, str, str]]) -> str:
    """
    Decide whether ``endPosition`` was written inclusively or exclusively.

    ``pairs`` is ``(start, end, selection_name, source_text)``. Many tools set
    a selection's ``name`` to the quoted text itself, which gives a ground
    truth to check against: whichever reading reproduces more names is the one
    the file used.

    Returns ``"inclusive"`` (the spec's own reading, and the default when
    there is nothing to measure), ``"exclusive"``, or ``"unknown"`` when the
    evidence is tied.
    """
    inclusive_hits = exclusive_hits = 0
    for start, end, name, text in pairs:
        if not name or start < 0:
            continue
        if text[start:end + 1] == name:
            inclusive_hits += 1
        if text[start:end] == name:
            exclusive_hits += 1

    if inclusive_hits == exclusive_hits:
        return "unknown"
    return "inclusive" if inclusive_hits > exclusive_hits else "exclusive"


class QDPXImporter(BaseTextImporter):
    format_name = "qdpx"
    description = ("REFI-QDA project exchange (.qdpx) from NVivo, ATLAS.ti, "
                   "MAXQDA, Quirkos and others")
    file_extensions = [".qdpx", ".qde"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file():
            return False
        suffix = path.suffix.lower()
        if suffix == ".qde":
            return True
        if suffix not in (".qdpx", ".zip"):
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                return any(name.lower().endswith(PROJECT_MEMBER)
                           for name in archive.namelist())
        except (zipfile.BadZipFile, OSError):
            return False

    def parse_path(self, path: Path,
                   options: Optional[dict] = None) -> TextImportResult:
        options = options or {}
        path = Path(path)
        if not path.is_file():
            raise ValueError(f"{path} is not a file")

        root, sources = self._open(path)
        if _tag(root) != "Project":
            raise ValueError(
                f"{path} does not hold a REFI-QDA <Project>; its root element "
                f"is <{_tag(root)}>")

        result = TextImportResult()
        codes, code_by_guid = self._read_codebook(root)
        result.labels = codes

        users = self._read_users(root)
        result.annotators = sorted(users.values())

        sources_element = _find(root, "Sources")
        text_sources = _findall(sources_element, "TextSource") if sources_element is not None else []
        if not text_sources:
            result.warnings.append(
                "The project has no <TextSource>. Picture, PDF, audio and "
                "video sources are not imported yet, so an audio-only project "
                "arrives empty.")

        # Read every source's text first: the end-position convention is a
        # property of the FILE, not of one selection, so it has to be decided
        # across all of them before any span is built.
        loaded: List[Tuple[ET.Element, str, str]] = []
        for element in text_sources:
            name = element.get("name") or element.get("guid") or "source"
            text = self._read_source_text(element, sources, result.warnings)
            if text is None:
                continue
            loaded.append((element, name, text))

        convention = self._decide_convention(loaded, options, result.warnings)
        inclusive = convention != "exclusive"

        for element, name, text in loaded:
            document = self._build_document(
                element, name, text, code_by_guid, users, inclusive,
                result.warnings)
            result.documents.append(document)

        result.verify()
        result.summarize(
            num_sources=len(text_sources),
            end_position=convention,
        )
        return result

    # -------------------------------------------------------------- internals

    @staticmethod
    def _open(path: Path) -> Tuple[ET.Element, Dict[str, bytes]]:
        """Return the parsed project element and the archive's source members."""
        if path.suffix.lower() == ".qde":
            # A bare .qde has no sources folder, so any source referenced as
            # internal:// is simply absent -- reported per source, not here.
            return ET.parse(path).getroot(), {}

        sources: Dict[str, bytes] = {}
        with zipfile.ZipFile(path) as archive:
            project_name = next(
                (n for n in archive.namelist()
                 if n.lower().endswith(PROJECT_MEMBER)), None)
            if project_name is None:
                raise ValueError(
                    f"{path} is a ZIP but contains no {PROJECT_MEMBER}")
            root = ET.fromstring(archive.read(project_name))
            for member in archive.namelist():
                if member.lower().endswith("/") or member == project_name:
                    continue
                sources[Path(member).name] = archive.read(member)
        return root, sources

    @staticmethod
    def _read_users(root: ET.Element) -> Dict[str, str]:
        users_element = _find(root, "Users")
        if users_element is None:
            return {}
        users = {}
        for user in _findall(users_element, "User"):
            guid = user.get("guid")
            if guid:
                users[guid] = user.get("name") or user.get("id") or guid
        return users

    @staticmethod
    def _read_codebook(root: ET.Element) -> Tuple[List[dict], Dict[str, dict]]:
        """
        Flatten the code tree, keeping each code's parent.

        REFI-QDA nests ``<Code>`` inside ``<Code>`` to any depth. Potato's span
        labels are flat, so the hierarchy is carried on each label as
        ``parent`` -- which is what the codebook exporter reads, so a nested
        codebook survives a round trip even though the span schema itself is
        flat.
        """
        codebook = _find(root, "CodeBook")
        codes_element = _find(codebook, "Codes") if codebook is not None else None
        if codes_element is None:
            return [], {}

        flat: List[dict] = []
        by_guid: Dict[str, dict] = {}

        def walk(element: ET.Element, parent: str) -> None:
            for code in _findall(element, "Code"):
                name = code.get("name") or ""
                if not name:
                    continue
                description = _find(code, "Description")
                entry = {"name": name}
                if parent:
                    entry["parent"] = parent
                if description is not None and (description.text or "").strip():
                    entry["description"] = description.text.strip()
                colour = code.get("color")
                if colour:
                    entry["color"] = colour
                flat.append(entry)
                guid = code.get("guid")
                if guid:
                    by_guid[guid] = entry
                walk(code, name)

        walk(codes_element, "")
        return flat, by_guid

    @staticmethod
    def _read_source_text(element: ET.Element, sources: Dict[str, bytes],
                          warnings: List[str]) -> Optional[str]:
        """
        Read a TextSource's plain text, from wherever the spec allows it.

        §9.1.2: exactly one of ``plainTextPath`` and ``<PlainTextContent>`` is
        filled, and the encoding must be UTF-8.
        """
        name = element.get("name") or element.get("guid") or "source"

        inline = _find(element, "PlainTextContent")
        if inline is not None and inline.text is not None:
            return inline.text

        plain_path = element.get("plainTextPath") or ""
        if not plain_path:
            warnings.append(
                f"'{name}' has neither plainTextPath nor PlainTextContent, so "
                f"there is no text for its selections to point into; skipped")
            return None

        member = Path(plain_path.split("://", 1)[-1]).name
        payload = sources.get(member)
        if payload is None:
            warnings.append(
                f"'{name}' points at {plain_path}, which is not in the "
                f"archive; skipped")
            return None

        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            # The spec requires UTF-8, but a project exported from a
            # Windows-codepage tool will not be, and failing the whole import
            # over one source helps nobody.
            warnings.append(
                f"'{name}' is not valid UTF-8, which REFI-QDA requires. "
                f"Undecodable bytes were replaced, so its offsets may shift.")
            return payload.decode("utf-8", errors="replace")

    def _decide_convention(self, loaded: List[Tuple[ET.Element, str, str]],
                           options: dict, warnings: List[str]) -> str:
        forced = options.get("qdpx_end_position")
        if forced in ("inclusive", "exclusive"):
            return forced

        evidence: List[Tuple[int, int, str, str]] = []
        for element, _name, text in loaded:
            for selection in _findall(element, "PlainTextSelection"):
                try:
                    start = int(selection.get("startPosition", -1))
                    end = int(selection.get("endPosition", -1))
                except (TypeError, ValueError):
                    continue
                evidence.append((start, end, selection.get("name") or "", text))

        verdict = _infer_end_convention(evidence)
        if verdict == "exclusive":
            warnings.append(
                "This file writes endPosition EXCLUSIVELY, which contradicts "
                "REFI-QDA 1.5 §10.2 ('the first and the last character'). The "
                "offsets were read as written; pass qdpx_end_position to "
                "override.")
            return "exclusive"
        if verdict == "unknown":
            logger.debug("No quoted selection names to check endPosition "
                         "against; using the spec's inclusive reading")
        return "inclusive"

    @staticmethod
    def _build_document(element: ET.Element, name: str, text: str,
                        code_by_guid: Dict[str, dict], users: Dict[str, str],
                        inclusive: bool,
                        warnings: List[str]) -> ImportedDocument:
        spans: List[ImportedSpan] = []

        for selection in _findall(element, "PlainTextSelection"):
            try:
                start = int(selection.get("startPosition"))
                raw_end = int(selection.get("endPosition"))
            except (TypeError, ValueError):
                warnings.append(
                    f"'{name}': a PlainTextSelection has no usable "
                    f"startPosition/endPosition; skipped")
                continue

            end = raw_end + 1 if inclusive else raw_end
            if not 0 <= start < end <= len(text):
                warnings.append(
                    f"'{name}': selection [{start},{end}) does not fit the "
                    f"{len(text)}-character source; skipped")
                continue

            annotator = users.get(selection.get("creatingUser") or "")
            codings = _findall(selection, "Coding")
            if not codings:
                # An uncoded selection is a highlight, not an annotation.
                # Dropping it loses nothing an annotator would act on, but it
                # is worth saying so rather than leaving a silent count gap.
                warnings.append(
                    f"'{name}': selection [{start},{end}) carries no code and "
                    f"was not imported as a span")
                continue

            for coding in codings:
                reference = _find(coding, "CodeRef")
                target = reference.get("targetGUID") if reference is not None else None
                code = code_by_guid.get(target or "")
                if code is None:
                    warnings.append(
                        f"'{name}': a coding points at code {target}, which is "
                        f"not in the codebook; skipped")
                    continue
                spans.append(ImportedSpan(
                    start=start, end=end, label=code["name"],
                    text=text[start:end], annotator=annotator,
                ))

        document = ImportedDocument(instance_id=name, text=text, spans=spans)

        description = _find(element, "Description")
        if description is not None and (description.text or "").strip():
            document.extra["description"] = description.text.strip()

        # Codings hung directly off the source apply to the whole document.
        whole_document = []
        for coding in _findall(element, "Coding"):
            reference = _find(coding, "CodeRef")
            target = reference.get("targetGUID") if reference is not None else None
            code = code_by_guid.get(target or "")
            if code is not None:
                whole_document.append(code["name"])
        if whole_document:
            document.extra["document_codes"] = whole_document

        return document
