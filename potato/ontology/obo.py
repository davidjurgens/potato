"""
A small reader for OBO 1.4 flat files, and term search over what it reads.

Only what ontology-backed labels need is read:

* header: ``data-version``, ``ontology``, ``default-namespace``, ``date``
* ``[Term]`` stanzas: ``id``, ``name``, ``namespace``, ``synonym``, ``def``,
  ``is_a``, ``alt_id``, ``is_obsolete``

Other stanzas (``[Typedef]``, ``[Instance]``) and other tags are skipped.
``relationship:`` and ``intersection_of:`` lines are not edges here, so a
subtree (``root``) follows ``is_a`` only.

Obsolete terms are kept out of search and subtrees, but their ids are
remembered so a lookup can say "obsolete" rather than "unknown".

The format reference is the OBO 1.4 guide
(https://owlcollab.github.io/oboformat/doc/obo-syntax.html).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

OBO_PURL = "http://purl.obolibrary.org/obo/"

#: Default refusal size for an OBO file. CL and GO are about 30-40 MB; the
#: full NCBITaxon file is several hundred, which is better served from OLS4.
DEFAULT_MAX_FILE_MB = 300

_ESCAPES = {"n": "\n", "t": "\t", "W": " "}


class OboError(ValueError):
    """The file could not be read as OBO."""


@dataclass
class OboTerm:
    id: str
    name: str = ""
    namespace: str = ""
    definition: str = ""
    synonyms: List[Tuple[str, str]] = field(default_factory=list)  # (text, scope)
    is_a: List[str] = field(default_factory=list)
    alt_ids: List[str] = field(default_factory=list)
    obsolete: bool = False


def term_iri(obo_id: str) -> str:
    """The OBO PURL for a prefixed id: ``CL:0000236`` -> ``.../obo/CL_0000236``."""
    if obo_id.startswith(("http://", "https://")):
        return obo_id
    prefix, sep, local = obo_id.partition(":")
    if not sep:
        return OBO_PURL + obo_id
    return f"{OBO_PURL}{prefix}_{local}"


def _unescape(text: str) -> str:
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_trailing(value: str) -> str:
    """Drop an unquoted, unescaped ``! comment`` and a trailing ``{qualifiers}``."""
    in_quote = False
    i = 0
    cut = len(value)
    while i < len(value):
        ch = value[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            in_quote = not in_quote
        elif ch == "!" and not in_quote:
            cut = i
            break
        i += 1
    value = value[:cut].rstrip()
    if value.endswith("}"):
        depth_start = _trailing_brace_start(value)
        if depth_start is not None:
            value = value[:depth_start].rstrip()
    return value


def _trailing_brace_start(value: str) -> Optional[int]:
    in_quote = False
    start = None
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            in_quote = not in_quote
        elif ch == "{" and not in_quote:
            start = i
        i += 1
    return start


def _quoted(value: str) -> Tuple[str, str]:
    """Split ``"text" rest`` into (unescaped text, rest). No quote: ('', value)."""
    value = value.lstrip()
    if not value.startswith('"'):
        return "", value
    i = 1
    while i < len(value):
        ch = value[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            return _unescape(value[1:i]), value[i + 1:].strip()
        i += 1
    return _unescape(value[1:]), ""


_SCOPES = ("EXACT", "BROAD", "NARROW", "RELATED")


class Ontology:
    """The terms of one OBO file, indexed for lookup, subtrees and search."""

    def __init__(self, terms: Dict[str, OboTerm], header: Dict[str, str],
                 obsolete_ids: Set[str], alt_ids: Dict[str, str], sha256: str = ""):
        self.terms = terms
        self.header = header
        self.obsolete_ids = obsolete_ids
        self.alt_ids = alt_ids
        self.sha256 = sha256
        self.children: Dict[str, List[str]] = {}
        for term in terms.values():
            for parent in term.is_a:
                self.children.setdefault(parent, []).append(term.id)
        # Casefolded search keys, built once.
        self._index = []
        for term in terms.values():
            label = term.name.casefold()
            syns = [(s.casefold(), s) for s, _scope in term.synonyms]
            self._index.append((term, label, _words(label), [(k, o, _words(k)) for k, o in syns]))

    # -- identity ---------------------------------------------------------

    @property
    def version(self) -> str:
        """``data-version`` from the header, else ``sha256:<12 hex>`` of the file."""
        dv = (self.header.get("data-version") or "").strip()
        if dv:
            return dv
        return f"sha256:{self.sha256[:12]}" if self.sha256 else ""

    @property
    def name(self) -> str:
        return (self.header.get("ontology") or "").strip()

    def resolve_id(self, obo_id: str) -> Optional[str]:
        """The primary id for ``obo_id`` (follows ``alt_id``), or None."""
        if obo_id in self.terms:
            return obo_id
        return self.alt_ids.get(obo_id)

    def get(self, obo_id: str) -> Optional[OboTerm]:
        primary = self.resolve_id(obo_id)
        return self.terms.get(primary) if primary else None

    def record(self, term: OboTerm) -> Dict[str, str]:
        return {
            "obo_id": term.id,
            "label": term.name,
            "iri": term_iri(term.id),
            "ontology_version": self.version,
        }

    # -- structure --------------------------------------------------------

    def descendants(self, root: str, include_root: bool = True) -> Set[str]:
        """``root`` and every non-obsolete term below it by ``is_a``."""
        seen: Set[str] = set()
        stack = [root]
        while stack:
            node = stack.pop()
            for child in self.children.get(node, ()):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        if include_root and root in self.terms:
            seen.add(root)
        return seen

    # -- search -----------------------------------------------------------

    def search(self, query: str, limit: int = 20,
               allowed: Optional[Set[str]] = None) -> Tuple[List[Tuple[OboTerm, Optional[str]]], int]:
        """Terms matching ``query``, best first, and the total match count.

        Each hit is ``(term, synonym)``; ``synonym`` is the synonym that matched
        when the label did not. Ranking: id, exact label, label prefix, word
        prefixes in the label, then the same for synonyms, then substrings.
        """
        q = " ".join((query or "").split()).casefold()
        if not q:
            return [], 0
        tokens = q.split(" ")
        id_hit = self._id_query(query.strip())
        scored = []
        for term, label, words, syns in self._index:
            if allowed is not None and term.id not in allowed:
                continue
            if id_hit and term.id == id_hit:
                scored.append((0, term, None))
                continue
            rank = _rank(q, tokens, label, words)
            hit_syn = None
            if rank is None or rank > 2:
                for key, original, swords in syns:
                    srank = _rank(q, tokens, key, swords)
                    if srank is not None:
                        srank += 3
                        if rank is None or srank < rank:
                            rank, hit_syn = srank, original
                        if srank == 3:
                            break
            if rank is not None:
                # Substring label matches rank below every synonym match.
                scored.append((rank, term, hit_syn))
        scored.sort(key=lambda s: (s[0], len(s[1].name), s[1].name.casefold(), s[1].id))
        return [(t, syn) for _r, t, syn in scored[:max(0, limit)]], len(scored)

    def _id_query(self, raw: str) -> Optional[str]:
        """A query that names a term id (``CL:0000236``, ``CL_0000236``)."""
        cand = raw.strip()
        if not cand or " " in cand:
            return None
        if cand.startswith(OBO_PURL):
            cand = cand[len(OBO_PURL):]
        variants = {cand, cand.upper()}
        if "_" in cand and ":" not in cand:
            p, _, l = cand.partition("_")
            variants |= {f"{p}:{l}", f"{p.upper()}:{l}"}
        for v in variants:
            primary = self.resolve_id(v)
            if primary:
                return primary
        return None


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"[^\w]+", text) if w]


def _rank(q: str, tokens: List[str], text: str, words: List[str]) -> Optional[int]:
    if text == q:
        return 0
    if text.startswith(q):
        return 1
    if all(any(w.startswith(t) for w in words) for t in tokens if t):
        return 2
    if q in text:
        return 7
    return None


def parse_obo_text(text: str, sha256: str = "") -> Ontology:
    header: Dict[str, str] = {}
    terms: Dict[str, OboTerm] = {}
    obsolete: Set[str] = set()
    alt: Dict[str, str] = {}
    stanza: Optional[str] = None
    current: Optional[OboTerm] = None
    saw_stanza = False

    def finish():
        if current is None or not current.id:
            return
        if current.obsolete:
            obsolete.add(current.id)
            return
        if not current.namespace:
            current.namespace = header.get("default-namespace", "")
        terms[current.id] = current
        for a in current.alt_ids:
            alt.setdefault(a, current.id)

    pending = ""
    for raw_line in text.splitlines():
        line = pending + raw_line
        pending = ""
        # OBO allows a trailing backslash to continue a line.
        if line.endswith("\\") and not line.endswith("\\\\"):
            pending = line[:-1]
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            finish()
            current = None
            saw_stanza = True
            stanza = stripped[1:-1].strip()
            if stanza == "Term":
                current = OboTerm(id="")
            continue
        tag, sep, value = stripped.partition(":")
        if not sep:
            continue
        tag = tag.strip()
        value = value.strip()
        if not saw_stanza:
            header.setdefault(tag, _strip_trailing(value))
            continue
        if current is None:
            continue
        if tag == "id":
            current.id = _strip_trailing(value)
        elif tag == "name":
            current.name = _unescape(_strip_trailing(value))
        elif tag == "namespace":
            current.namespace = _strip_trailing(value)
        elif tag == "def":
            current.definition, _rest = _quoted(value)
        elif tag == "synonym":
            text_, rest = _quoted(value)
            scope = rest.split(" ", 1)[0].upper() if rest else "RELATED"
            if text_:
                current.synonyms.append((text_, scope if scope in _SCOPES else "RELATED"))
        elif tag in ("exact_synonym", "narrow_synonym", "broad_synonym", "related_synonym"):
            # OBO 1.0 spellings, still found in old files.
            text_, _rest = _quoted(value)
            if text_:
                current.synonyms.append((text_, tag.split("_")[0].upper()))
        elif tag == "is_a":
            parent = _strip_trailing(value).split(" ")[0]
            if parent:
                current.is_a.append(parent)
        elif tag == "alt_id":
            current.alt_ids.append(_strip_trailing(value))
        elif tag == "is_obsolete":
            current.obsolete = _strip_trailing(value).lower() == "true"
    finish()
    return Ontology(terms, header, obsolete, alt, sha256=sha256)


def load_obo_file(path: str, max_mb: float = DEFAULT_MAX_FILE_MB) -> Ontology:
    """Read and index an OBO file. Raises OboError with a readable reason."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise OboError(f"cannot read {path}: {e.strerror or e}") from None
    if size > max_mb * 1024 * 1024:
        raise OboError(
            f"{path} is {size / (1024 * 1024):.0f} MB, over the {max_mb:g} MB limit "
            f"(label_source.max_file_mb). Use a subset or slim of the ontology, or "
            f"raise the limit.")
    with open(path, "rb") as fh:
        data = fh.read()
    digest = hashlib.sha256(data).hexdigest()
    text = data.decode("utf-8", errors="replace")
    head = text.lstrip()[:400]
    if head.startswith("<?xml") or head.startswith("<rdf:RDF") or "owl:Ontology" in head:
        raise OboError(
            f"{path} looks like OWL/RDF-XML, not OBO. Convert it with ROBOT "
            f"(`robot convert --input file.owl --output file.obo`) or download the "
            f".obo release of the ontology.")
    onto = parse_obo_text(text, sha256=digest)
    if not onto.terms:
        raise OboError(f"{path} has no [Term] stanzas with an id; is it an OBO file?")
    return onto
