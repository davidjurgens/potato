"""
Authenticity paradata: did the annotator do this item here, themselves?

Page-level, content-blind signals for every task type -- not just free text.
Keystroke logging (potato/typing_detect.py) can tell how a *response* was
produced; it says nothing about a Likert, radio, span or ranking item, where the
whole of an outsourced answer is "copy the item, ask a chatbot, come back, click".
This module covers that path.

The browser (static/authenticity_tracker.js) keeps one running snapshot per view
of an item -- counts, durations and maxima, never text -- and posts it
periodically. The server sanitizes it, folds the views of one item together and
evaluates the flags below. Thresholds stay here and are never sent to the page.

Design commitments are the ones typing_detect.py states, and for the same
reasons: **flags, not a score**; each flag carries the numbers behind it;
**flags are evidence for human review, never an automatic rejection.**

Grounding for the individual rules
----------------------------------
- ``copy_then_paste``: "A Penny for Your Prompts" (arXiv:2607.00403, 2026) --
  copying survey text and pasting external text of 10+ words was the core
  heuristic for LLM use. A single copy or paste on its own is not diagnostic
  (30.7% of responses had one), which is why ``item_copied`` and
  ``external_paste`` are only ``review``.
- ``copy_then_away``: the same workflow on a closed-format item, where there is
  nothing to paste back: copy the item, leave the page, return and answer.
- ``away_from_task``: tab switching is a weak signal on its own (F1 = .545 in
  the same paper), so it is ``review`` only and excludes time spent in pages
  the task itself opened (the codebook link).
- ``copy_then_away`` needs the copy to be a real piece of the item (40+
  characters) and the absence to start soon after it (60 s): copying a word to
  look it up, then taking a phone call five minutes later, is not the workflow.
- ``automation``: ``navigator.webdriver``, which a driven browser sets.
- ``synthetic_input``: pointer/key events the browser marks
  ``isTrusted = false``. Potato itself never synthesizes those event types, but
  browser extensions (keyboard navigation, accessibility tools) can, so it is
  ``review`` and needs several events.
- ``pointer_teleport``: a real mouse cannot change position without emitting
  pointermove; scripted clicks (CDP, many browser agents) commonly do.
- ``split_screen``: a browser window much narrower than the screen is the usual
  setup for working with a chatbot open beside the task. Weak, ``review`` only.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional

from potato.typing_detect import Flag, Verdict

logger = logging.getLogger(__name__)

#: Version of the snapshot vocabulary. Bumped when a field changes meaning.
SCHEMA_VERSION = 1

#: Summed across views of one item.
COUNT_FIELDS = (
    "elapsed_ms",
    "hidden_events", "hidden_ms",        # tab/page hidden (switched tab, minimized)
    "blur_events", "blur_ms",            # page visible but window unfocused (other window)
    "linked_away_events", "linked_away_ms",  # away in a page the task opened itself
    "item_copy_events", "item_copy_chars",
    "other_copy_events", "cut_events",
    "item_select_events", "item_context_menu_events",
    "paste_events", "external_paste_events", "external_paste_words",
    "item_paste_events",
    "resize_events", "zoom_changes",
    "pointer_moves", "pointer_distance_px",
    "mouse_clicks", "teleport_clicks",
    "untrusted_events",
)

#: Maximum across views.
MAX_FIELDS = (
    "max_away_ms",
    "max_external_paste_words",
    "max_away_after_item_copy_ms",
    "max_paste_words_after_item_copy",
)

#: Minimum across views (ratios; 1.0 = window as wide as the screen).
MIN_FIELDS = ("min_window_ratio",)

#: True if true in any view.
BOOL_FIELDS = ("webdriver", "touch_input", "large_screen")

#: One ``[gap_ms, away_ms, copy_chars]`` per absence that began after an item
#: copy: how long after the copy the annotator left, for how long, and how much
#: of the item the copy held. Pairs rather than maxima, because whether an
#: absence counts depends on all three at once and the thresholds stay here.
PAIR_FIELDS = ("copy_away_pairs",)

#: Pairs kept per view, and per item after merging views.
MAX_PAIRS_PER_VIEW = 20
MAX_PAIRS_PER_ITEM = 200

#: Upper bound on any count or duration from the client. Generous (11+ days in
#: ms) -- it exists to keep a malformed payload from poisoning a sum, not to
#: second-guess plausible values.
_MAX_VALUE = 1_000_000_000

#: Views stored per item. A view is one load of the item; nobody legitimately
#: reloads an item fifty times, and the cap keeps user_state.json bounded.
MAX_VIEWS_PER_ITEM = 50

_VIEW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Default thresholds. Conservative for the same reason as typing_detect's: a
#: missed case costs one row, a false accusation costs an annotator.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    # Words of external text pasted after the item was copied.
    "copy_then_paste.min_words": 10,
    # Time away from the page after the item was copied...
    "copy_then_away.min_away_ms": 10000,
    # ...when the copy held at least this much of the item...
    "copy_then_away.min_copy_chars": 40,
    # ...and the absence began within this long of the copy.
    "copy_then_away.max_gap_ms": 60000,
    # Words in the largest external paste (without a preceding item copy).
    "external_paste.min_words": 10,
    # Characters of item text copied.
    "item_copied.min_chars": 40,
    # Times the annotator left the page during one item...
    "away_from_task.min_events": 3,
    # ...or total time away, when it is also most of the time on the item.
    "away_from_task.min_ms": 60000,
    "away_from_task.min_fraction": 0.5,
    # Browser window width as a fraction of the screen's available width.
    "split_screen.max_window_ratio": 0.6,
    # Mouse clicks at a new position with no pointer movement in between.
    "pointer_teleport.min_clicks": 3,
    # Script-generated (isTrusted=false) pointer/key events.
    "synthetic_input.min_events": 3,
}


def _threshold(key: str, overrides: Optional[Dict[str, float]]) -> float:
    if overrides and key in overrides:
        try:
            return float(overrides[key])
        except (TypeError, ValueError):
            logger.warning("Ignoring non-numeric authenticity threshold %s", key)
    return DEFAULT_THRESHOLDS[key]


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value:  # NaN
        return None
    return float(value)


def valid_view_id(view_id: Any) -> bool:
    return isinstance(view_id, str) and bool(_VIEW_ID_RE.match(view_id))


def sanitize_snapshot(raw: Any) -> Dict[str, Any]:
    """Keep only known fields, coerced to the expected type and range.

    The snapshot comes from the browser and is therefore untrusted: unknown keys
    are dropped (so nothing content-bearing can ride along), counts are clamped
    to ``[0, _MAX_VALUE]`` and ratios to ``[0, 2]``.
    """
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in COUNT_FIELDS + MAX_FIELDS:
        v = _num(raw.get(key))
        if v is not None:
            out[key] = int(min(max(v, 0), _MAX_VALUE))
    for key in MIN_FIELDS:
        v = _num(raw.get(key))
        if v is not None and v > 0:
            out[key] = round(min(v, 2.0), 3)
    for key in BOOL_FIELDS:
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    for key in PAIR_FIELDS:
        pairs = _sanitize_pairs(raw.get(key), MAX_PAIRS_PER_VIEW)
        if pairs:
            out[key] = pairs
    return out


def _sanitize_pairs(value: Any, limit: int) -> List[List[int]]:
    """Up to ``limit`` well-formed ``[gap_ms, away_ms, copy_chars]`` triples."""
    if not isinstance(value, list):
        return []
    pairs = []
    for entry in value:
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            continue
        nums = [_num(v) for v in entry]
        if any(n is None for n in nums):
            continue
        pairs.append([int(min(max(n, 0), _MAX_VALUE)) for n in nums])
        if len(pairs) >= limit:
            break
    return pairs


def merge_snapshots(snapshots: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Fold several views of one item into a single summary."""
    merged: Dict[str, Any] = {k: 0 for k in COUNT_FIELDS + MAX_FIELDS}
    mins: Dict[str, Optional[float]] = {k: None for k in MIN_FIELDS}
    bools: Dict[str, bool] = {k: False for k in BOOL_FIELDS}
    pairs: List[List[int]] = []
    views = 0
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        views += 1
        for k in COUNT_FIELDS:
            merged[k] += int(snap.get(k) or 0)
        for k in MAX_FIELDS:
            merged[k] = max(merged[k], int(snap.get(k) or 0))
        for k in MIN_FIELDS:
            v = snap.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                mins[k] = v if mins[k] is None else min(mins[k], v)
        for k in BOOL_FIELDS:
            bools[k] = bools[k] or bool(snap.get(k))
        pairs.extend(_sanitize_pairs(snap.get("copy_away_pairs"), MAX_PAIRS_PER_VIEW))
    merged.update({k: v for k, v in mins.items() if v is not None})
    merged.update(bools)
    # Longest absences first, so the cap drops the ones least likely to matter.
    pairs.sort(key=lambda p: -p[1])
    merged["copy_away_pairs"] = pairs[:MAX_PAIRS_PER_ITEM]
    merged["views"] = views
    merged["away_ms"] = merged["hidden_ms"] + merged["blur_ms"]
    merged["away_events"] = merged["hidden_events"] + merged["blur_events"]
    merged["schema_version"] = SCHEMA_VERSION
    return merged


def evaluate(summary: Dict[str, Any], *,
             thresholds: Optional[Dict[str, float]] = None) -> Verdict:
    """Apply the rule-based flags to one item's merged summary."""
    s = summary or {}
    t = lambda key: _threshold(key, thresholds)  # noqa: E731
    verdict = Verdict()
    flags: List[Flag] = []

    if s.get("webdriver"):
        flags.append(Flag(
            name="automation",
            explanation=("The browser reported automation: navigator.webdriver "
                         "was set."),
            evidence={"webdriver": True,
                      "untrusted_events": s.get("untrusted_events", 0)},
            severity="suspect",
        ))

    untrusted = s.get("untrusted_events", 0) or 0
    if untrusted >= t("synthetic_input.min_events"):
        flags.append(Flag(
            name="synthetic_input",
            explanation=(
                f"{untrusted} pointer/key event(s) were script-generated "
                "(isTrusted=false). A browser extension can produce these, as "
                "can an automation tool."),
            evidence={"untrusted_events": untrusted},
            severity="review",
        ))

    item_copies = s.get("item_copy_events", 0) or 0
    paste_after_copy = s.get("max_paste_words_after_item_copy", 0) or 0
    # Both halves must be present: the paste field alone is one client number.
    copy_then_paste = (item_copies > 0
                       and paste_after_copy >= t("copy_then_paste.min_words"))
    if copy_then_paste:
        flags.append(Flag(
            name="copy_then_paste",
            explanation=(
                f"Copied the item text, then pasted {paste_after_copy} words of "
                "text that did not come from this page."),
            evidence={"item_copy_events": s.get("item_copy_events", 0),
                      "paste_words_after_item_copy": paste_after_copy},
            severity="suspect",
        ))

    # One absence that satisfies all three conditions together; separate
    # maxima could pair a long copy with an unrelated absence much later.
    matching = [
        p for p in (s.get("copy_away_pairs") or [])
        if isinstance(p, (list, tuple)) and len(p) == 3
        and p[0] <= t("copy_then_away.max_gap_ms")
        and p[1] >= t("copy_then_away.min_away_ms")
        and p[2] >= t("copy_then_away.min_copy_chars")]
    copy_then_away = not copy_then_paste and item_copies > 0 and bool(matching)
    if copy_then_away:
        gap_ms, away_ms, copy_chars = max(matching, key=lambda p: p[1])
        flags.append(Flag(
            name="copy_then_away",
            explanation=(
                f"Copied {copy_chars} characters of the item text, left the page "
                f"{gap_ms / 1000:.1f}s later and stayed away for "
                f"{away_ms / 1000:.1f}s."),
            evidence={"item_copy_events": item_copies,
                      "copy_chars": copy_chars,
                      "gap_after_copy_ms": gap_ms,
                      "away_ms": away_ms,
                      "matching_absences": len(matching)},
            severity="suspect",
        ))

    max_paste = s.get("max_external_paste_words", 0) or 0
    if not copy_then_paste and max_paste >= t("external_paste.min_words"):
        flags.append(Flag(
            name="external_paste",
            explanation=(
                f"Pasted {max_paste} words of text that did not come from this "
                "page."),
            evidence={"external_paste_events": s.get("external_paste_events", 0),
                      "max_external_paste_words": max_paste},
            severity="review",
        ))

    copied_chars = s.get("item_copy_chars", 0) or 0
    if (not copy_then_paste and not copy_then_away
            and copied_chars >= t("item_copied.min_chars")):
        flags.append(Flag(
            name="item_copied",
            explanation=f"Copied {copied_chars} characters of the item text.",
            evidence={"item_copy_events": s.get("item_copy_events", 0),
                      "item_copy_chars": copied_chars},
            severity="review",
        ))

    away_events = s.get("away_events", 0) or 0
    away_ms = s.get("away_ms", 0) or 0
    elapsed = s.get("elapsed_ms", 0) or 0
    away_fraction = min(1.0, away_ms / elapsed) if elapsed > 0 else 0.0
    many_switches = away_events >= t("away_from_task.min_events")
    long_away = (away_ms >= t("away_from_task.min_ms")
                 and away_fraction >= t("away_from_task.min_fraction"))
    if many_switches or long_away:
        flags.append(Flag(
            name="away_from_task",
            explanation=(
                f"Left the page {away_events} time(s), {away_ms / 1000:.1f}s in "
                f"total ({away_fraction:.0%} of the time on this item)."),
            evidence={"away_events": away_events, "away_ms": away_ms,
                      "away_fraction": round(away_fraction, 3),
                      "hidden_events": s.get("hidden_events", 0),
                      "blur_events": s.get("blur_events", 0),
                      "linked_away_events_excluded": s.get("linked_away_events", 0)},
            severity="review",
        ))

    ratio = s.get("min_window_ratio")
    if (isinstance(ratio, (int, float)) and s.get("large_screen")
            and not s.get("touch_input")
            and ratio <= t("split_screen.max_window_ratio")):
        flags.append(Flag(
            name="split_screen",
            explanation=(
                f"The browser window was {ratio:.0%} of the screen width, "
                "leaving room for another window beside the task."),
            evidence={"min_window_ratio": ratio},
            severity="review",
        ))

    teleports = s.get("teleport_clicks", 0) or 0
    if teleports >= t("pointer_teleport.min_clicks"):
        flags.append(Flag(
            name="pointer_teleport",
            explanation=(
                f"{teleports} of {s.get('mouse_clicks', 0)} mouse clicks landed at "
                "a new position with no pointer movement in between, which a "
                "physical mouse cannot do."),
            evidence={"teleport_clicks": teleports,
                      "mouse_clicks": s.get("mouse_clicks", 0),
                      "pointer_moves": s.get("pointer_moves", 0)},
            severity="review",
        ))

    verdict.flags = flags
    if any(f.severity == "suspect" for f in flags):
        verdict.level = "suspect"
    elif flags:
        verdict.level = "review"
    if s.get("touch_input"):
        verdict.notes.append("touch input: pointer-based rules may not apply")
    return verdict


def record_view(store: Dict[str, Any], view_id: str, snapshot: Dict[str, Any],
                *, now: float, phase: Optional[str] = None,
                page: Optional[str] = None,
                thresholds: Optional[Dict[str, float]] = None,
                detection: bool = True) -> Dict[str, Any]:
    """Store one view's snapshot in an item's authenticity record and re-merge.

    ``store`` is the item's ``BehavioralData.authenticity`` dict (may be empty).
    A snapshot *replaces* the previous one for the same view -- the client sends
    running totals -- so a retried or duplicated post cannot double-count.
    Returns the updated record.
    """
    record = dict(store or {})
    views = dict(record.get("views") or {})
    existing = views.get(view_id)
    if existing is None and len(views) >= MAX_VIEWS_PER_ITEM:
        logger.warning("Authenticity view cap reached for an item; ignoring view %s",
                       view_id)
        return record
    entry = dict(existing or {"first_seen": now})
    entry["last_seen"] = now
    entry["snapshot"] = snapshot
    if phase is not None:
        entry["phase"] = phase
    if page is not None:
        entry["page"] = page
    views[view_id] = entry
    record["views"] = views

    summary = merge_snapshots(v.get("snapshot") for v in views.values())
    # Server-observed span of each view: a bound the client cannot inflate.
    summary["server_span_ms"] = int(sum(
        max(0.0, (v.get("last_seen") or 0) - (v.get("first_seen") or 0)) * 1000
        for v in views.values()))
    record["summary"] = summary
    if detection:
        record["verdict"] = evaluate(summary, thresholds=thresholds).to_dict()
    else:
        record.pop("verdict", None)
    return record


# --------------------------------------------------------------------------
# Write buffering
# --------------------------------------------------------------------------

#: Longest an ordinary snapshot stays in memory only. The browser posts every
#: few seconds while anything changes, and each write rewrites the whole of
#: user_state.json, so ordinary posts update the in-memory record and reach
#: disk at most this often (or with the next annotation save, whichever is
#: first). A crash loses at most this much paradata, never an annotation.
PERSIST_INTERVAL_S = 60.0


class PersistThrottle:
    """Decides, per annotator, whether an authenticity post is written to disk."""

    def __init__(self) -> None:
        self._last: Dict[str, float] = {}
        #: Annotators with a post held in memory and not yet written.
        self._pending: set = set()
        self._lock = threading.Lock()

    def should_persist(self, user_id: str, *, now: float, urgent: bool) -> bool:
        """True if this post should be written now; records the write if so.

        ``urgent`` posts -- the last of a view, or one that changed the item's
        flags -- are always written: nothing may follow
        them. The rest are written once :data:`PERSIST_INTERVAL_S` has passed
        since this annotator's last write; until then they live in memory and
        go to disk with the next write of any kind.
        """
        with self._lock:
            last = self._last.get(user_id)
            if not urgent and last is not None and now - last < PERSIST_INTERVAL_S:
                self._pending.add(user_id)
                return False
            self._last[user_id] = now
            self._pending.discard(user_id)
            return True

    def take_pending(self) -> List[str]:
        """The annotators with unwritten posts; clears the set."""
        with self._lock:
            pending = sorted(self._pending)
            self._pending.clear()
            return pending

    def reset(self) -> None:
        with self._lock:
            self._last.clear()
            self._pending.clear()


persist_throttle = PersistThrottle()


def clear_persist_throttle() -> None:
    """Forget every annotator's last write (test harness, between servers)."""
    persist_throttle.reset()


def flag_names(record: Dict[str, Any]) -> List[str]:
    """The flag names of a stored record's verdict, or ``[]``."""
    verdict = (record or {}).get("verdict") or {}
    return list(verdict.get("flag_names") or [])


def flush_pending(save: Callable[[str], None]) -> int:
    """Write every annotator whose last posts are held in memory only.

    ``save`` writes one annotator's state (``UserStateManager.save_user_state``
    takes a username). Returns how many were written; never raises, because it
    runs at shutdown.
    """
    written = 0
    for user_id in persist_throttle.take_pending():
        try:
            save(user_id)
            written += 1
        except Exception as e:  # noqa: BLE001 - shutdown must not raise
            logger.warning("Could not write buffered authenticity data for %s: %s",
                           user_id, e)
    return written


_shutdown_flush_installed = False


def install_shutdown_flush(save: Callable[[str], None]) -> None:
    """Write buffered posts when the server stops.

    Registered with atexit, and SIGTERM is turned into a normal exit so atexit
    runs: Python runs atexit on a normal exit and on Ctrl-C, but not on a
    SIGTERM it has no handler for, and SIGTERM is what ``systemctl stop``,
    ``docker stop`` and ``kill`` send. A previous SIGTERM handler is chained,
    as in coding_agent_runner_manager. Signal handlers can only be installed
    from the main thread; elsewhere only the atexit hook is registered.
    """
    global _shutdown_flush_installed
    if _shutdown_flush_installed:
        return
    _shutdown_flush_installed = True

    import atexit
    import signal

    atexit.register(flush_pending, save)
    try:
        if threading.current_thread() is not threading.main_thread():
            return
        previous = signal.getsignal(signal.SIGTERM)

        def _terminate(signum, frame):
            try:
                flush_pending(save)
            finally:
                if callable(previous) and previous not in (
                        signal.SIG_DFL, signal.SIG_IGN):
                    previous(signum, frame)
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, _terminate)
    except (ValueError, OSError, AttributeError) as e:
        logger.debug("Could not install a SIGTERM handler: %s", e)
