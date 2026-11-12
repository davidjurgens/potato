"""
Reader for Claude Code's on-disk session transcripts.

Claude Code writes one JSONL file per session under
``~/.claude/projects/<slugified-cwd>/<session-uuid>.jsonl``. That file is what
people mean when they say "Claude Code export", and it is *not* the Anthropic
Messages API shape the sibling converter reads. Measured against a real
1369-line session (CLI 2.1.233):

* 12 record ``type``s, of which only ``user``, ``assistant`` and ``system``
  carry conversation. The rest is editor bookkeeping — ``file-history-snapshot``,
  ``file-history-delta``, ``permission-mode``, ``queue-operation``,
  ``custom-title``, ``last-prompt``, ``agent-name``, ``attachment``, ``mode``.
* Content blocks are ``text``, ``tool_use``, ``tool_result`` and ``thinking``.
  Extended thinking is on disk (121 blocks in that session).
* ``parentUuid`` makes the file a **DAG, not a list**. Rewinds and edits branch
  it, so reading it as a flat sequence silently folds abandoned attempts into
  the transcript as though they had happened.
* ``isSidechain`` marks sub-agent transcripts, interleaved with the main one.
* Each assistant message carries ``usage`` (input/output plus cache reads and
  creations, service tier).
* Rows carry ``cwd``, ``gitBranch``, ``version`` and ``sessionId``.

The format is versioned per row for a reason: it belongs to the CLI, not to a
published contract. This reader is deliberately tolerant — unknown record types
are ignored, missing fields degrade to empty — but never silent: a transcript
that yields nothing raises rather than producing an empty trace.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Record types that carry conversation. Everything else is CLI bookkeeping.
CONVERSATION_TYPES = frozenset({"user", "assistant"})

#: Fields whose presence identifies a transcript row.
_SIGNATURE_FIELDS = ("uuid", "sessionId")


def looks_like_session_transcript(rows: Any) -> bool:
    """True when ``rows`` are Claude Code transcript records.

    Deliberately strict about the signature (a uuid *and* a sessionId on a
    conversation row) so a Messages-API payload that happens to carry a
    ``uuid`` is not mistaken for a transcript.
    """
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if all(f in row for f in _SIGNATURE_FIELDS) and \
                row.get("type") in CONVERSATION_TYPES:
            return True
    return False


def _live_chain(rows: List[dict]) -> List[dict]:
    """The surviving conversation, newest leaf back to the root.

    Rewinding in Claude Code branches the DAG: the abandoned messages stay in
    the file with their own parent links. Walking ``parentUuid`` back from the
    last recorded row keeps exactly the path that is still live, which is what
    an annotator is being shown when they resume the session.
    """
    by_uuid = {r["uuid"]: r for r in rows if isinstance(r.get("uuid"), str)}
    if not by_uuid:
        return []

    # The last conversation row in file order is the newest leaf: Claude Code
    # appends, so file order is arrival order even across branches.
    leaf = None
    for row in rows:
        if row.get("type") in CONVERSATION_TYPES and row.get("uuid") in by_uuid:
            leaf = row
    if leaf is None:
        return []

    chain: List[dict] = []
    seen = set()
    cursor: Optional[dict] = leaf
    while cursor is not None:
        uid = cursor.get("uuid")
        if uid in seen:            # defensive: a cycle would hang the walk
            break
        seen.add(uid)
        chain.append(cursor)
        parent_uuid = cursor.get("parentUuid")
        cursor = by_uuid.get(parent_uuid) if parent_uuid else None

    chain.reverse()
    return chain


def _text_of(content: Any) -> str:
    """Plain text of a message's content, ignoring tool traffic."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(p for p in parts if p).strip()


def _is_tool_result_only(message: dict) -> bool:
    """A 'user' row that is really a tool result being fed back."""
    content = message.get("content")
    if not isinstance(content, list) or not content:
        return False
    return all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def to_messages(chain: List[dict]) -> List[Dict[str, Any]]:
    """Messages-API-shaped messages, for the existing block extraction.

    Command output and other CLI-injected rows (``isMeta``) are dropped: they
    are not things the user or the model said, and counting them as user turns
    puts text in the transcript that nobody typed.
    """
    messages = []
    for row in chain:
        if row.get("isMeta"):
            continue
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role") or row.get("type")
        if role not in ("user", "assistant"):
            continue
        messages.append({"role": role, "content": message.get("content", "")})
    return messages


#: Slash commands and their output are stored as user messages wrapped in
#: these envelopes. They are the CLI talking to itself, not the request.
_COMMAND_ENVELOPES = ("<command-name>", "<command-message>",
                      "<local-command-stdout>", "<local-command-stderr>")


def is_command_envelope(text: str) -> bool:
    return any(marker in text for marker in _COMMAND_ENVELOPES)


def first_user_prompt(chain: List[dict]) -> str:
    """The request the session started from.

    Skips slash-command envelopes: a session that opened with `/clear` would
    otherwise be titled with the text of that command rather than with what
    the user actually asked for.
    """
    for row in chain:
        if row.get("type") != "user" or row.get("isMeta"):
            continue
        message = row.get("message")
        if not isinstance(message, dict) or _is_tool_result_only(message):
            continue
        text = _text_of(message.get("content"))
        if text and not is_command_envelope(text):
            return text
    return ""


def count_thinking_blocks(rows: List[dict]) -> int:
    """How many thinking blocks the transcript holds.

    Worth reporting because the *text* is not there: across 40 local sessions,
    6393 thinking blocks and not one with content — the file keeps the block
    and its signature and drops what was thought. Anyone who needs reasoning
    traces has to capture them from the stream, not read them back off disk.
    """
    count = 0
    for row in rows:
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            count += sum(1 for b in content
                         if isinstance(b, dict) and b.get("type") == "thinking")
    return count


def _sum_usage(rows: List[dict]) -> Dict[str, int]:
    """Token totals across the session's assistant messages."""
    keys = ("input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens")
    totals = {k: 0 for k in keys}
    for row in rows:
        message = row.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
    return {k: v for k, v in totals.items() if v}


def _group_sidechains(rows: List[dict]) -> List[Dict[str, Any]]:
    """Sub-agent transcripts, one entry per sidechain root.

    Kept separate rather than spliced into the main conversation: a sub-agent's
    messages are a different agent's work, and folding them in would attribute
    them to the session's own assistant turns.
    """
    side = [r for r in rows if r.get("isSidechain")]
    if not side:
        return []
    by_uuid = {r["uuid"]: r for r in side if isinstance(r.get("uuid"), str)}

    def root_of(row):
        cursor, seen = row, set()
        while cursor is not None:
            uid = cursor.get("uuid")
            if uid in seen:
                break
            seen.add(uid)
            parent = by_uuid.get(cursor.get("parentUuid"))
            if parent is None:
                return uid
            cursor = parent
        return row.get("uuid")

    runs: Dict[str, List[dict]] = {}
    for row in side:
        runs.setdefault(root_of(row), []).append(row)
    return [{"run_id": run_id, "messages": to_messages(chain)}
            for run_id, chain in runs.items()]


def parse_sessions(rows: List[dict]) -> List[Dict[str, Any]]:
    """Split transcript rows into one parsed session per sessionId.

    Returns dicts with ``session_id``, ``messages`` (Messages-API shaped),
    ``task_description``, ``metadata`` and ``sidechains``. Building the
    Messages shape here means the tool_use/tool_result pairing already written
    for the API format is reused rather than re-implemented.
    """
    by_session: Dict[str, List[dict]] = {}
    unattributed: List[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        session_id = row.get("sessionId")
        if session_id:
            by_session.setdefault(session_id, []).append(row)
        else:
            # File-level bookkeeping (`file-history-snapshot`,
            # `file-history-delta`) carries no sessionId. Grouping it under ""
            # invents a session with no messages in it, which then trips the
            # empty-transcript error on a perfectly good file.
            unattributed.append(row)
    if not by_session and unattributed:
        by_session[""] = unattributed

    sessions = []
    for session_id, session_rows in by_session.items():
        main = [r for r in session_rows if not r.get("isSidechain")]
        chain = _live_chain(main)
        assistant_rows = [r for r in chain if r.get("type") == "assistant"]

        metadata: Dict[str, Any] = {}
        for key, field in (("session_id", None), ("cwd", "cwd"),
                           ("git_branch", "gitBranch"), ("cli_version", "version")):
            if field is None:
                metadata["session_id"] = session_id
                continue
            for row in reversed(session_rows):
                if row.get(field):
                    metadata[key] = row[field]
                    break
        for row in reversed(assistant_rows):
            message = row.get("message")
            if isinstance(message, dict) and message.get("model"):
                metadata["model"] = message["model"]
                break
        metadata.update(_sum_usage(assistant_rows))
        thinking = count_thinking_blocks(chain)
        if thinking:
            metadata["thinking_blocks"] = thinking
        # Only conversation rows count as abandoned: the bookkeeping records
        # are not on the parent chain to begin with, and counting them made a
        # healthy transcript look like it had lost a quarter of itself.
        on_chain = {r.get("uuid") for r in chain}
        dropped = sum(1 for r in main
                      if r.get("type") in CONVERSATION_TYPES
                      and r.get("uuid") not in on_chain)
        if dropped > 0:
            # Rewound branches are not an error, but a silent difference
            # between the file's line count and the trace's turn count is
            # exactly the kind of thing that gets mistaken for data loss.
            metadata["abandoned_branch_records"] = dropped

        sessions.append({
            "session_id": session_id,
            "messages": to_messages(chain),
            "task_description": first_user_prompt(chain),
            "metadata": metadata,
            "sidechains": _group_sidechains(session_rows),
        })
    return sessions
