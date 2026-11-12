"""
Writing a ConvoKit corpus back to disk.

The counterpart to :mod:`potato.convokit.reader`, and the half that lets
annotations made in Potato re-enter a ConvoKit workflow. Two shapes are
supported, because they answer different questions:

**Overlay** (:func:`write_info_files`)
    ``info.<field>.jsonl`` files that drop into an existing corpus directory and
    are picked up by ``corpus.load_info(obj_type, [field])``. Nothing about the
    original corpus is rewritten, so this is the safe default: the corpus on disk
    stays exactly as downloaded and the annotations ride alongside it.

**Full dump** (:func:`write_corpus`)
    A complete corpus directory. For when the annotated result is the artifact —
    something to archive, share, or hand to a collaborator who should not need
    the original plus a patch.

Round-tripping is deliberately not claimed to be lossless. Binary metadata
skipped on read is never re-emitted and vectors are never carried, so
:func:`write_corpus` records what was dropped in ``corpus.json`` rather than
letting the output pass for a faithful copy.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .reader import Corpus
from .schema import CorpusIndex, python_type_string

logger = logging.getLogger(__name__)

__all__ = [
    "info_filename",
    "write_corpus",
    "write_info_files",
]


def info_filename(field: str) -> str:
    """The filename ``corpus.load_info`` expects for a metadata field.

    Upstream recovers the field name by stripping the ``info.`` prefix and the
    ``.jsonl`` suffix, so the middle survives verbatim — including dots, which is
    why the field itself must not contain any.
    """
    return f"info.{field}.jsonl"


def write_info_files(
    output_dir: str,
    fields: Dict[Tuple[str, str], Dict[str, Any]],
) -> List[str]:
    """Write ``info.<field>.jsonl`` overlays.

    Args:
        output_dir: Directory to write into — an existing corpus directory when
            the overlays are meant to be loaded in place.
        fields: ``{(obj_type, field_name): {object_id: value}}``.

    Returns:
        The paths written.

    Each line is exactly ``{"id": ..., "value": ...}``, which is what
    ``load_jsonlist_to_dict(f, index_key="id", value_key="value")`` reads. Ids
    that do not exist in the target corpus are skipped silently by ConvoKit, so
    an overlay built from a subset of a corpus is safe to load against the whole.
    """
    os.makedirs(output_dir, exist_ok=True)
    written: List[str] = []
    manifest: Dict[str, str] = {}

    for (obj_type, field_name), values in sorted(fields.items()):
        if not values:
            continue
        if "." in field_name:
            # The loader slices on '.', so a dotted field name would come back
            # truncated and silently attach to the wrong key.
            logger.warning(
                "Skipping info field '%s': dots are not usable in an info "
                "filename (convokit recovers the field by slicing on them).",
                field_name,
            )
            continue

        path = os.path.join(output_dir, info_filename(field_name))
        with open(path, "w", encoding="utf-8") as f:
            for obj_id, value in values.items():
                f.write(
                    json.dumps({"id": str(obj_id), "value": value}, ensure_ascii=False)
                    + "\n"
                )
        written.append(path)
        manifest[field_name] = obj_type

    if manifest:
        # corpus.load_info(obj_type, fields) makes the caller name the object
        # type, which the filename does not encode. Record it so nobody has to
        # guess whether a field belongs to utterances or conversations.
        manifest_path = os.path.join(output_dir, "potato_export_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_by": "potato export --format convokit",
                    "object_types": manifest,
                    "usage": {
                        field: f'corpus.load_info("{obj_type}", ["{field}"])'
                        for field, obj_type in sorted(manifest.items())
                    },
                },
                f,
                indent=1,
            )
        written.append(manifest_path)

    return written


def _build_index(corpus: Corpus) -> CorpusIndex:
    """Derive an index from the metadata actually present.

    Recomputed rather than carried over from the source, because the whole point
    of the export is that the metadata changed.
    """
    indices: Dict[str, Dict[str, List[str]]] = {
        "utterance": {},
        "speaker": {},
        "conversation": {},
        "corpus": {},
    }

    def record(obj_type: str, meta: Dict[str, Any]) -> None:
        for key, value in (meta or {}).items():
            if value is None:
                # convokit tolerates a missing key; recording a type for a value
                # that is always None would be a lie.
                continue
            type_str = python_type_string(value)
            entry = indices[obj_type].setdefault(str(key), [])
            if type_str not in entry:
                entry.append(type_str)

    for utt in corpus.utterances.values():
        record("utterance", utt.meta)
    for meta in corpus.speakers.values():
        record("speaker", meta)
    for convo in corpus.conversations.values():
        record("conversation", convo.meta)
    record("corpus", corpus.meta)

    return CorpusIndex(
        indices=indices,
        version=corpus.version if corpus.version is not None else 1,
        present=True,
    )


def _strip_none(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in (meta or {}).items() if v is not None}


def write_corpus(
    corpus: Corpus,
    output_dir: str,
    *,
    legacy_speaker_key: bool = False,
) -> List[str]:
    """Write a full ConvoKit corpus directory.

    Args:
        corpus: The corpus to write.
        output_dir: Directory to create and write into.
        legacy_speaker_key: Write ``users.json``/``users-index`` instead of the
            modern spellings. Off by default — new output should use current
            names even when the source was legacy.

    Returns:
        The paths written.
    """
    os.makedirs(output_dir, exist_ok=True)
    written: List[str] = []

    # --- utterances.jsonl -------------------------------------------------- #
    utt_path = os.path.join(output_dir, "utterances.jsonl")
    with open(utt_path, "w", encoding="utf-8") as f:
        for utt in corpus.utterances.values():
            row = {
                "id": utt.id,
                "conversation_id": utt.conversation_id,
                "text": utt.text,
                "speaker": utt.speaker,
                "meta": _strip_none(utt.meta),
                # The hyphenated spelling is what convokit's dump writes; its
                # loader accepts both.
                "reply-to": utt.reply_to,
                "timestamp": utt.timestamp,
                "vectors": [],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    written.append(utt_path)

    # --- speakers / conversations ------------------------------------------ #
    speaker_file = "users.json" if legacy_speaker_key else "speakers.json"
    speakers_path = os.path.join(output_dir, speaker_file)
    with open(speakers_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                sid: {"meta": _strip_none(meta), "vectors": []}
                for sid, meta in corpus.speakers.items()
            },
            f,
            ensure_ascii=False,
        )
    written.append(speakers_path)

    convos_path = os.path.join(output_dir, "conversations.json")
    with open(convos_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                cid: {"meta": _strip_none(convo.meta), "vectors": []}
                for cid, convo in corpus.conversations.items()
            },
            f,
            ensure_ascii=False,
        )
    written.append(convos_path)

    # --- corpus.json ------------------------------------------------------- #
    corpus_meta = dict(_strip_none(corpus.meta))
    # Say plainly what this copy does not contain, so it is not mistaken for a
    # faithful reproduction of the source.
    if corpus.skipped_binary_fields:
        corpus_meta["potato_skipped_binary_meta"] = sorted(corpus.skipped_binary_fields)
    if corpus.dropped_meta_fields:
        corpus_meta["potato_dropped_meta"] = sorted(corpus.dropped_meta_fields)

    corpus_path = os.path.join(output_dir, "corpus.json")
    with open(corpus_path, "w", encoding="utf-8") as f:
        json.dump(corpus_meta, f, ensure_ascii=False)
    written.append(corpus_path)

    # --- index.json -------------------------------------------------------- #
    index_path = os.path.join(output_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(
            _build_index(corpus).to_dict(legacy_speaker_key=legacy_speaker_key),
            f,
            indent=1,
        )
    written.append(index_path)

    return written
