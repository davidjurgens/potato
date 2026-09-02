"""
CoNLL importer -- CoNLL-2003 column format and CoNLL-U.

Potato already *wrote* both formats (``potato/export/conll_2003_exporter.py``,
``conll_u_exporter.py``) and could read neither, so the most common way to
arrive with an existing NER corpus was to have someone write a conversion
script first.

Reconstructing character offsets
--------------------------------
CoNLL is token-based: it records what the tokens are and what tag each carries,
not where they sat in a string. Potato spans are character offsets, so the text
has to be rebuilt before any span exists at all, and how faithfully depends on
what the file preserved:

* **CoNLL-U with ``# text =``** -- exact. The sentence string is in the file;
  tokens are located inside it by scanning forward, so the offsets are the
  original ones.
* **CoNLL-U without it** -- rebuilt from tokens, respecting ``SpaceAfter=No``
  in MISC, which is what the format carries the feature for.
* **CoNLL-2003** -- tokens joined with single spaces. The format records no
  spacing at all, so ``"Dr. Smith"`` and ``"Dr.  Smith"`` are the same file.
  Offsets are internally consistent and correct against the reconstructed text
  we store, which is the text annotators will see.

Because the *stored* text is the reconstruction, spans always line up with what
is displayed. The lossy step is upstream, in what CoNLL chose to record.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseTextImporter, ImportedDocument, ImportedSpan, TextImportResult

logger = logging.getLogger(__name__)

#: A CoNLL-2003 document separator. The tag columns after it vary between
#: distributions ("-DOCSTART- -X- -X- O", "-DOCSTART- -X- O O"), so only the
#: first field is matched.
DOCSTART = "-DOCSTART-"

#: ``# sent_id = <doc>-s<n>``, which is what our own CoNLL-U exporter writes.
#: Matching it is what lets an export-import round trip recover the original
#: instance ids rather than inventing new ones.
SENT_ID_DOC = re.compile(r"^(?P<doc>.+)-s\d+$")


def bio_tags_to_spans(tags: List[str]) -> List[Tuple[int, int, str]]:
    """
    Collapse a per-token tag sequence into ``(first_token, last_token, label)``.

    Handles the four schemes that turn up in real corpora, because a reader
    that only understands strict IOB2 silently merges adjacent same-type
    entities in an IOB1 file -- two ``PER`` mentions become one, and nothing
    reports it:

    * **IOB2 / BIO** -- ``B-`` always opens.
    * **IOB1** -- ``I-`` opens when the previous token was ``O`` or a different
      type, which is the only signal IOB1 gives.
    * **BIOES / IOBES** -- ``S-`` is a whole entity, ``E-`` closes one.
    * **BILOU** -- ``U-`` and ``L-`` are the same two roles under other names.

    Returns token index pairs with ``last`` inclusive; the caller turns those
    into character offsets, since only it knows where the tokens landed.
    """
    spans: List[Tuple[int, int, str]] = []
    open_start: Optional[int] = None
    open_label: Optional[str] = None

    def close(end_index: int) -> None:
        nonlocal open_start, open_label
        if open_start is not None and open_label is not None:
            spans.append((open_start, end_index, open_label))
        open_start = None
        open_label = None

    for i, raw in enumerate(tags):
        tag = (raw or "O").strip()
        if tag in ("O", "_", ""):
            close(i - 1)
            continue

        prefix, _, label = tag.partition("-")
        if not label:
            # A bare label with no prefix ("PER" rather than "B-PER") is a
            # real, if sloppy, variant. Treat it as IOB1 continuation.
            prefix, label = "I", tag

        if prefix in ("B", "S", "U"):
            close(i - 1)
            open_start, open_label = i, label
            if prefix in ("S", "U"):
                close(i)
        elif prefix in ("I", "E", "L"):
            if open_label != label:
                # IOB1: an I- that does not continue anything opens an entity.
                close(i - 1)
                open_start, open_label = i, label
            if prefix in ("E", "L"):
                close(i)
        else:
            close(i - 1)

    close(len(tags) - 1)
    return spans


def _locate_tokens(tokens: List[str], text: str) -> List[Tuple[int, int]]:
    """
    Find each token inside ``text``, scanning forward and never backtracking.

    Forward-only matters: searching the whole string for each token makes a
    repeated word bind to its first occurrence, so every later span collapses
    onto the same offsets. A token that cannot be found from the current cursor
    yields ``(-1, -1)`` and the caller drops the span rather than guessing.
    """
    offsets: List[Tuple[int, int]] = []
    cursor = 0
    for token in tokens:
        found = text.find(token, cursor)
        if found < 0:
            offsets.append((-1, -1))
            continue
        offsets.append((found, found + len(token)))
        cursor = found + len(token)
    return offsets


class _Sentence:
    """One blank-line-delimited block, with whatever comments preceded it."""

    __slots__ = ("tokens", "tags", "text", "sent_id", "newdoc_id", "space_after")

    def __init__(self):
        self.tokens: List[str] = []
        self.tags: List[str] = []
        self.space_after: List[bool] = []
        self.text: Optional[str] = None
        self.sent_id: Optional[str] = None
        self.newdoc_id: Optional[str] = None


class CoNLLImporter(BaseTextImporter):
    format_name = "conll"
    description = ("CoNLL-2003 column format and CoNLL-U "
                   "(NER read from the tag column or from MISC NER=)")
    file_extensions = [".conll", ".conllu", ".iob", ".iob2", ".bio", ".txt"]

    # ------------------------------------------------------------------ detect

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file():
            return False
        if path.suffix.lower() not in {".conll", ".conllu", ".iob", ".iob2",
                                       ".bio", ".txt", ".tsv"}:
            return False
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:8192]
        except OSError:
            return False
        return self._looks_like_conll(head)

    @staticmethod
    def _looks_like_conll(head: str) -> bool:
        """
        A .txt file is only CoNLL if its lines really are token columns.

        The extension list has to include ``.txt`` -- plenty of CoNLL corpora
        ship as ``eng.train`` or ``train.txt`` -- which means the content check
        is the only thing standing between a plain prose file and a very
        confusing import.
        """
        if DOCSTART in head:
            return True
        rows = 0
        for line in head.splitlines():
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split("\t") if "\t" in line else line.split()
            if len(fields) < 2:
                return False
            rows += 1
            if rows >= 5:
                return True
        return False

    # ------------------------------------------------------------------- parse

    def parse_path(self, path: Path,
                   options: Optional[dict] = None) -> TextImportResult:
        options = options or {}
        path = Path(path)
        if not path.is_file():
            raise ValueError(f"{path} is not a file")

        text = path.read_text(encoding="utf-8")
        sentences = self._read_sentences(text)
        if not sentences:
            raise ValueError(f"{path} contains no token rows")

        result = TextImportResult()
        grouped = self._group_into_documents(sentences, path.stem, options)

        seen_labels: Dict[str, None] = {}
        for doc_id, block in grouped:
            document = self._build_document(doc_id, block, result.warnings)
            if document is None:
                continue
            for span in document.spans:
                seen_labels.setdefault(span.label, None)
            result.documents.append(document)

        result.labels = [{"name": name} for name in seen_labels]
        result.verify()
        result.summarize(num_sentences=len(sentences))
        return result

    # -------------------------------------------------------------- internals

    @staticmethod
    def _read_sentences(text: str) -> List[_Sentence]:
        sentences: List[_Sentence] = []
        current = _Sentence()
        pending_newdoc: Optional[str] = None

        def flush() -> None:
            nonlocal current, pending_newdoc
            if current.tokens:
                if pending_newdoc is not None:
                    current.newdoc_id = pending_newdoc
                    pending_newdoc = None
                sentences.append(current)
            current = _Sentence()

        for raw_line in text.splitlines():
            line = raw_line.rstrip("\r\n")
            if not line.strip():
                flush()
                continue

            if line.startswith("#"):
                comment = line.lstrip("#").strip()
                key, sep, value = comment.partition("=")
                if not sep:
                    continue
                key, value = key.strip(), value.strip()
                if key == "text":
                    current.text = value
                elif key == "sent_id":
                    current.sent_id = value
                elif key in ("newdoc id", "newdoc"):
                    # UD writes the marker BEFORE the sentence it opens, so it
                    # has to survive until that sentence is flushed.
                    pending_newdoc = value or "doc"
                continue

            fields = line.split("\t") if "\t" in line else line.split()
            if fields[0] == DOCSTART:
                flush()
                pending_newdoc = DOCSTART
                continue

            token, tag, space_after = CoNLLImporter._read_row(fields)
            if token is None:
                continue
            current.tokens.append(token)
            current.tags.append(tag)
            current.space_after.append(space_after)

        flush()
        return sentences

    @staticmethod
    def _read_row(fields: List[str]) -> Tuple[Optional[str], str, bool]:
        """
        Pull (token, tag, space_after) out of one row of either dialect.

        CoNLL-U puts the NER tag in MISC as ``NER=B-PER`` and CoNLL-2003 puts
        it in the last column, so which field carries the label depends on
        which format this is -- decided per row by column count rather than
        per file, because concatenated corpora are common and one stray
        malformed row should not reinterpret the rest.
        """
        # CoNLL-U: 10 columns whose first is the token index.
        if len(fields) >= 10 and re.fullmatch(r"\d+(?:[-.]\d+)?", fields[0]):
            if "-" in fields[0] or "." in fields[0]:
                # Multiword-token ranges and empty nodes are not real tokens;
                # including them double-counts the surface string.
                return None, "O", True
            misc = fields[9]
            tag = "O"
            space_after = True
            for feature in misc.split("|"):
                name, _, value = feature.partition("=")
                if name == "NER":
                    tag = value or "O"
                elif name == "SpaceAfter" and value == "No":
                    space_after = False
            return fields[1], tag, space_after

        # CoNLL-2003 and friends: token first, tag last.
        if len(fields) < 2:
            return None, "O", True
        return fields[0], fields[-1], True

    @staticmethod
    def _group_into_documents(sentences: List[_Sentence], stem: str,
                              options: dict) -> List[Tuple[str, List[_Sentence]]]:
        """
        Decide what counts as one annotation item.

        A CoNLL file says almost nothing about this, and the answer changes the
        project: one item per sentence gives an annotator short units, one item
        per document gives them context. The markers are used when the file has
        them, and per-sentence is the fallback because that is the unit most
        NER corpora are actually distributed in.
        """
        mode = options.get("conll_document_unit", "auto")

        if mode == "file":
            return [(stem, list(sentences))]
        if mode == "sentence":
            return [(s.sent_id or f"{stem}-s{i + 1}", [s])
                    for i, s in enumerate(sentences)]

        # auto ------------------------------------------------------------
        if any(s.newdoc_id for s in sentences):
            groups: List[Tuple[str, List[_Sentence]]] = []
            counter = 0
            for sentence in sentences:
                if sentence.newdoc_id or not groups:
                    counter += 1
                    name = sentence.newdoc_id
                    if not name or name == DOCSTART:
                        name = f"{stem}-d{counter}"
                    groups.append((name, []))
                groups[-1][1].append(sentence)
            return groups

        # Our own CoNLL-U exporter writes `<instance_id>-s<n>`. Recovering the
        # instance id from it is what makes export -> import land back on the
        # same ids instead of on synthetic ones.
        doc_ids = [SENT_ID_DOC.match(s.sent_id or "") for s in sentences]
        if all(doc_ids) and any(doc_ids):
            groups = []
            for sentence, match in zip(sentences, doc_ids):
                doc = match.group("doc")
                if not groups or groups[-1][0] != doc:
                    groups.append((doc, []))
                groups[-1][1].append(sentence)
            return groups

        return [(s.sent_id or f"{stem}-s{i + 1}", [s])
                for i, s in enumerate(sentences)]

    @staticmethod
    def _build_document(doc_id: str, sentences: List[_Sentence],
                        warnings: List[str]) -> Optional[ImportedDocument]:
        pieces: List[str] = []
        tokens: List[str] = []
        offsets: List[Tuple[int, int]] = []
        tags: List[str] = []
        cursor = 0

        for sentence in sentences:
            if not sentence.tokens:
                continue
            if pieces:
                pieces.append(" ")
                cursor += 1

            if sentence.text:
                # The file gave us the real string; find the tokens in it so
                # the offsets are the originals rather than a reconstruction.
                located = _locate_tokens(sentence.tokens, sentence.text)
                if any(start < 0 for start, _ in located):
                    warnings.append(
                        f"{doc_id}: '# text =' does not contain every token, "
                        f"so offsets were rebuilt from the tokens instead")
                    rendered, located = CoNLLImporter._render(sentence)
                else:
                    rendered = sentence.text
            else:
                rendered, located = CoNLLImporter._render(sentence)

            pieces.append(rendered)
            for token, (start, end) in zip(sentence.tokens, located):
                tokens.append(token)
                offsets.append((cursor + start, cursor + end)
                               if start >= 0 else (-1, -1))
            tags.extend(sentence.tags)
            cursor += len(rendered)

        if not tokens:
            return None

        text = "".join(pieces)
        spans: List[ImportedSpan] = []
        for first, last, label in bio_tags_to_spans(tags):
            start = offsets[first][0]
            end = offsets[last][1]
            if start < 0 or end < 0:
                warnings.append(
                    f"{doc_id}: dropped a {label} span whose tokens could not "
                    f"be located in the text")
                continue
            spans.append(ImportedSpan(start=start, end=end, label=label,
                                      text=text[start:end]))

        return ImportedDocument(instance_id=doc_id, text=text, spans=spans)

    @staticmethod
    def _render(sentence: _Sentence) -> Tuple[str, List[Tuple[int, int]]]:
        """Rebuild a sentence from its tokens, honouring ``SpaceAfter=No``."""
        parts: List[str] = []
        located: List[Tuple[int, int]] = []
        cursor = 0
        for i, token in enumerate(sentence.tokens):
            located.append((cursor, cursor + len(token)))
            parts.append(token)
            cursor += len(token)
            joins = sentence.space_after[i] if i < len(sentence.space_after) else True
            if joins and i < len(sentence.tokens) - 1:
                parts.append(" ")
                cursor += 1
        return "".join(parts), located
