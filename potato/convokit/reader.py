"""
Reading a ConvoKit corpus off disk, with no ``convokit`` dependency.

A ConvoKit corpus is a directory of JSON:

.. code-block:: text

    corpus_dir/
        utterances.jsonl     one JSON object per line
        speakers.json        {speaker_id: meta}          (legacy: users.json)
        conversations.json   {conversation_id: meta}
        corpus.json          corpus-level meta
        index.json           metadata field -> type strings
        <field>-bin.p        pickled metadata values (optional)
        info.<field>.jsonl   metadata overlays (optional)

Reading it directly rather than importing ``convokit`` is deliberate: the pip
package pulls in spacy, torch, scikit-learn, and pymongo, and Potato's boot path
deliberately stays clear of the ML stack. The format is small and stable, so this
module reads it with the standard library alone — the same approach
:mod:`potato.server_utils.transcripts` takes for 21 transcript formats.

Format variation this module absorbs
------------------------------------

* **Legacy key names.** Older corpora use ``user`` instead of ``speaker`` and
  ``root`` instead of ``conversation_id``, and store speakers in ``users.json``.
  Detection follows upstream exactly: look at the *first* utterance and pick
  ``"speaker" if "speaker" in first else "user"``.
* **``reply-to`` vs ``reply_to``.** The dump code writes the hyphenated form;
  the load code prefers the underscored one ("temp fix for reddit"). Both appear
  in real corpora, so both are accepted, underscore first.
* **Wrapped vs bare metadata.** ``speakers.json`` values may be
  ``{"meta": {...}, "vectors": [...]}`` or the metadata dict itself.
* **Binary metadata.** A value like ``"<##bin{3}&&@**>"`` is an index into a
  pickled list in a ``-bin.p`` sidecar. These are **skipped by default** —
  unpickling data downloaded from the internet executes arbitrary code, and the
  fields in question are almost always spacy parses or embeddings that no
  annotation task needs. ``load_binary_meta=True`` opts in.
* **Giant derived fields.** ``parsed`` (spacy dependency parses) runs to hundreds
  of lines *per utterance*. It is dropped during the streaming parse by default.

What is deliberately lossy
--------------------------

Vectors (``vect_info.*.npy``) are never read, and skipped binary fields come back
as ``None``. Both are recorded on the returned :class:`Corpus` so callers can say
so out loud rather than quietly implying a faithful copy.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

from .schema import CorpusIndex

logger = logging.getLogger(__name__)

__all__ = [
    "BIN_DELIM_L",
    "BIN_DELIM_R",
    "DEFAULT_DROPPED_META",
    "Conversation",
    "Corpus",
    "ConvoKitReadError",
    "Utterance",
    "iter_utterance_lines",
    "read_corpus",
    "resolve_corpus_dir",
]


class ConvoKitReadError(Exception):
    """Raised when a corpus cannot be read at all."""


#: Delimiters ConvoKit wraps around a pickle index when a metadata value lives in
#: a ``-bin.p`` sidecar. Verbatim from ``convokit/model/corpus_helpers.py``.
BIN_DELIM_L, BIN_DELIM_R = "<##bin{", "}&&@**>"

#: Metadata fields dropped unless explicitly kept. ``parsed`` is spacy dependency
#: parses (enormous, and useless for annotation); the other two are vector
#: bookkeeping that has no inline value.
DEFAULT_DROPPED_META = frozenset({"parsed", "vectors", "embeddings"})

#: Cap on a ``-bin.p`` sidecar we are willing to unpickle, even with the opt-in.
MAX_BIN_FILE_BYTES = 256 * 1024 * 1024

#: Cap on the uncompressed size of a corpus zip (zip-bomb guard).
MAX_ZIP_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024

#: Object types a ``info.<field>.jsonl`` overlay may target, in resolution order.
_INFO_RESOLUTION_ORDER = ("utterance", "conversation", "speaker")


@dataclass
class Utterance:
    """One utterance. Mirrors ConvoKit's object model, not its API."""

    id: str
    conversation_id: str
    speaker: str
    text: str
    reply_to: Optional[str] = None
    timestamp: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    #: Position in ``utterances.jsonl``. The stable tie-break for ordering when
    #: timestamps are missing or duplicated — never sort these by id, since ids
    #: like ``146743638.12667.12652`` do not sort meaningfully as strings.
    file_index: int = 0


@dataclass
class Conversation:
    """One conversation: an id, its metadata, and its utterances in file order."""

    id: str
    meta: Dict[str, Any] = field(default_factory=dict)
    utterance_ids: List[str] = field(default_factory=list)


@dataclass
class Corpus:
    """A whole corpus, plus an honest account of what was dropped reading it."""

    name: str
    path: str
    utterances: Dict[str, Utterance] = field(default_factory=dict)
    conversations: Dict[str, Conversation] = field(default_factory=dict)
    speakers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    index: CorpusIndex = field(default_factory=CorpusIndex.empty)
    version: Optional[int] = None
    #: True when the corpus uses ``user``/``root``/``users.json``.
    legacy: bool = False
    warnings: List[str] = field(default_factory=list)
    #: Fields present in the corpus but not loaded because they are pickled.
    skipped_binary_fields: List[str] = field(default_factory=list)
    #: Fields dropped by ``drop_meta`` (``parsed`` and friends).
    dropped_meta_fields: List[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.utterances)

    def iter_conversations(self) -> Iterator[Conversation]:
        return iter(self.conversations.values())

    def utterances_of(self, conversation_id: str) -> List[Utterance]:
        convo = self.conversations.get(conversation_id)
        if convo is None:
            return []
        return [self.utterances[uid] for uid in convo.utterance_ids if uid in self.utterances]

    def warn(self, message: str) -> None:
        """Record a warning once. Duplicates are common (per-utterance issues)."""
        if message not in self.warnings:
            self.warnings.append(message)
            logger.warning("%s", message)


# --------------------------------------------------------------------------- #
# Locating the corpus directory
# --------------------------------------------------------------------------- #

def _is_corpus_dir(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "utterances.jsonl")) or os.path.isfile(
        os.path.join(path, "utterances.json")
    )


def resolve_corpus_dir(source: str, *, extract_to: Optional[str] = None) -> str:
    """Return the directory holding ``utterances.jsonl`` for ``source``.

    Accepts a corpus directory, a directory containing exactly one corpus
    subdirectory (what ConvoKit's zips unpack to), or a ``.zip``.

    Zip extraction rejects absolute member paths, ``..`` components, and symlink
    entries, and refuses archives whose declared uncompressed size exceeds
    :data:`MAX_ZIP_UNCOMPRESSED_BYTES`.
    """
    source = os.path.expanduser(source)

    if os.path.isdir(source):
        if _is_corpus_dir(source):
            return source
        subdirs = [
            os.path.join(source, name)
            for name in sorted(os.listdir(source))
            if os.path.isdir(os.path.join(source, name)) and not name.startswith("__")
        ]
        corpus_subdirs = [d for d in subdirs if _is_corpus_dir(d)]
        if len(corpus_subdirs) == 1:
            return corpus_subdirs[0]
        if len(corpus_subdirs) > 1:
            raise ConvoKitReadError(
                f"'{source}' contains {len(corpus_subdirs)} corpus directories "
                f"({', '.join(os.path.basename(d) for d in corpus_subdirs)}). "
                "Point at one of them."
            )
        raise ConvoKitReadError(
            f"'{source}' does not look like a ConvoKit corpus — no utterances.jsonl "
            "in it or in a single subdirectory."
        )

    if zipfile.is_zipfile(source):
        target = extract_to or os.path.join(
            os.path.dirname(os.path.abspath(source)),
            os.path.splitext(os.path.basename(source))[0] + "_extracted",
        )
        _safe_extract_zip(source, target)
        return resolve_corpus_dir(target)

    if not os.path.exists(source):
        raise ConvoKitReadError(f"No such corpus path: '{source}'")
    raise ConvoKitReadError(
        f"'{source}' is neither a directory nor a zip archive."
    )


def _safe_extract_zip(zip_path: str, target_dir: str) -> None:
    """Extract ``zip_path`` into ``target_dir``, rejecting hostile members."""
    target_abs = os.path.abspath(target_dir)

    with zipfile.ZipFile(zip_path) as zf:
        total = 0
        for info in zf.infolist():
            name = info.filename

            if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
                raise ConvoKitReadError(
                    f"Refusing to extract '{zip_path}': absolute member path '{name}'"
                )
            parts = name.replace("\\", "/").split("/")
            if ".." in parts:
                raise ConvoKitReadError(
                    f"Refusing to extract '{zip_path}': path traversal in member '{name}'"
                )
            # High 16 bits of external_attr are st_mode; 0xA000 marks a symlink.
            if (info.external_attr >> 16) & 0xF000 == 0xA000:
                raise ConvoKitReadError(
                    f"Refusing to extract '{zip_path}': symlink member '{name}'"
                )

            total += info.file_size
            if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ConvoKitReadError(
                    f"Refusing to extract '{zip_path}': uncompressed size exceeds "
                    f"{MAX_ZIP_UNCOMPRESSED_BYTES} bytes"
                )

            resolved = os.path.abspath(os.path.join(target_abs, name))
            if resolved != target_abs and not resolved.startswith(target_abs + os.sep):
                raise ConvoKitReadError(
                    f"Refusing to extract '{zip_path}': member '{name}' escapes the target"
                )

        os.makedirs(target_abs, exist_ok=True)
        zf.extractall(target_abs)


# --------------------------------------------------------------------------- #
# Streaming the utterance file
# --------------------------------------------------------------------------- #

def _utterance_file(corpus_dir: str) -> str:
    for name in ("utterances.jsonl", "utterances.json"):
        path = os.path.join(corpus_dir, name)
        if os.path.isfile(path):
            return path
    raise ConvoKitReadError(f"No utterances.jsonl in '{corpus_dir}'")


def iter_utterance_lines(path: str) -> Iterator[dict]:
    """Yield raw utterance dicts from ``utterances.jsonl`` (or ``.json``).

    Streams the ``.jsonl`` case so a multi-gigabyte corpus never lands in memory
    as one list. The ``.json`` case is a single array and must be read whole —
    upstream has the same limitation.
    """
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, list):
            raise ConvoKitReadError(f"'{path}' is not a JSON array of utterances")
        for row in payload:
            if isinstance(row, dict):
                yield row
        return

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ConvoKitReadError(
                    f"{path}:{line_no}: not valid JSON ({exc})"
                ) from exc
            if isinstance(row, dict):
                yield row


# --------------------------------------------------------------------------- #
# Metadata handling
# --------------------------------------------------------------------------- #

def _is_bin_marker(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(BIN_DELIM_L)
        and value.endswith(BIN_DELIM_R)
    )


def _bin_marker_index(value: str) -> Optional[int]:
    try:
        return int(value[len(BIN_DELIM_L): -len(BIN_DELIM_R)])
    except ValueError:
        return None


def _json_safe(value: Any) -> Any:
    """Coerce an unpickled value into something ``json.dumps`` will accept.

    Everything a :class:`Corpus` holds must be JSON-serializable, because the
    item builder and the corpus writer both serialize metadata verbatim. Values
    read from JSON already satisfy that; values read from a ``-bin.p`` pickle do
    not. Real corpora hit this immediately — ``wikipedia-politeness-corpus``
    stores its per-annotator ratings as ``numpy.int64``, which ``json.dumps``
    rejects with an unhelpful ``Object of type int64 is not JSON serializable``
    several layers away from the cause.

    Numpy is duck-typed rather than imported: any scalar exposing ``.item()`` and
    any array exposing ``.tolist()`` converts, so this works whether or not numpy
    is installed and without adding it to the import path.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _json_safe(tolist())
        except Exception:  # noqa: BLE001 - fall through to the string form
            pass

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:  # noqa: BLE001 - fall through to the string form
            pass

    # Anything else (a spacy Doc, a custom class) has no faithful JSON form.
    # A string is lossy but honest, and keeps the import from dying.
    return str(value)


def _unwrap_meta(value: Any) -> Dict[str, Any]:
    """Speaker/conversation entries are either ``{"meta": {...}}`` or bare meta."""
    if not isinstance(value, dict):
        return {}
    if "meta" in value and isinstance(value["meta"], dict):
        return value["meta"]
    return {k: v for k, v in value.items() if k != "vectors"}


class _BinResolver:
    """Resolves ``<##bin{N}&&@**>`` markers against ``-bin.p`` sidecars.

    Disabled by default. When enabled it still refuses to read outside the corpus
    directory and caps the sidecar size, because ``pickle.load`` on a file
    downloaded from the internet is arbitrary code execution.

    The sidecar naming is asymmetric upstream: the dump path writes
    ``{field}-{speaker,convo,overall}-bin.p`` while the load path looks for
    ``{field}-{speaker,conversation,corpus}-bin.p``. We accept every spelling.
    """

    _SUFFIXES = {
        "utterance": ("",),
        "speaker": ("-speaker",),
        "conversation": ("-convo", "-conversation"),
        "corpus": ("-overall", "-corpus"),
    }

    def __init__(self, corpus_dir: str, enabled: bool, corpus: Corpus):
        self._dir = os.path.abspath(corpus_dir)
        self._enabled = enabled
        self._corpus = corpus
        self._cache: Dict[Tuple[str, str], Optional[List[Any]]] = {}

    def resolve(self, obj_type: str, field_name: str, value: str) -> Any:
        """Return the unpickled value, or ``None`` when skipping."""
        if not self._enabled:
            self._note_skip(obj_type, field_name)
            return None

        payload = self._load(obj_type, field_name)
        if payload is None:
            return None
        idx = _bin_marker_index(value)
        if idx is None or not (0 <= idx < len(payload)):
            self._corpus.warn(
                f"Binary metadata index out of range for {obj_type}.{field_name}"
            )
            return None
        return _json_safe(payload[idx])

    def _note_skip(self, obj_type: str, field_name: str) -> None:
        label = f"{obj_type}.{field_name}"
        if label not in self._corpus.skipped_binary_fields:
            self._corpus.skipped_binary_fields.append(label)
            self._corpus.warn(
                f"Skipped binary metadata field '{label}' (stored in a pickle "
                "sidecar). Pass load_binary_meta=True to read it — note that "
                "unpickling executes arbitrary code."
            )

    def _load(self, obj_type: str, field_name: str) -> Optional[List[Any]]:
        key = (obj_type, field_name)
        if key in self._cache:
            return self._cache[key]

        payload: Optional[List[Any]] = None
        for suffix in self._SUFFIXES.get(obj_type, ("",)):
            candidate = os.path.join(self._dir, f"{field_name}{suffix}-bin.p")
            resolved = os.path.realpath(candidate)
            corpus_real = os.path.realpath(self._dir)
            if resolved != corpus_real and not resolved.startswith(corpus_real + os.sep):
                self._corpus.warn(
                    f"Refusing to read binary sidecar outside the corpus: {candidate}"
                )
                continue
            if not os.path.isfile(resolved):
                continue
            size = os.path.getsize(resolved)
            if size > MAX_BIN_FILE_BYTES:
                self._corpus.warn(
                    f"Binary sidecar '{os.path.basename(resolved)}' is {size} bytes, "
                    f"over the {MAX_BIN_FILE_BYTES}-byte limit; skipping."
                )
                continue
            try:
                with open(resolved, "rb") as f:
                    loaded = pickle.load(f)
            except Exception as exc:  # noqa: BLE001 - any unpickle failure is non-fatal
                self._corpus.warn(
                    f"Could not unpickle '{os.path.basename(resolved)}': {exc}"
                )
                continue
            payload = loaded if isinstance(loaded, list) else [loaded]
            break

        if payload is None:
            self._corpus.warn(
                f"No binary sidecar found for {obj_type}.{field_name}; value dropped."
            )
        self._cache[key] = payload
        return payload


def _clean_meta(
    raw: Any,
    *,
    obj_type: str,
    corpus: Corpus,
    drop: Set[str],
    keep: Set[str],
    bin_resolver: _BinResolver,
) -> Dict[str, Any]:
    """Drop unwanted fields and resolve (or skip) binary markers."""
    if not isinstance(raw, dict):
        return {}

    cleaned: Dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        if name in drop and name not in keep:
            if name not in corpus.dropped_meta_fields:
                corpus.dropped_meta_fields.append(name)
            continue
        if _is_bin_marker(value):
            cleaned[name] = bin_resolver.resolve(obj_type, name, value)
            continue
        cleaned[name] = value
    return cleaned


# --------------------------------------------------------------------------- #
# info.<field>.jsonl overlays
# --------------------------------------------------------------------------- #

def _load_info_files(
    corpus: Corpus,
    corpus_dir: str,
    requested: Sequence[str],
) -> None:
    """Merge ``info.<field>.jsonl`` overlays into object metadata.

    Each line is ``{"id": <object id>, "value": <anything>}`` — the exact shape
    ``convokit``'s ``load_jsonlist_to_dict(f, index_key="id", value_key="value")``
    expects. The filename carries the field name but *not* the object type, so a
    request may be written ``field`` (resolve by id lookup) or ``field:utterance``
    (explicit). Ids matching nothing are skipped, as upstream does.
    """
    for request in requested:
        field_name, _, forced_type = request.partition(":")
        field_name = field_name.strip()
        forced_type = forced_type.strip() or None

        if forced_type and forced_type not in _INFO_RESOLUTION_ORDER:
            corpus.warn(
                f"Unknown object type '{forced_type}' for info field '{field_name}'; "
                f"expected one of {', '.join(_INFO_RESOLUTION_ORDER)}."
            )
            continue

        path = os.path.join(corpus_dir, f"info.{field_name}.jsonl")
        if not os.path.isfile(path):
            corpus.warn(f"No info file for '{field_name}' (looked for {path})")
            continue

        assigned = {t: 0 for t in _INFO_RESOLUTION_ORDER}
        unmatched = 0

        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    corpus.warn(f"{path}:{line_no}: not valid JSON; skipping line")
                    continue
                if not isinstance(entry, dict) or "id" not in entry:
                    corpus.warn(f"{path}:{line_no}: missing 'id'; skipping line")
                    continue

                obj_id = str(entry["id"])
                value = entry.get("value")
                target = forced_type or _resolve_info_target(corpus, obj_id)
                if target is None:
                    unmatched += 1
                    continue
                if _assign_info(corpus, target, obj_id, field_name, value):
                    assigned[target] += 1
                else:
                    unmatched += 1

        hit_types = [t for t, n in assigned.items() if n]
        if len(hit_types) > 1:
            corpus.warn(
                f"info.{field_name}.jsonl matched ids across "
                f"{', '.join(hit_types)}; use '{field_name}:<objtype>' to disambiguate."
            )
        if unmatched:
            corpus.warn(
                f"info.{field_name}.jsonl: {unmatched} id(s) matched no object; skipped."
            )


def _resolve_info_target(corpus: Corpus, obj_id: str) -> Optional[str]:
    if obj_id in corpus.utterances:
        return "utterance"
    if obj_id in corpus.conversations:
        return "conversation"
    if obj_id in corpus.speakers:
        return "speaker"
    return None


def _assign_info(
    corpus: Corpus, obj_type: str, obj_id: str, field_name: str, value: Any
) -> bool:
    if obj_type == "utterance" and obj_id in corpus.utterances:
        corpus.utterances[obj_id].meta[field_name] = value
        return True
    if obj_type == "conversation" and obj_id in corpus.conversations:
        corpus.conversations[obj_id].meta[field_name] = value
        return True
    if obj_type == "speaker" and obj_id in corpus.speakers:
        corpus.speakers[obj_id][field_name] = value
        return True
    return False


# --------------------------------------------------------------------------- #
# The reader
# --------------------------------------------------------------------------- #

def _read_json_map(corpus_dir: str, *names: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """Read the first of ``names`` that exists. Returns ``({}, None)`` if none do."""
    for name in names:
        path = os.path.join(corpus_dir, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, ValueError) as exc:
                raise ConvoKitReadError(f"Could not read {path}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ConvoKitReadError(f"{path} is not a JSON object")
            return payload, name
    return {}, None


def read_corpus(
    source: str,
    *,
    load_binary_meta: bool = False,
    drop_meta: Sequence[str] = tuple(DEFAULT_DROPPED_META),
    keep_meta: Sequence[str] = (),
    info_fields: Optional[Sequence[str]] = None,
    max_conversations: Optional[int] = None,
    name: Optional[str] = None,
) -> Corpus:
    """Read a ConvoKit corpus from a directory or zip.

    Args:
        source: Corpus directory, a directory containing one, or a ``.zip``.
        load_binary_meta: Unpickle ``-bin.p`` sidecars. Off by default because
            unpickling downloaded data executes arbitrary code.
        drop_meta: Metadata fields to discard (default: ``parsed``, ``vectors``,
            ``embeddings``).
        keep_meta: Fields to keep even if listed in ``drop_meta``.
        info_fields: ``info.<field>.jsonl`` overlays to merge, each optionally
            suffixed ``:utterance`` / ``:conversation`` / ``:speaker``.
        max_conversations: Stop after this many *distinct* conversations. Bounds
            the utterance scan; ``conversations.json`` and ``speakers.json`` are
            single JSON objects and are always read whole.
        name: Corpus name for provenance. Defaults to the directory basename.

    Returns:
        A :class:`Corpus`. Check ``.warnings``, ``.skipped_binary_fields``, and
        ``.dropped_meta_fields`` before treating it as a faithful copy.
    """
    corpus_dir = resolve_corpus_dir(source)
    corpus = Corpus(
        name=name or os.path.basename(os.path.normpath(corpus_dir)),
        path=corpus_dir,
    )
    corpus.index = CorpusIndex.from_file(corpus_dir)
    corpus.version = corpus.index.version

    drop = set(drop_meta)
    keep = set(keep_meta)
    bin_resolver = _BinResolver(corpus_dir, load_binary_meta, corpus)

    # --- speakers ---------------------------------------------------------- #
    speakers_raw, speakers_file = _read_json_map(corpus_dir, "speakers.json", "users.json")
    legacy_speaker_file = speakers_file == "users.json"

    # --- conversations ----------------------------------------------------- #
    convos_raw, _ = _read_json_map(corpus_dir, "conversations.json")

    # --- corpus meta ------------------------------------------------------- #
    corpus_meta_raw, _ = _read_json_map(corpus_dir, "corpus.json")
    corpus.meta = _clean_meta(
        corpus_meta_raw,
        obj_type="corpus",
        corpus=corpus,
        drop=drop,
        keep=keep,
        bin_resolver=bin_resolver,
    )

    # --- utterances -------------------------------------------------------- #
    utterance_path = _utterance_file(corpus_dir)
    speaker_key: Optional[str] = None
    convo_key: Optional[str] = None
    seen_conversations: List[str] = []
    seen_conversation_set: Set[str] = set()

    for file_index, row in enumerate(iter_utterance_lines(utterance_path)):
        if speaker_key is None:
            # Upstream's rule, applied to the first row only.
            speaker_key = "speaker" if "speaker" in row else "user"
            convo_key = "conversation_id" if "conversation_id" in row else "root"
            corpus.legacy = speaker_key == "user" or convo_key == "root"
            if corpus.legacy:
                corpus.warn(
                    f"Corpus '{corpus.name}' uses the legacy key names "
                    f"('{speaker_key}'/'{convo_key}'); reading it as such."
                )

        utt_id = row.get("id")
        if utt_id is None:
            corpus.warn("Utterance without an 'id'; skipped.")
            continue
        utt_id = str(utt_id)

        convo_id = row.get(convo_key)
        if convo_id is None:
            # A corpus with no conversation grouping is legal; treat each
            # utterance as its own single-turn conversation rather than dropping
            # it (this is what wikipedia-politeness-corpus effectively is).
            convo_id = utt_id
        convo_id = str(convo_id)

        if convo_id not in seen_conversation_set:
            if max_conversations is not None and len(seen_conversation_set) >= max_conversations:
                break
            seen_conversation_set.add(convo_id)
            seen_conversations.append(convo_id)

        # The dump writes "reply-to"; the loader prefers "reply_to". Both exist.
        reply_to = row.get("reply_to", row.get("reply-to"))
        if reply_to in ("", None):
            reply_to = None
        else:
            reply_to = str(reply_to)

        speaker_id = row.get(speaker_key)
        speaker_id = "" if speaker_id is None else str(speaker_id)

        utterance = Utterance(
            id=utt_id,
            conversation_id=convo_id,
            speaker=speaker_id,
            text=row.get("text") or "",
            reply_to=reply_to,
            timestamp=_coerce_timestamp(row.get("timestamp")),
            meta=_clean_meta(
                row.get("meta"),
                obj_type="utterance",
                corpus=corpus,
                drop=drop,
                keep=keep,
                bin_resolver=bin_resolver,
            ),
            file_index=file_index,
        )

        if utt_id in corpus.utterances:
            corpus.warn(f"Duplicate utterance id '{utt_id}'; keeping the first.")
            continue

        corpus.utterances[utt_id] = utterance
        convo = corpus.conversations.get(convo_id)
        if convo is None:
            convo = Conversation(id=convo_id)
            corpus.conversations[convo_id] = convo
        convo.utterance_ids.append(utt_id)

    if not corpus.utterances:
        corpus.warn(f"No utterances read from {utterance_path}")

    # --- attach speaker / conversation metadata ---------------------------- #
    for speaker_id in {u.speaker for u in corpus.utterances.values()}:
        raw = speakers_raw.get(speaker_id)
        if raw is None:
            corpus.warn(
                f"No metadata for speaker '{speaker_id}'; using an empty dict."
            )
            corpus.speakers[speaker_id] = {}
            continue
        corpus.speakers[speaker_id] = _clean_meta(
            _unwrap_meta(raw),
            obj_type="speaker",
            corpus=corpus,
            drop=drop,
            keep=keep,
            bin_resolver=bin_resolver,
        )

    for convo_id, convo in corpus.conversations.items():
        raw = convos_raw.get(convo_id)
        if raw is None:
            continue
        convo.meta = _clean_meta(
            _unwrap_meta(raw),
            obj_type="conversation",
            corpus=corpus,
            drop=drop,
            keep=keep,
            bin_resolver=bin_resolver,
        )

    if legacy_speaker_file and not corpus.legacy:
        corpus.warn(
            "Corpus has users.json but modern utterance keys; reading both forms."
        )

    if info_fields:
        _load_info_files(corpus, corpus_dir, info_fields)

    return corpus


def _coerce_timestamp(value: Any) -> Optional[float]:
    """ConvoKit timestamps are epoch seconds, but arrive as int, float, or str."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
