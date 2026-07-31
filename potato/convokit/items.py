"""
Turning a ConvoKit corpus into Potato items.

A ConvoKit conversation is a *tree*: utterances point at their parent through
``reply_to``, and Wikipedia talk pages and Reddit threads genuinely branch. Potato
annotates flat items. This module bridges the two, at either of two granularities:

``conversation``
    One item per conversation, carrying every turn. Conversation-level schemes
    annotate the whole thread; ``turn_level`` schemes annotate individual turns.
    This is the default and the interesting case.

``utterance``
    One item per utterance, with a configurable window of surrounding turns for
    context. This is what corpora like ``wikipedia-politeness-corpus`` want, where
    each utterance is an independent judgement.

The ``turn_id`` contract
------------------------

Every emitted turn carries ``turn_id`` set to the **real ConvoKit utterance id**.
That single choice is what makes the round trip work:
:func:`potato.server_utils.turn_annotations.turn_id_for` prefers an explicit
``turn_id`` over its ``t{index}`` fallback, and ``turn_id`` is already in
``_trace_normalize.PASSTHROUGH_KEYS``, so per-turn annotations are stored keyed by
genuine utterance ids with no change to the annotation framework at all. Exporting
them back into ConvoKit metadata is then a direct lookup rather than a
reconciliation against positions that may have shifted.

Tree nodes use the same ids, so a task can show a threaded tree *and* a flat
dialogue of the same conversation and their annotations refer to the same turns.

Ordering
--------

Sibling replies are ordered by ``(timestamp, file_index)`` when every timestamp in
the conversation is present, and by ``file_index`` alone otherwise. They are never
ordered by id: ConvoKit ids like ``146743638.12667.12652`` are structured strings
that do not sort meaningfully.

Turn order within an item is either ``thread`` (depth-first pre-order, so replies
sit under what they reply to — required for the indented flat view) or
``chronological`` (global timestamp sort).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .reader import Conversation, Corpus, Utterance

logger = logging.getLogger(__name__)

__all__ = [
    "PROVENANCE_KEY",
    "ItemBuildError",
    "ItemOptions",
    "build_items",
    "concatenate_turns",
    "ordered_turns",
]

#: The single key under which import provenance is stored on every item. Leading
#: underscore, and a name no ConvoKit corpus uses, so it cannot collide with
#: promoted metadata. Never listed in ``instance_display.fields``, so it is never
#: rendered — but it survives into ``ExportContext.items``, which is what lets the
#: exporter map annotations back onto the corpus.
PROVENANCE_KEY = "_convokit"

#: Bumped if the provenance shape ever changes, so an exporter reading an old data
#: file can tell.
PROVENANCE_VERSION = 1


class ItemBuildError(Exception):
    """Raised when the requested item shape cannot be produced."""


@dataclass
class ItemOptions:
    """How to turn a corpus into items."""

    unit: str = "conversation"                 # conversation | utterance
    field_name: str = "conversation"           # the dialogue field key
    tree_field: Optional[str] = "conversation_tree"   # None/"" to omit
    text_field: str = "text"
    id_prefix: bool = True                     # "convo:"/"utt:" prefixes
    order: str = "thread"                      # thread | chronological
    context_before: int = 2
    context_after: int = 2
    context_mode: str = "auto"                 # ancestors | linear | auto
    promote_meta: Sequence[str] = ()
    convo_meta_field: Optional[str] = "convo_meta"
    speakers_field: Optional[str] = "speakers"
    include_turn_meta: bool = True

    def validate(self) -> None:
        if self.unit not in ("conversation", "utterance"):
            raise ItemBuildError(
                f"unit must be 'conversation' or 'utterance', got {self.unit!r}"
            )
        if self.order not in ("thread", "chronological"):
            raise ItemBuildError(
                f"order must be 'thread' or 'chronological', got {self.order!r}"
            )
        if self.context_mode not in ("ancestors", "linear", "auto"):
            raise ItemBuildError(
                f"context_mode must be 'ancestors', 'linear' or 'auto', "
                f"got {self.context_mode!r}"
            )
        if self.context_before < 0 or self.context_after < 0:
            raise ItemBuildError("context window sizes must be >= 0")

        # Two fields writing the same key would silently clobber each other.
        chosen = [
            ("field", self.field_name),
            ("tree_field", self.tree_field),
            ("text_field", self.text_field),
            ("convo_meta_field", self.convo_meta_field),
            ("speakers_field", self.speakers_field),
        ]
        seen: Dict[str, str] = {}
        for label, name in chosen:
            if not name:
                continue
            if name == PROVENANCE_KEY:
                raise ItemBuildError(
                    f"--{label.replace('_', '-')} cannot be {PROVENANCE_KEY!r}; "
                    "that key holds import provenance."
                )
            if name in seen:
                raise ItemBuildError(
                    f"--{label.replace('_', '-')} and --{seen[name].replace('_', '-')} "
                    f"are both {name!r}; each field needs its own key."
                )
            seen[name] = label


@dataclass
class _Thread:
    """A conversation's utterances arranged as a tree, with depths resolved."""

    conversation: Conversation
    #: Utterance ids in the requested order.
    order: List[str] = field(default_factory=list)
    depth: Dict[str, int] = field(default_factory=dict)
    parent: Dict[str, Optional[str]] = field(default_factory=dict)
    children: Dict[str, List[str]] = field(default_factory=dict)
    roots: List[str] = field(default_factory=list)
    dangling: int = 0
    cycles: int = 0


# --------------------------------------------------------------------------- #
# Tree construction
# --------------------------------------------------------------------------- #

def _sort_key(utterances: Dict[str, Utterance], ids: Iterable[str], use_time: bool):
    if use_time:
        return sorted(ids, key=lambda u: (utterances[u].timestamp or 0.0, utterances[u].file_index))
    return sorted(ids, key=lambda u: utterances[u].file_index)


def _build_thread(corpus: Corpus, convo: Conversation, order: str) -> _Thread:
    """Resolve one conversation's reply structure into a tree.

    Dangling parents (pointing outside the conversation) and reply cycles both
    become extra roots rather than errors — real corpora contain both, and losing
    the utterances would be worse than losing their exact position.
    """
    thread = _Thread(conversation=convo)
    ids = [uid for uid in convo.utterance_ids if uid in corpus.utterances]
    if not ids:
        return thread

    id_set = set(ids)
    utterances = corpus.utterances
    use_time = all(utterances[uid].timestamp is not None for uid in ids)

    for uid in ids:
        parent = utterances[uid].reply_to
        if parent is not None and parent not in id_set:
            thread.dangling += 1
            parent = None
        thread.parent[uid] = parent
        thread.children.setdefault(uid, [])

    for uid in ids:
        parent = thread.parent[uid]
        if parent is None:
            thread.roots.append(uid)
        else:
            thread.children[parent].append(uid)

    # A pure cycle (a -> b -> a with no root) leaves those nodes unreachable from
    # any root. Promote the earliest of each unreachable group to a root.
    reachable: Set[str] = set()
    stack = list(thread.roots)
    while stack:
        node = stack.pop()
        if node in reachable:
            continue
        reachable.add(node)
        stack.extend(thread.children.get(node, ()))

    unreachable = [uid for uid in ids if uid not in reachable]
    while unreachable:
        promoted = _sort_key(utterances, unreachable, use_time)[0]
        old_parent = thread.parent.get(promoted)
        if old_parent is not None and promoted in thread.children.get(old_parent, []):
            thread.children[old_parent].remove(promoted)
        thread.parent[promoted] = None
        thread.roots.append(promoted)
        thread.cycles += 1

        stack = [promoted]
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            stack.extend(thread.children.get(node, ()))
        unreachable = [uid for uid in ids if uid not in reachable]

    thread.roots = _sort_key(utterances, thread.roots, use_time)
    for uid in thread.children:
        thread.children[uid] = _sort_key(utterances, thread.children[uid], use_time)

    # Depth-first pre-order over the resolved tree, computing depth as we go.
    ordered: List[str] = []
    for root in thread.roots:
        stack: List[Tuple[str, int]] = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            if node in thread.depth:
                continue
            thread.depth[node] = depth
            ordered.append(node)
            for child in reversed(thread.children.get(node, ())):
                stack.append((child, depth + 1))

    if order == "chronological":
        thread.order = _sort_key(utterances, ordered, use_time)
    else:
        thread.order = ordered

    return thread


# --------------------------------------------------------------------------- #
# Turn rendering
# --------------------------------------------------------------------------- #

def _turn_dict(
    utt: Utterance,
    depth: int,
    index: int,
    opts: ItemOptions,
) -> Dict[str, Any]:
    """One turn, in the shape the dialogue display consumes.

    ``turn_id`` is the real ConvoKit utterance id — see the module docstring.
    """
    turn: Dict[str, Any] = {
        "turn_id": utt.id,
        "speaker": utt.speaker,
        "text": utt.text,
        "reply_to": utt.reply_to,
        "depth": depth,
        "index": index,
    }
    if utt.timestamp is not None:
        turn["timestamp"] = utt.timestamp
    if opts.include_turn_meta and utt.meta:
        turn["meta"] = utt.meta
    return turn


def ordered_turns(
    corpus: Corpus, convo: Conversation, opts: ItemOptions
) -> Tuple[List[Dict[str, Any]], _Thread]:
    """Render one conversation's utterances as ordered turn dicts."""
    thread = _build_thread(corpus, convo, opts.order)
    turns = [
        _turn_dict(corpus.utterances[uid], thread.depth.get(uid, 0), i, opts)
        for i, uid in enumerate(thread.order)
    ]
    return turns, thread


def concatenate_turns(turns: Sequence[Dict[str, Any]]) -> str:
    """Flat ``"Speaker: text"`` rendering, one turn per line.

    Exists so ``item_properties.text_key`` has something to point at: Potato warns
    when ``text_key`` is missing, and search, similarity, and AI suggestion all
    read that field.
    """
    lines = []
    for turn in turns:
        speaker = str(turn.get("speaker") or "").strip()
        text = str(turn.get("text") or "")
        lines.append(f"{speaker}: {text}" if speaker else text)
    return "\n".join(lines)


def _build_tree(
    corpus: Corpus, thread: _Thread, node_id: str, opts: ItemOptions
) -> Dict[str, Any]:
    """Nested ``{"id","speaker","text","children"}`` for the tree display.

    Node ``id`` is the utterance id, matching the flat view's ``turn_id`` so both
    views annotate the same turns.
    """
    utt = corpus.utterances[node_id]
    node: Dict[str, Any] = {
        "id": utt.id,
        "speaker": utt.speaker,
        "text": utt.text,
        "depth": thread.depth.get(node_id, 0),
        "children": [
            _build_tree(corpus, thread, child, opts)
            for child in thread.children.get(node_id, ())
        ],
    }
    if utt.timestamp is not None:
        node["timestamp"] = utt.timestamp
    if opts.include_turn_meta and utt.meta:
        node["meta"] = utt.meta
    return node


def _tree_payload(corpus: Corpus, thread: _Thread, opts: ItemOptions) -> Optional[Any]:
    """The tree field's value: one node, or a synthetic root over several."""
    if not thread.roots:
        return None
    if len(thread.roots) == 1:
        return _build_tree(corpus, thread, thread.roots[0], opts)
    # A conversation with several roots (dangling parents, broken threading) still
    # has to render as one tree. A synthetic root is clearer than dropping any.
    #
    # It is flagged ``synthetic`` because it is not an utterance: displays must
    # not offer it for annotation, or an annotation would be stored under an id
    # that exists in no corpus and could never be exported back.
    return {
        "id": f"{thread.conversation.id}::roots",
        "speaker": "",
        "text": f"({len(thread.roots)} root messages)",
        "depth": 0,
        "synthetic": True,
        "children": [_build_tree(corpus, thread, r, opts) for r in thread.roots],
    }


# --------------------------------------------------------------------------- #
# Context selection for utterance-level items
# --------------------------------------------------------------------------- #

def _detect_context_mode(corpus: Corpus) -> str:
    """Is this corpus threaded, or is ``reply_to`` just "the previous line"?

    Switchboard and movie-corpus link every utterance to its immediate predecessor
    purely to express sequence; walking ancestors there is the same as walking
    backwards, but doing it explicitly is wasted work and reads oddly. Genuinely
    threaded corpora (Wikipedia, Reddit) need real ancestor walks.
    """
    checked = 0
    for convo in corpus.conversations.values():
        ids = [uid for uid in convo.utterance_ids if uid in corpus.utterances]
        for position, uid in enumerate(ids):
            parent = corpus.utterances[uid].reply_to
            if parent is None:
                continue
            checked += 1
            if position == 0 or parent != ids[position - 1]:
                return "ancestors"
        if checked >= 500:
            break
    return "linear" if checked else "ancestors"


def _ancestors(thread: _Thread, uid: str, limit: int) -> List[str]:
    """Up to ``limit`` ancestors of ``uid``, nearest last."""
    chain: List[str] = []
    seen: Set[str] = {uid}
    node = thread.parent.get(uid)
    while node is not None and len(chain) < limit and node not in seen:
        chain.append(node)
        seen.add(node)
        node = thread.parent.get(node)
    chain.reverse()
    return chain


def _descendants(thread: _Thread, uid: str, limit: int) -> List[str]:
    """Up to ``limit`` following turns, in threaded display order.

    Depth-first pre-order over the focus utterance's subtree, so the context is
    the replies as an annotator would see them laid out. Walking only the
    first-child chain instead would dead-end as soon as the first reply happened
    to have no replies of its own, which on a branching thread throws away the
    sibling replies that are the most relevant context there is.
    """
    out: List[str] = []
    seen: Set[str] = {uid}
    stack: List[str] = list(reversed(thread.children.get(uid, ())))
    while stack and len(out) < limit:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        out.append(node)
        stack.extend(reversed(thread.children.get(node, ())))
    return out


# --------------------------------------------------------------------------- #
# Item construction
# --------------------------------------------------------------------------- #

def _base_provenance(corpus: Corpus, opts: ItemOptions) -> Dict[str, Any]:
    return {
        "v": PROVENANCE_VERSION,
        "corpus": corpus.name,
        "corpus_version": corpus.version,
        "unit": opts.unit,
        "legacy_keys": corpus.legacy,
        "dropped_meta": list(corpus.dropped_meta_fields),
        "skipped_binary_meta": list(corpus.skipped_binary_fields),
    }


def _promote(item: Dict[str, Any], meta: Dict[str, Any], names: Sequence[str]) -> None:
    """Lift selected metadata to top-level item keys.

    Only scalars: a promoted key is meant for ``item_properties``, filters, and
    keyword highlighting, none of which can do anything with a nested structure.
    """
    for name in names:
        if name not in meta:
            continue
        value = meta[name]
        if isinstance(value, (dict, list)):
            logger.warning(
                "Not promoting metadata field '%s': value is a %s, and promoted "
                "fields must be scalars.",
                name,
                type(value).__name__,
            )
            continue
        if name in item or name == PROVENANCE_KEY:
            logger.warning(
                "Not promoting metadata field '%s': it would overwrite an existing "
                "item key.",
                name,
            )
            continue
        item[name] = value


def _conversation_items(corpus: Corpus, opts: ItemOptions) -> Iterable[Dict[str, Any]]:
    for convo in corpus.conversations.values():
        turns, thread = ordered_turns(corpus, convo, opts)
        if not turns:
            continue

        item_id = f"convo:{convo.id}" if opts.id_prefix else convo.id
        item: Dict[str, Any] = {"id": item_id, opts.field_name: turns}

        if opts.tree_field:
            tree = _tree_payload(corpus, thread, opts)
            if tree is not None:
                item[opts.tree_field] = tree

        item[opts.text_field] = concatenate_turns(turns)

        if opts.convo_meta_field and convo.meta:
            item[opts.convo_meta_field] = convo.meta
        if opts.speakers_field:
            speaker_ids = {t["speaker"] for t in turns if t.get("speaker")}
            item[opts.speakers_field] = {
                sid: corpus.speakers.get(sid, {}) for sid in sorted(speaker_ids)
            }

        _promote(item, convo.meta, opts.promote_meta)

        provenance = _base_provenance(corpus, opts)
        provenance.update(
            {
                "conversation_id": convo.id,
                "utterance_ids": [t["turn_id"] for t in turns],
                "dangling_reply_to": thread.dangling,
                "broken_cycles": thread.cycles,
            }
        )
        item[PROVENANCE_KEY] = provenance
        yield item


def _utterance_items(corpus: Corpus, opts: ItemOptions) -> Iterable[Dict[str, Any]]:
    mode = opts.context_mode
    if mode == "auto":
        mode = _detect_context_mode(corpus)
        logger.info("Context mode auto-detected as '%s'", mode)

    for convo in corpus.conversations.values():
        thread = _build_thread(corpus, convo, "thread")
        positions = {uid: i for i, uid in enumerate(thread.order)}

        for uid in thread.order:
            if mode == "ancestors":
                before = _ancestors(thread, uid, opts.context_before)
                after = _descendants(thread, uid, opts.context_after)
            else:
                pos = positions[uid]
                start = max(0, pos - opts.context_before)
                before = thread.order[start:pos]
                after = thread.order[pos + 1: pos + 1 + opts.context_after]

            window = before + [uid] + after
            turns = []
            for i, wid in enumerate(window):
                turn = _turn_dict(
                    corpus.utterances[wid], thread.depth.get(wid, 0), i, opts
                )
                if wid == uid:
                    turn["is_focus"] = True
                turns.append(turn)

            item_id = f"utt:{uid}" if opts.id_prefix else uid
            item: Dict[str, Any] = {
                "id": item_id,
                opts.field_name: turns,
                opts.text_field: corpus.utterances[uid].text,
                "focus_turn_id": uid,
            }

            if opts.convo_meta_field and convo.meta:
                item[opts.convo_meta_field] = convo.meta
            if opts.speakers_field:
                speaker_ids = {t["speaker"] for t in turns if t.get("speaker")}
                item[opts.speakers_field] = {
                    sid: corpus.speakers.get(sid, {}) for sid in sorted(speaker_ids)
                }

            _promote(item, corpus.utterances[uid].meta, opts.promote_meta)

            provenance = _base_provenance(corpus, opts)
            provenance.update(
                {
                    "conversation_id": convo.id,
                    "utterance_id": uid,
                    "utterance_ids": [t["turn_id"] for t in turns],
                    "context_before": opts.context_before,
                    "context_after": opts.context_after,
                    "context_mode": mode,
                }
            )
            item[PROVENANCE_KEY] = provenance
            yield item


def build_items(
    corpus: Corpus,
    opts: Optional[ItemOptions] = None,
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Turn ``corpus`` into a list of Potato items.

    Args:
        corpus: A corpus from :func:`potato.convokit.read_corpus`.
        opts: Shape controls; see :class:`ItemOptions`.
        limit: Stop after this many items.

    Returns:
        Items ready to serialize as a Potato data file. Every item carries a
        :data:`PROVENANCE_KEY` block recording where it came from, which the
        ConvoKit exporter needs to map annotations back onto the corpus.
    """
    opts = opts or ItemOptions()
    opts.validate()

    source = (
        _conversation_items(corpus, opts)
        if opts.unit == "conversation"
        else _utterance_items(corpus, opts)
    )

    items: List[Dict[str, Any]] = []
    for item in source:
        items.append(item)
        if limit is not None and len(items) >= limit:
            break
    return items
