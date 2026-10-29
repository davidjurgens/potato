"""
``label_source``: where an ontology-backed scheme gets its terms.

A scheme (radio, multiselect, span, image_annotation) may carry::

    label_source:
      ontology: cl                 # short name; for OLS4 the ontology id
      service: file                # file | ols4
      file: ontologies/cl.obo      # service: file -- OBO 1.4, inside task_dir
      root: CL:0000000             # optional: only this term and its is_a descendants
      max_results: 20              # results per search, 1-100

    # OLS4 also needs an explicit opt-in, because the search text goes to a
    # third-party server:
      service: ols4
      allow_network: true
      base_url: https://www.ebi.ac.uk/ols4/api   # optional, for a self-hosted OLS4
      timeout_s: 5

The picked term is stored as ``{obo_id, label, iri, ontology_version}``.

This module holds the config checks (called from ``config_module``), the two
sources, and their caches. Nothing here imports Flask, and ``requests`` is only
imported inside the OLS4 calls.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .obo import DEFAULT_MAX_FILE_MB, Ontology, OboError, load_obo_file, term_iri

logger = logging.getLogger(__name__)

SERVICES = ("file", "ols4")
SUPPORTED_TYPES = ("radio", "multiselect", "span", "image_annotation")
DEFAULT_OLS4_BASE_URL = "https://www.ebi.ac.uk/ols4/api"
DEFAULT_MAX_RESULTS = 20
MAX_MAX_RESULTS = 100
DEFAULT_TIMEOUT_S = 5.0
MIN_QUERY_LENGTH = 2

#: Every key ``label_source`` accepts, with the services it applies to.
LABEL_SOURCE_KEYS = {
    "ontology": SERVICES,
    "service": SERVICES,
    "file": ("file",),
    "max_file_mb": ("file",),
    "root": SERVICES,
    "max_results": SERVICES,
    "allow_network": ("ols4",),
    "base_url": ("ols4",),
    "timeout_s": ("ols4",),
}

_CURIE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*:[A-Za-z0-9_.\-]+$")
CURIE_RE = _CURIE
_ONTOLOGY_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*$")

#: The four keys of a stored term, in the order they are written.
TERM_KEYS = ("obo_id", "label", "iri", "ontology_version")


class LabelSourceError(ValueError):
    """A ``label_source`` block that cannot be used. The message names the key."""


class OntologyServiceError(RuntimeError):
    """A remote lookup failed (timeout, HTTP error, unreadable reply)."""


# ---------------------------------------------------------------------------
# Config checks
# ---------------------------------------------------------------------------

def check_label_source(scheme: Dict[str, Any], path: str) -> None:
    """Structural check of ``scheme['label_source']``. Raises LabelSourceError.

    File existence and the ``root`` lookup need the task directory and are in
    :func:`check_label_source_file`.
    """
    ls = scheme.get("label_source")
    where = f"{path}.label_source"
    atype = scheme.get("annotation_type")
    if atype not in SUPPORTED_TYPES:
        raise LabelSourceError(
            f"{where}: label_source applies to {', '.join(SUPPORTED_TYPES)} schemes, "
            f"not '{atype}'")
    if not isinstance(ls, dict):
        raise LabelSourceError(
            f"{where} must be a mapping such as "
            f"{{ontology: cl, service: file, file: ontologies/cl.obo}}")
    unknown = sorted(set(ls) - set(LABEL_SOURCE_KEYS))
    if unknown:
        raise LabelSourceError(
            f"{where} has unknown key(s) {unknown}. Allowed: {sorted(LABEL_SOURCE_KEYS)}")
    service = ls.get("service")
    if service not in SERVICES:
        raise LabelSourceError(
            f"{where}.service must be one of {list(SERVICES)}, got {service!r}")
    for key in ls:
        if service not in LABEL_SOURCE_KEYS[key]:
            raise LabelSourceError(
                f"{where}.{key} applies to service {'/'.join(LABEL_SOURCE_KEYS[key])}, "
                f"not '{service}'")
    onto = ls.get("ontology")
    if not isinstance(onto, str) or not _ONTOLOGY_ID.match(onto.strip()):
        raise LabelSourceError(
            f"{where}.ontology must be a short ontology name such as 'cl' or 'go', "
            f"got {onto!r}")
    if "max_results" in ls:
        mr = ls["max_results"]
        if isinstance(mr, bool) or not isinstance(mr, int) or not 1 <= mr <= MAX_MAX_RESULTS:
            raise LabelSourceError(
                f"{where}.max_results must be an integer from 1 to {MAX_MAX_RESULTS}, got {mr!r}")
    if "root" in ls:
        root = ls["root"]
        if not isinstance(root, str) or not _CURIE.match(root.strip()):
            raise LabelSourceError(
                f"{where}.root must be a term id such as 'CL:0000000', got {root!r}")

    if service == "file":
        f = ls.get("file")
        if not isinstance(f, str) or not f.strip():
            raise LabelSourceError(
                f"{where}.file is required for service: file (a path to an .obo file "
                f"inside task_dir)")
        if f.startswith(("http://", "https://")):
            raise LabelSourceError(
                f"{where}.file must be a local path; Potato does not download ontology "
                f"files. Save the .obo file inside task_dir.")
        if "max_file_mb" in ls:
            mb = ls["max_file_mb"]
            if isinstance(mb, bool) or not isinstance(mb, (int, float)) or mb <= 0:
                raise LabelSourceError(f"{where}.max_file_mb must be a positive number, got {mb!r}")
    else:  # ols4
        if ls.get("allow_network") is not True:
            raise LabelSourceError(
                f"{where}: service 'ols4' sends each search to an external server "
                f"({ls.get('base_url') or DEFAULT_OLS4_BASE_URL}). It is off unless the "
                f"scheme sets label_source.allow_network: true. For an offline study "
                f"use service: file with a local .obo file.")
        if "base_url" in ls:
            url = ls["base_url"]
            if not isinstance(url, str) or not re.match(r"^https?://[^\s/]+", url):
                raise LabelSourceError(
                    f"{where}.base_url must be an http(s) URL such as "
                    f"{DEFAULT_OLS4_BASE_URL}, got {url!r}")
        if "timeout_s" in ls:
            t = ls["timeout_s"]
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0.5 <= t <= 30:
                raise LabelSourceError(f"{where}.timeout_s must be a number from 0.5 to 30, got {t!r}")


def check_label_source_file(scheme: Dict[str, Any], path: str, resolved: str) -> None:
    """The file exists, parses as OBO, and contains ``root`` when one is set."""
    ls = scheme["label_source"]
    where = f"{path}.label_source"
    if not os.path.exists(resolved):
        raise LabelSourceError(
            f"{where}.file not found: {ls['file']} (resolved to {resolved})")
    if not os.path.isfile(resolved):
        raise LabelSourceError(f"{where}.file is not a file: {resolved}")
    try:
        onto = cached_ontology(resolved, ls.get("max_file_mb", DEFAULT_MAX_FILE_MB))
    except OboError as e:
        raise LabelSourceError(f"{where}.file: {e}") from None
    root = ls.get("root")
    if root:
        root = root.strip()
        if onto.get(root) is None:
            if root in onto.obsolete_ids:
                raise LabelSourceError(f"{where}.root {root} is marked obsolete in {ls['file']}")
            raise LabelSourceError(
                f"{where}.root {root} is not a term in {ls['file']} "
                f"({len(onto.terms)} terms read)")


def iter_label_source_schemes(config_data: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """(path, scheme) for every scheme with a ``label_source``, top level and phases."""
    if not isinstance(config_data, dict):
        return

    def from_list(schemes, prefix):
        for i, s in enumerate(schemes if isinstance(schemes, list) else []):
            if isinstance(s, dict) and "label_source" in s:
                yield f"{prefix}[{i}]", s

    yield from from_list(config_data.get("annotation_schemes"), "annotation_schemes")
    phases = config_data.get("phases")
    if isinstance(phases, list):
        for i, ph in enumerate(phases):
            if isinstance(ph, dict):
                yield from from_list(ph.get("annotation_schemes"),
                                     f"phases[{i}].annotation_schemes")
    elif isinstance(phases, dict):
        for name, ph in phases.items():
            if isinstance(ph, dict):
                yield from from_list(ph.get("annotation_schemes"),
                                     f"phases.{name}.annotation_schemes")


def find_scheme(config_data: Dict[str, Any], schema_name: str) -> Optional[Dict[str, Any]]:
    for _path, scheme in iter_label_source_schemes(config_data):
        if scheme.get("name") == schema_name:
            return scheme
    return None


# ---------------------------------------------------------------------------
# Term records
# ---------------------------------------------------------------------------

def normalize_record(value: Any) -> Optional[Dict[str, str]]:
    """A stored term as a dict with the four keys, or None.

    Accepts the JSON string the page stores or an already-decoded dict.
    """
    if isinstance(value, str):
        value = value.strip()
        if not value.startswith("{"):
            return None
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict) or not value.get("obo_id"):
        return None
    return {k: ("" if value.get(k) is None else str(value.get(k))) for k in TERM_KEYS}


def encode_record(record: Dict[str, Any]) -> str:
    """The option value for a stored term, byte for byte what the picker's
    ``JSON.stringify`` writes, so a restored answer saves unchanged."""
    return json.dumps({k: "" if record.get(k) is None else str(record[k]) for k in TERM_KEYS},
                      ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

_ONTOLOGY_CACHE: Dict[Tuple[str, float, int, float], Ontology] = {}
_ONTOLOGY_LOCK = threading.Lock()


def cached_ontology(path: str, max_mb: float = DEFAULT_MAX_FILE_MB) -> Ontology:
    """Parse ``path`` once per (mtime, size); later calls reuse the index."""
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_mtime, st.st_size, float(max_mb))
    with _ONTOLOGY_LOCK:
        hit = _ONTOLOGY_CACHE.get(key)
    if hit is not None:
        return hit
    onto = load_obo_file(path, max_mb)
    with _ONTOLOGY_LOCK:
        # One entry per file: drop older parses of the same path.
        for k in [k for k in _ONTOLOGY_CACHE if k[0] == key[0]]:
            del _ONTOLOGY_CACHE[k]
        _ONTOLOGY_CACHE[key] = onto
    return onto


def resolve_file(label_source: Dict[str, Any], task_dir: str) -> str:
    """The absolute path of ``label_source.file``, refused outside ``task_dir``."""
    from potato.server_utils.config_module import validate_path_security
    return validate_path_security(label_source["file"], task_dir)


class FileSource:
    service = "file"

    def __init__(self, scheme: Dict[str, Any], task_dir: str):
        self.scheme = scheme
        self.ls = scheme["label_source"]
        self.path = resolve_file(self.ls, task_dir)
        self.max_results = int(self.ls.get("max_results", DEFAULT_MAX_RESULTS))
        self._allowed_key = None
        self._allowed = None

    @property
    def ontology(self) -> Ontology:
        return cached_ontology(self.path, self.ls.get("max_file_mb", DEFAULT_MAX_FILE_MB))

    def _allowed_ids(self, onto: Ontology):
        root = (self.ls.get("root") or "").strip()
        if not root:
            return None
        if self._allowed_key is not onto:
            self._allowed = onto.descendants(onto.resolve_id(root) or root)
            self._allowed_key = onto
        return self._allowed

    @property
    def version(self) -> str:
        return self.ontology.version

    def search(self, query: str) -> Dict[str, Any]:
        onto = self.ontology
        hits, total = onto.search(query, self.max_results, self._allowed_ids(onto))
        results = []
        for term, synonym in hits:
            row = onto.record(term)
            if synonym:
                row["synonym"] = synonym
            if term.definition:
                row["definition"] = _clip(term.definition)
            results.append(row)
        return {"results": results, "total": total, "version": onto.version}

    def get_term(self, obo_id: str) -> Optional[Dict[str, str]]:
        onto = self.ontology
        term = onto.get(obo_id)
        if term is None:
            return None
        allowed = self._allowed_ids(onto)
        if allowed is not None and term.id not in allowed:
            return None
        return onto.record(term)


class Ols4Source:
    """Searches an OLS4 server through Potato; the browser never calls it."""

    service = "ols4"
    _search_cache: "OrderedDict[tuple, Tuple[float, Dict[str, Any]]]" = OrderedDict()
    _version_cache: Dict[tuple, Tuple[float, str]] = {}
    _lock = threading.Lock()
    CACHE_SIZE = 512
    CACHE_TTL_S = 6 * 3600
    MAX_REPLY_BYTES = 4 * 1024 * 1024

    def __init__(self, scheme: Dict[str, Any], task_dir: str, ledger_dir: Optional[str] = None):
        self.scheme = scheme
        self.ls = scheme["label_source"]
        self.base_url = (self.ls.get("base_url") or DEFAULT_OLS4_BASE_URL).rstrip("/")
        self.ontology_id = self.ls["ontology"].strip().lower()
        self.max_results = int(self.ls.get("max_results", DEFAULT_MAX_RESULTS))
        self.timeout = float(self.ls.get("timeout_s", DEFAULT_TIMEOUT_S))
        self.root = (self.ls.get("root") or "").strip()
        self.ledger = TermLedger(ledger_dir, self.ontology_id) if ledger_dir else None

    # -- HTTP --

    def _get(self, url: str, params: Dict[str, Any]) -> Any:
        if self.ls.get("allow_network") is not True:  # defence in depth
            raise OntologyServiceError("OLS4 is not enabled for this scheme")
        import requests  # lazy: core dependency, but not needed at boot
        try:
            resp = requests.get(url, params=params, timeout=self.timeout,
                                headers={"Accept": "application/json",
                                         "User-Agent": "Potato-annotation (ontology labels)"})
        except requests.Timeout:
            raise OntologyServiceError(f"OLS4 did not answer within {self.timeout:g} s") from None
        except requests.RequestException as e:
            raise OntologyServiceError(f"OLS4 request failed: {type(e).__name__}") from None
        if resp.status_code != 200:
            raise OntologyServiceError(f"OLS4 answered HTTP {resp.status_code}")
        if len(resp.content or b"") > self.MAX_REPLY_BYTES:
            raise OntologyServiceError("OLS4 reply was too large")
        try:
            return resp.json()
        except ValueError:
            raise OntologyServiceError("OLS4 reply was not JSON") from None

    @property
    def version(self) -> str:
        key = (self.base_url, self.ontology_id)
        now = time.time()
        with self._lock:
            hit = self._version_cache.get(key)
        if hit and now - hit[0] < self.CACHE_TTL_S:
            return hit[1]
        version = ""
        try:
            data = self._get(f"{self.base_url}/ontologies/{self.ontology_id}", {})
            version = _ols_version(data)
        except OntologyServiceError as e:
            logger.warning("Could not read the OLS4 version of %s: %s", self.ontology_id, e)
            if hit:
                return hit[1]
        with self._lock:
            self._version_cache[key] = (now, version)
        return version

    def search(self, query: str) -> Dict[str, Any]:
        q = " ".join((query or "").split())
        key = (self.base_url, self.ontology_id, self.root, q.casefold(), self.max_results)
        now = time.time()
        with self._lock:
            hit = self._search_cache.get(key)
            if hit and now - hit[0] < self.CACHE_TTL_S:
                self._search_cache.move_to_end(key)
                return hit[1]
        params = {
            "q": q,
            "ontology": self.ontology_id,
            "rows": self.max_results,
            "obsoletes": "false",
            "fieldList": "iri,label,obo_id,short_form,ontology_name,synonym,description",
        }
        if self.root:
            params["childrenOf"] = term_iri(self.root)
        data = self._get(f"{self.base_url}/search", params)
        response = (data or {}).get("response") or {}
        docs = response.get("docs") or []
        version = self.version
        results = []
        for doc in docs[: self.max_results]:
            row = _ols_doc_record(doc, version)
            if row is None:
                continue
            if doc.get("ontology_name") and str(doc["ontology_name"]).lower() != self.ontology_id:
                continue
            desc = doc.get("description")
            if isinstance(desc, list) and desc:
                row["definition"] = _clip(str(desc[0]))
            results.append(row)
        try:
            total = int(response.get("numFound", len(results)))
        except (TypeError, ValueError):
            total = len(results)
        payload = {"results": results, "total": max(total, len(results)), "version": version}
        with self._lock:
            self._search_cache[key] = (now, payload)
            while len(self._search_cache) > self.CACHE_SIZE:
                self._search_cache.popitem(last=False)
        if self.ledger is not None:
            self.ledger.add([{k: r[k] for k in TERM_KEYS} for r in results])
        return payload

    def get_term(self, obo_id: str) -> Optional[Dict[str, str]]:
        if self.ledger is not None:
            hit = self.ledger.get(obo_id)
            if hit:
                return hit
        return None

    @classmethod
    def clear_caches(cls) -> None:
        with cls._lock:
            cls._search_cache.clear()
            cls._version_cache.clear()


def _ols_version(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    cfg = data.get("config") if isinstance(data.get("config"), dict) else {}
    for value in (cfg.get("version"), data.get("version"), cfg.get("versionIri"),
                  data.get("versionIri"), data.get("updated")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _ols_doc_record(doc: Any, version: str) -> Optional[Dict[str, str]]:
    if not isinstance(doc, dict):
        return None
    obo_id = doc.get("obo_id")
    if not obo_id and isinstance(doc.get("short_form"), str) and "_" in doc["short_form"]:
        p, _, l = doc["short_form"].partition("_")
        obo_id = f"{p}:{l}"
    label = doc.get("label")
    if isinstance(label, list):
        label = label[0] if label else ""
    if not obo_id or not label:
        return None
    return {
        "obo_id": str(obo_id),
        "label": str(label),
        "iri": str(doc.get("iri") or term_iri(str(obo_id))),
        "ontology_version": version,
    }


def _clip(text: str, n: int = 240) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


class TermLedger:
    """Terms an OLS4 source has returned, kept on disk under the output directory.

    Spans and image shapes store only the term id, so export and the image
    label palette look the rest of the record up here. A file source does not
    need one: its terms are in the .obo file.
    """

    def __init__(self, directory: str, ontology_id: str):
        self.path = os.path.join(directory, f"{ontology_id}-ols4-terms.json")
        self._lock = threading.Lock()
        self._terms: Optional[Dict[str, Dict[str, str]]] = None

    def _load(self) -> Dict[str, Dict[str, str]]:
        if self._terms is None:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self._terms = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._terms = {}
        return self._terms

    def get(self, obo_id: str) -> Optional[Dict[str, str]]:
        with self._lock:
            return self._load().get(obo_id)

    def add(self, records: List[Dict[str, str]]) -> None:
        with self._lock:
            terms = self._load()
            changed = False
            for r in records:
                if terms.get(r["obo_id"]) != r:
                    terms[r["obo_id"]] = r
                    changed = True
            if not changed:
                return
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(terms, fh, ensure_ascii=False, indent=0, sort_keys=True)
                os.replace(tmp, self.path)
            except OSError as e:
                logger.warning("Could not write the ontology term ledger %s: %s", self.path, e)


def ledger_dir(config_data: Dict[str, Any]) -> Optional[str]:
    task_dir = config_data.get("task_dir") or os.getcwd()
    out = config_data.get("output_annotation_dir")
    if not out or out in ("null", "default"):
        return None
    out = out if os.path.isabs(out) else os.path.join(task_dir, out)
    return os.path.join(out, "ontology_cache")


_SOURCES: Dict[tuple, Any] = {}
_SOURCES_LOCK = threading.Lock()


def source_for_scheme(scheme: Dict[str, Any], config_data: Dict[str, Any]):
    """The (cached) FileSource or Ols4Source for a scheme with ``label_source``."""
    ls = scheme.get("label_source") or {}
    task_dir = config_data.get("task_dir") or os.getcwd()
    key = (scheme.get("name"), json.dumps(ls, sort_keys=True, default=str), task_dir,
           ledger_dir(config_data))
    with _SOURCES_LOCK:
        src = _SOURCES.get(key)
    if src is not None:
        return src
    if ls.get("service") == "ols4":
        src = Ols4Source(scheme, task_dir, ledger_dir(config_data))
    else:
        src = FileSource(scheme, task_dir)
    with _SOURCES_LOCK:
        _SOURCES[key] = src
    return src


def clear_source_caches() -> None:
    """For tests: forget parsed files, sources and OLS4 replies."""
    with _SOURCES_LOCK:
        _SOURCES.clear()
    with _ONTOLOGY_LOCK:
        _ONTOLOGY_CACHE.clear()
    Ols4Source.clear_caches()
