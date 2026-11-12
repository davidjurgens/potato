"""
ConvoKit ``index.json`` parsing.

A ConvoKit corpus ships a metadata index describing, for each object type, which
metadata fields exist and what Python types their values took when the corpus was
dumped. Potato uses it for two things: deciding which fields are *binary* (stored
in a pickle sidecar rather than inline) and suggesting annotation schemes from the
fields a corpus already carries.

The on-disk shape is inconsistent across corpus versions, which is the whole
reason this module exists:

* Modern dumps write a **list** of type strings per field —
  ``{"toxicity": ["<class 'float'>"]}``.
* Older dumps write a **bare string** — ``{"toxicity": "<class 'float'>"}``.
  Upstream normalizes this on load (``ConvoKitIndex.update_from_dict`` contains
  ``if isinstance(v, str): index[k] = [v]``), so both are legal on disk. Verified
  in the wild: ``conversations-gone-awry-corpus`` (version 6) uses bare strings.
* Legacy dumps key the speaker index as ``users-index`` rather than
  ``speakers-index``.

:class:`CorpusIndex` normalizes all of that to one shape so no caller downstream
has to know which vintage it is reading.

A caution that matters for :mod:`potato.convokit.config_gen`: **these types are a
hint, not the truth.** In ``conversations-gone-awry-corpus`` the field
``toxicity`` is indexed as ``<class 'int'>`` while its actual values are floats
like ``0.078140646``. Anything that needs to be correct must sample real values.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "BIN_TYPE",
    "OBJ_TYPES",
    "CorpusIndex",
    "python_type_string",
]

#: The literal type marker ConvoKit writes for metadata held in a ``-bin.p``
#: pickle rather than inline in the JSON. Upstream asserts every index value is
#: either this or a ``"<class '...'>"`` string.
BIN_TYPE = "bin"

#: Object types, in the spelling Potato uses internally. The index file keys are
#: the pluralized forms (``utterances-index`` and friends), and the speaker index
#: is spelled ``users-index`` in legacy corpora.
OBJ_TYPES = ("utterance", "speaker", "conversation", "corpus")

#: Maps our object type to the index key(s) to look for, most-preferred first.
_INDEX_KEYS = {
    "utterance": ("utterances-index",),
    "speaker": ("speakers-index", "users-index"),
    "conversation": ("conversations-index",),
    "corpus": ("overall-index",),
}


def python_type_string(value: Any) -> str:
    """Render ``value``'s type the way ConvoKit's index spells it.

    ``True`` -> ``"<class 'bool'>"``. Used when writing an index back out.
    """
    return str(type(value))


@dataclass
class CorpusIndex:
    """Normalized view of a corpus ``index.json``.

    Every field maps to a ``list[str]`` of type strings regardless of how the
    file spelled it. ``legacy_speaker_key`` records whether the speaker index
    arrived as ``users-index``, which is a useful corroborating signal for the
    reader's legacy detection (that detection is driven by the utterance keys,
    per upstream, but a corpus with ``users-index`` and ``speaker`` fields is
    worth a warning).
    """

    indices: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    version: Optional[int] = None
    legacy_speaker_key: bool = False
    present: bool = False

    @classmethod
    def empty(cls) -> "CorpusIndex":
        return cls(indices={t: {} for t in OBJ_TYPES}, present=False)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "CorpusIndex":
        indices: Dict[str, Dict[str, List[str]]] = {}
        legacy_speaker_key = False

        for obj_type, candidate_keys in _INDEX_KEYS.items():
            entry: Dict[str, Any] = {}
            for key in candidate_keys:
                if key in raw:
                    entry = raw[key] or {}
                    if key == "users-index":
                        legacy_speaker_key = True
                    break
            indices[obj_type] = _normalize_entry(entry, obj_type)

        version = raw.get("version")
        if not isinstance(version, int):
            version = None

        return cls(
            indices=indices,
            version=version,
            legacy_speaker_key=legacy_speaker_key,
            present=True,
        )

    @classmethod
    def from_file(cls, corpus_dir: str) -> "CorpusIndex":
        """Read ``<corpus_dir>/index.json``, tolerating its absence.

        A missing or unparseable index is not fatal — callers fall back to
        sampling real values, which is more reliable anyway.
        """
        path = os.path.join(corpus_dir, "index.json")
        if not os.path.exists(path):
            logger.debug("No index.json in %s; types will be inferred", corpus_dir)
            return cls.empty()
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError) as exc:
            logger.warning("Could not read %s (%s); types will be inferred", path, exc)
            return cls.empty()
        if not isinstance(raw, dict):
            logger.warning("%s is not a JSON object; types will be inferred", path)
            return cls.empty()
        return cls.from_dict(raw)

    def types_for(self, obj_type: str, field_name: str) -> List[str]:
        """Type strings recorded for one field, or ``[]`` if unrecorded."""
        return self.indices.get(obj_type, {}).get(field_name, [])

    def is_binary(self, obj_type: str, field_name: str) -> bool:
        """Is this field stored in a ``-bin.p`` pickle sidecar?

        Upstream checks only the first entry, so a field indexed as
        ``["bin", "<class 'list'>"]`` counts as binary. We match that.
        """
        types = self.types_for(obj_type, field_name)
        return bool(types) and types[0] == BIN_TYPE

    def fields(self, obj_type: str) -> List[str]:
        return list(self.indices.get(obj_type, {}).keys())

    def binary_fields(self, obj_type: str) -> List[str]:
        return [f for f in self.fields(obj_type) if self.is_binary(obj_type, f)]

    def to_dict(self, *, legacy_speaker_key: bool = False) -> Dict[str, Any]:
        """Serialize back to ``index.json`` shape, always with list values.

        Writing the modern (list) form is deliberate: it is what current ConvoKit
        dumps, and ``update_from_dict`` upgrades strings to lists on load anyway,
        so lists are accepted by every version that can read the corpus at all.
        """
        speaker_key = "users-index" if legacy_speaker_key else "speakers-index"
        out: Dict[str, Any] = {
            "utterances-index": dict(self.indices.get("utterance", {})),
            speaker_key: dict(self.indices.get("speaker", {})),
            "conversations-index": dict(self.indices.get("conversation", {})),
            "overall-index": dict(self.indices.get("corpus", {})),
            "version": self.version if self.version is not None else 1,
        }
        return out


def _normalize_entry(entry: Any, obj_type: str) -> Dict[str, List[str]]:
    """Coerce one ``*-index`` block to ``{field: [type_str, ...]}``."""
    if not isinstance(entry, dict):
        logger.warning("Index block for %s is not an object; ignoring", obj_type)
        return {}

    normalized: Dict[str, List[str]] = {}
    for key, value in entry.items():
        if isinstance(value, str):
            normalized[str(key)] = [value]
        elif isinstance(value, list):
            normalized[str(key)] = [str(v) for v in value]
        elif value is None:
            normalized[str(key)] = []
        else:
            # Nothing upstream produces this, but a corrupt index should not
            # take down an import that does not even need the types.
            logger.warning(
                "Unexpected index value for %s.%s (%r); ignoring", obj_type, key, value
            )
            normalized[str(key)] = []
    return normalized
