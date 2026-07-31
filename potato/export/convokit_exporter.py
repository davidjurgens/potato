"""
Export Potato annotations as ConvoKit metadata.

Closes the loop opened by ``potato convokit``: annotations made in Potato go back
onto the utterances and conversations they were made about, where ConvoKit's
transformers, its DataFrame views, and everything else built on the corpus can
read them.

The mapping is a direct lookup rather than a reconciliation, because the importer
set each turn's ``turn_id`` to the real ConvoKit utterance id and recorded the
conversation id in the item's ``_convokit`` provenance block. Nothing has to be
matched by position or by text.

Two output modes:

``info`` (default)
    ``info.<field>.jsonl`` overlays that drop into an existing corpus directory.
    The corpus is left exactly as downloaded.

``corpus``
    A complete corpus directory with the annotations merged into metadata.

Multiple annotators are never collapsed away. By default each field holds
``{user_id: value}``, which is what an agreement study needs; asking for an
aggregate moves the per-annotator dict to ``<field>_raw`` rather than discarding
it.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.convokit.items import PROVENANCE_KEY
from potato.convokit.reader import Conversation, Corpus, Utterance
from potato.convokit.writer import write_corpus, write_info_files
from potato.server_utils.turn_annotations import flatten_turn_annotation

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)

#: Prefix for every field this exporter writes.
#:
#: An underscore, not a dot: ConvoKit has a MongoDB backend, and MongoDB rejects
#: document keys containing ``.``.
DEFAULT_FIELD_PREFIX = "potato_"

#: Turn ids of this shape are the turn-annotation framework's positional
#: fallback, used when the data had no explicit id. They are not utterance ids.
_INDEX_FALLBACK_RE = re.compile(r"^t(\d+)$")


class ConvoKitExporter(BaseExporter):
    """Write annotations back as ConvoKit corpus metadata."""

    format_name = "convokit"
    description = (
        "ConvoKit corpus metadata — info.<field>.jsonl overlays for an existing "
        "corpus, or a full corpus dump"
    )
    file_extensions = [".jsonl", ".json"]

    # ------------------------------------------------------------------ #
    # Compatibility
    # ------------------------------------------------------------------ #

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not context.items:
            return False, (
                "No item data was loaded. The ConvoKit exporter needs the original "
                "items to know which utterance each annotation belongs to."
            )
        if any(PROVENANCE_KEY in item for item in context.items.values()):
            return True, ""
        return False, (
            f"No item carries a '{PROVENANCE_KEY}' block, so there is nothing to "
            "map annotations back onto. Import the corpus with 'potato convokit' "
            "to produce items that can be exported this way."
        )

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #

    def export(
        self,
        context: ExportContext,
        output_path: str,
        options: Optional[dict] = None,
    ) -> ExportResult:
        options = options or {}
        mode = options.get("mode", "info")
        field_prefix = options.get("field_prefix", DEFAULT_FIELD_PREFIX)
        aggregate = options.get("aggregate", "none")
        include_spans = options.get("include_spans", True)
        corpus_dir = options.get("corpus_dir")
        write_into_corpus = options.get("write_into_corpus", False)

        result = ExportResult(success=False, format_name=self.format_name)

        if mode not in ("info", "corpus"):
            result.errors.append(f"Unknown mode '{mode}'; expected 'info' or 'corpus'.")
            return result
        if aggregate not in ("none", "majority", "mean"):
            result.errors.append(
                f"Unknown aggregate '{aggregate}'; expected 'none', 'majority' or 'mean'."
            )
            return result

        collector = _AnnotationCollector(
            context=context,
            field_prefix=field_prefix,
            include_spans=include_spans,
            warnings=result.warnings,
        )
        collector.collect()

        utterance_meta = _resolve(collector.utterance, aggregate)
        conversation_meta = _resolve(collector.conversation, aggregate)

        result.stats.update(
            {
                "annotated_utterances": len(utterance_meta),
                "annotated_conversations": len(conversation_meta),
                "annotators": len(collector.users),
                "unresolved_turn_ids": collector.unresolved_turn_ids,
                "spans_exported": collector.span_count,
                "mode": mode,
            }
        )

        if not utterance_meta and not conversation_meta:
            result.warnings.append("No annotations mapped onto any corpus object.")

        try:
            if mode == "info":
                target = corpus_dir if (write_into_corpus and corpus_dir) else output_path
                fields = _as_info_fields(utterance_meta, conversation_meta)
                result.files_written = write_info_files(target, fields)
            else:
                corpus = collector.rebuild_corpus(utterance_meta, conversation_meta)
                result.files_written = write_corpus(corpus, output_path)
        except OSError as exc:
            result.errors.append(f"Could not write output: {exc}")
            return result

        result.success = True
        return result


# ---------------------------------------------------------------------- #
# Collection
# ---------------------------------------------------------------------- #

#: ``{object_id: {field: {user_id: value}}}``
_Collected = Dict[str, Dict[str, Dict[str, Any]]]


class _AnnotationCollector:
    """Walks the export context and bins each annotation onto a corpus object."""

    def __init__(
        self,
        context: ExportContext,
        field_prefix: str,
        include_spans: bool,
        warnings: List[str],
    ):
        self.context = context
        self.prefix = field_prefix
        self.include_spans = include_spans
        self.warnings = warnings

        self.utterance: _Collected = defaultdict(lambda: defaultdict(dict))
        self.conversation: _Collected = defaultdict(lambda: defaultdict(dict))
        self.users: set = set()
        self.unresolved_turn_ids = 0
        self.span_count = 0

        self._turn_level = {
            s.get("name")
            for s in (context.schemas or [])
            if s.get("turn_level")
        }

    # -- helpers -------------------------------------------------------- #

    def _provenance(self, instance_id: str) -> Optional[dict]:
        item = self.context.items.get(instance_id)
        if not isinstance(item, dict):
            return None
        prov = item.get(PROVENANCE_KEY)
        return prov if isinstance(prov, dict) else None

    def _resolve_turn_id(self, turn_id: str, prov: dict) -> Optional[str]:
        """Map a stored turn id onto a ConvoKit utterance id."""
        match = _INDEX_FALLBACK_RE.match(str(turn_id))
        if not match:
            return str(turn_id)
        # Positional fallback: the data had no explicit turn id, so recover the
        # utterance from the order the importer recorded.
        ids = prov.get("utterance_ids") or []
        index = int(match.group(1))
        if 0 <= index < len(ids):
            return str(ids[index])
        self.unresolved_turn_ids += 1
        return None

    def _field(self, schema: str, suffix: str = "") -> str:
        return f"{self.prefix}{schema}{suffix}"

    # -- main pass ------------------------------------------------------- #

    def collect(self) -> None:
        for record in self.context.annotations or []:
            instance_id = record.get("instance_id")
            user_id = str(record.get("user_id", "unknown"))
            prov = self._provenance(instance_id)
            if prov is None:
                continue
            self.users.add(user_id)

            self._collect_labels(record, prov, user_id)
            if self.include_spans:
                self._collect_spans(record, prov, user_id)

    def _collect_labels(self, record: dict, prov: dict, user_id: str) -> None:
        convo_id = prov.get("conversation_id")
        focus_utt = prov.get("utterance_id")

        for schema, values in (record.get("labels") or {}).items():
            if not isinstance(values, dict):
                continue

            if schema in self._turn_level or "_data" in values:
                self._collect_turn_level(schema, values, prov, user_id)
                continue

            value = _simplify_label(values)
            if value is None:
                continue

            field = self._field(schema)
            if prov.get("unit") == "utterance" and focus_utt:
                self.utterance[str(focus_utt)][field][user_id] = value
            elif convo_id:
                self.conversation[str(convo_id)][field][user_id] = value

    def _collect_turn_level(
        self, schema: str, values: dict, prov: dict, user_id: str
    ) -> None:
        raw = values.get("_data")
        if raw is None:
            return
        rows = flatten_turn_annotation(schema, raw)
        if not rows:
            return
        field = self._field(schema)
        for row in rows:
            utt_id = self._resolve_turn_id(row.get("turn_id"), prov)
            if utt_id is None:
                continue
            value = row.get("values", row.get("value"))
            if value is None:
                continue
            self.utterance[utt_id][field][user_id] = value

    def _collect_spans(self, record: dict, prov: dict, user_id: str) -> None:
        """Attach spans to the utterance whose text they fall inside.

        Span offsets are measured against the whole dialogue field, so each span
        is located by walking the same turn layout the display renders and the
        server reconstructs, then re-expressed relative to the utterance's own
        text. A span crossing a turn boundary yields one entry per utterance,
        sharing a ``span_group`` id so the pieces can be recombined.
        """
        spans_by_schema = record.get("spans") or {}
        if not spans_by_schema:
            return

        instance_id = record.get("instance_id")
        item = self.context.items.get(instance_id) or {}

        for schema, spans in spans_by_schema.items():
            for span in spans or []:
                if not isinstance(span, dict):
                    continue
                target_field = span.get("target_field")
                turns = item.get(target_field) if target_field else None
                if not isinstance(turns, list):
                    self.warnings.append(
                        f"Span on field '{target_field}' skipped: it is not a "
                        "list of turns, so it cannot be mapped onto utterances."
                    )
                    continue

                pieces = _split_span_across_turns(
                    span, turns, self._show_turn_numbers(target_field)
                )
                if not pieces:
                    self.unresolved_turn_ids += 1
                    continue

                field = self._field(schema, "_spans")
                for utt_id, piece in pieces:
                    resolved = self._resolve_turn_id(utt_id, prov)
                    if resolved is None:
                        continue
                    bucket = self.utterance[resolved][field].setdefault(user_id, [])
                    bucket.append(piece)
                    self.span_count += 1

    def _show_turn_numbers(self, field_key: Optional[str]) -> bool:
        for field in (self.context.config.get("instance_display", {}) or {}).get(
            "fields", []
        ) or []:
            if field.get("key") == field_key:
                return bool(
                    (field.get("display_options") or {}).get("show_turn_numbers", False)
                )
        return False

    # -- corpus reconstruction ------------------------------------------- #

    def rebuild_corpus(
        self,
        utterance_meta: Dict[str, Dict[str, Any]],
        conversation_meta: Dict[str, Dict[str, Any]],
    ) -> Corpus:
        """Rebuild a corpus from the imported items, plus the new metadata.

        The items carry every field the corpus format needs — that is what the
        importer preserved them for — so a full dump does not require the source
        corpus to still be on disk.
        """
        corpus = Corpus(name="potato-export", path="")
        corpus_names = Counter()
        dropped: set = set()
        skipped: set = set()

        for instance_id, item in self.context.items.items():
            prov = item.get(PROVENANCE_KEY)
            if not isinstance(prov, dict):
                continue
            corpus_names[prov.get("corpus") or "unknown"] += 1
            dropped.update(prov.get("dropped_meta") or [])
            skipped.update(prov.get("skipped_binary_meta") or [])
            if corpus.version is None and isinstance(prov.get("corpus_version"), int):
                corpus.version = prov["corpus_version"]

            convo_id = str(prov.get("conversation_id") or instance_id)
            convo = corpus.conversations.get(convo_id)
            if convo is None:
                convo = Conversation(id=convo_id, meta=dict(item.get("convo_meta") or {}))
                corpus.conversations[convo_id] = convo

            for turns in _turn_lists(item):
                for turn in turns:
                    utt_id = turn.get("turn_id")
                    if not utt_id or utt_id in corpus.utterances:
                        continue
                    utt_id = str(utt_id)
                    corpus.utterances[utt_id] = Utterance(
                        id=utt_id,
                        conversation_id=convo_id,
                        speaker=str(turn.get("speaker") or ""),
                        text=str(turn.get("text") or ""),
                        reply_to=turn.get("reply_to"),
                        timestamp=turn.get("timestamp"),
                        meta=dict(turn.get("meta") or {}),
                    )
                    convo.utterance_ids.append(utt_id)

            for speaker_id, meta in (item.get("speakers") or {}).items():
                corpus.speakers.setdefault(str(speaker_id), dict(meta or {}))

        # Any speaker seen on a turn but absent from the roster.
        for utt in corpus.utterances.values():
            if utt.speaker:
                corpus.speakers.setdefault(utt.speaker, {})

        for utt_id, fields in utterance_meta.items():
            if utt_id in corpus.utterances:
                corpus.utterances[utt_id].meta.update(fields)
        for convo_id, fields in conversation_meta.items():
            if convo_id in corpus.conversations:
                corpus.conversations[convo_id].meta.update(fields)

        if corpus_names:
            corpus.name = corpus_names.most_common(1)[0][0]
            corpus.meta["potato_source_corpus"] = corpus.name
        corpus.dropped_meta_fields = sorted(dropped)
        corpus.skipped_binary_fields = sorted(skipped)
        return corpus


# ---------------------------------------------------------------------- #
# Value handling
# ---------------------------------------------------------------------- #

def _turn_lists(item: dict) -> List[List[dict]]:
    """Every list-of-turns field on an item."""
    out = []
    for key, value in item.items():
        if key == PROVENANCE_KEY or not isinstance(value, list):
            continue
        if value and isinstance(value[0], dict) and "turn_id" in value[0]:
            out.append(value)
    return out


def _simplify_label(values: dict) -> Any:
    """Collapse Potato's ``{label_name: value}`` map into one exportable value.

    Radio and likert store the chosen label as the *key* with a truthy value, so
    ``{"yes": "yes"}`` means "yes". Multiselect stores several such entries. A
    single free-text or numeric entry keyed ``""`` is just its value.
    """
    if not values:
        return None

    selected = [name for name, value in values.items() if value not in (None, "", False)]

    if len(values) == 1:
        (name, value), = values.items()
        if name in ("", None):
            return value
        # A single selected label: the label itself is the annotation.
        if isinstance(value, (bool, str)) and name:
            return name
        return value

    if selected:
        return sorted(selected)
    return None


def _resolve(collected: _Collected, aggregate: str) -> Dict[str, Dict[str, Any]]:
    """Turn ``{obj: {field: {user: value}}}`` into final metadata."""
    out: Dict[str, Dict[str, Any]] = {}
    for obj_id, fields in collected.items():
        resolved: Dict[str, Any] = {}
        for field, by_user in fields.items():
            if not by_user:
                continue
            if aggregate == "none":
                resolved[field] = dict(by_user)
                resolved[f"{field}_n_annotators"] = len(by_user)
                continue

            summary = _aggregate(list(by_user.values()), aggregate)
            if summary is None:
                # Nothing sensible to aggregate (e.g. mean over strings): keep
                # the raw form as the value rather than dropping the annotation.
                resolved[field] = dict(by_user)
            else:
                resolved[field] = summary
                # Per-annotator data is never discarded, in any mode.
                resolved[f"{field}_raw"] = dict(by_user)
            resolved[f"{field}_n_annotators"] = len(by_user)
        if resolved:
            out[obj_id] = resolved
    return out


def _aggregate(values: List[Any], how: str) -> Any:
    if not values:
        return None
    if how == "mean":
        numbers = []
        for value in values:
            try:
                numbers.append(float(value))
            except (TypeError, ValueError):
                return None
        return sum(numbers) / len(numbers)

    # majority
    hashable = []
    for value in values:
        hashable.append(tuple(value) if isinstance(value, list) else value)
    try:
        counts = Counter(hashable)
    except TypeError:
        return None
    winner, _ = counts.most_common(1)[0]
    return list(winner) if isinstance(winner, tuple) else winner


def _as_info_fields(
    utterance_meta: Dict[str, Dict[str, Any]],
    conversation_meta: Dict[str, Dict[str, Any]],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Invert ``{obj: {field: value}}`` into ``{(obj_type, field): {obj: value}}``."""
    fields: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(dict)
    for obj_type, source in (("utterance", utterance_meta), ("conversation", conversation_meta)):
        for obj_id, values in source.items():
            for field, value in values.items():
                fields[(obj_type, field)][obj_id] = value
    return dict(fields)


# ---------------------------------------------------------------------- #
# Span placement
# ---------------------------------------------------------------------- #

def _split_span_across_turns(
    span: dict, turns: List[dict], show_turn_numbers: bool
) -> List[Tuple[str, Dict[str, Any]]]:
    """Locate a whole-field span within individual turns.

    Rebuilds the same character layout the display renders and
    ``reconstruct_dialogue_dom_text`` reproduces — ``[i] Speaker: text`` per turn,
    newline-separated — then intersects the span with each turn's own text.
    Offsets in the result are relative to the utterance, which is what makes them
    meaningful once they are attached to it.
    """
    try:
        start = int(span.get("start"))
        end = int(span.get("end"))
    except (TypeError, ValueError):
        return []
    if end <= start:
        return []

    label = span.get("label") or span.get("name")
    span_group = span.get("id")

    pieces: List[Tuple[str, Dict[str, Any]]] = []
    cursor = 0
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        prefix_parts = []
        if show_turn_numbers:
            prefix_parts.append(f"[{index + 1}]")
        speaker = turn.get("speaker") or ""
        if speaker:
            prefix_parts.append(f"{speaker}:")
        prefix = " ".join(prefix_parts)
        prefix_len = len(prefix) + (1 if prefix else 0)

        text = str(turn.get("text") or "")
        text_start = cursor + prefix_len
        text_end = text_start + len(text)

        overlap_start = max(start, text_start)
        overlap_end = min(end, text_end)
        if overlap_start < overlap_end:
            local_start = overlap_start - text_start
            local_end = overlap_end - text_start
            piece = {
                "start": local_start,
                "end": local_end,
                "text": text[local_start:local_end],
            }
            if label:
                piece["label"] = label
            if span_group:
                piece["span_group"] = span_group
            pieces.append((str(turn.get("turn_id") or f"t{index}"), piece))

        # One newline between turns, matching TURN_SEPARATOR.
        cursor = text_end + 1

    return pieces
