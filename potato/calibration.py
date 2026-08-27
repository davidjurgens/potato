"""
Calibration rounds: pushing annotators back through training mid-study.

The methodological finding this exists for is that calibration sessions --
annotators working through pre-annotated items and arguing about the
disagreements -- produce large gains in inter-annotator agreement, and that the
gain only holds if the calibration is **repeated**, because guidelines drift as
soon as new edge cases turn up.

Potato had the machinery and could only fire it once. ``TRAINING`` was a
one-shot gate between ``INSTRUCTIONS`` and ``ANNOTATION``: a user who passed it
could never be sent back, so "re-calibrate periodically" was not expressible.

What a round does
-----------------
Resets each named annotator's :class:`~potato.user_state_management.TrainingState`
and returns them to ``UserPhase.TRAINING``. They work through the configured
training items again, graded against the same correct answers, and rejoin
annotation where they left off -- their assignments and their existing
annotations are untouched.

Why it re-runs the *training* set rather than the disagreements
--------------------------------------------------------------
A disagreement item has no right answer -- that is what makes it a
disagreement. The training phase grades every answer against
``get_training_correct_answers``, so pointing it at the adjudication queue
would grade annotators against nothing and report the result as if it meant
something. Reviewing disagreements is a real and separate need, and
``/admin/adjudicate`` already does it with the right affordances.

So a round is: re-run the exercise whose answers are known, and check whether
the team still passes it. That is the measurable half of re-calibration.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, List, Optional

from potato.persistence import Migration, get_db, register_migration
from potato.phase import UserPhase

logger = logging.getLogger(__name__)

_CALIBRATION_MIGRATION = Migration(
    name="0001_calibration_rounds",
    sql="""
    CREATE TABLE IF NOT EXISTS calibration_rounds (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project     TEXT NOT NULL,
        started_at  REAL NOT NULL,
        started_by  TEXT NOT NULL,
        reason      TEXT NOT NULL DEFAULT '',
        usernames   TEXT NOT NULL,
        closed_at   REAL
    );
    CREATE INDEX IF NOT EXISTS idx_calibration_project
        ON calibration_rounds (project, started_at DESC);
    """,
)

register_migration(_CALIBRATION_MIGRATION)


def _db(task_dir: str):
    register_migration(_CALIBRATION_MIGRATION)
    return get_db(task_dir)


def eligible_users(user_state_manager) -> List[str]:
    """
    Annotators a round can be started for: everyone past the training gate.

    Someone still in CONSENT or INSTRUCTIONS has not been calibrated once yet,
    and sending them "back" to training would skip the phases in between.
    """
    eligible = []
    for user_id in list(getattr(user_state_manager, "user_to_annotation_state", {})):
        try:
            state = user_state_manager.get_user_state(user_id)
        except Exception:
            continue
        if state is None:
            continue
        phase = state.get_phase()
        if phase in (UserPhase.ANNOTATION, UserPhase.POSTSTUDY, UserPhase.DONE):
            eligible.append(user_id)
    return sorted(eligible)


def start_round(config: Dict[str, Any], user_state_manager,
                usernames: Iterable[str], started_by: str,
                reason: str = "") -> Dict[str, Any]:
    """
    Send the named annotators back through training.

    Args:
        usernames: Who to recall. Names that are not eligible are skipped and
            returned under ``skipped`` rather than silently dropped -- an admin
            who recalls twelve people needs to know that two of them are still
            on the consent page.
        started_by: The admin's username, recorded with the round.
        reason: Free text, usually which schema's agreement fell.

    Returns:
        ``{"round_id", "recalled": [...], "skipped": {user: why}}``

    Raises:
        ValueError: If training is not configured. Recalling annotators to a
            phase that immediately advances past itself would look like the
            feature silently did nothing.
    """
    if not (config.get("training") or {}).get("enabled", False):
        raise ValueError(
            "Calibration rounds re-run the training exercise, but `training` "
            "is not enabled in this config. There is nothing to send "
            "annotators back to."
        )

    allowed = set(eligible_users(user_state_manager))
    recalled: List[str] = []
    skipped: Dict[str, str] = {}

    for username in usernames:
        if username not in allowed:
            skipped[username] = (
                "not past the training gate yet, so there is nothing to repeat")
            continue
        try:
            _recall(user_state_manager, username)
        except Exception as exc:
            logger.exception("Could not recall %s for calibration", username)
            skipped[username] = str(exc)
            continue
        recalled.append(username)

    round_id = _record(config, started_by, reason, recalled)
    logger.info("Calibration round %s recalled %d annotator(s): %s",
                round_id, len(recalled), ", ".join(recalled) or "none")
    return {"round_id": round_id, "recalled": recalled, "skipped": skipped}


def _recall(user_state_manager, username: str) -> None:
    """
    Reset one annotator's training state and put them back in TRAINING.

    The training state is reset rather than reused: ``passed`` is sticky, and a
    user who arrived at TRAINING already marked as passed would be advanced
    straight back out on their next request, so the round would appear to have
    done nothing at all.

    Assignments and saved annotations are deliberately untouched. A calibration
    round asks the annotator to re-do the exercise, not to re-do the study.
    """
    user_state = user_state_manager.get_user_state(username)
    if user_state is None:
        raise ValueError(f"no state for user {username}")

    training_state = user_state.get_training_state()
    training_state.completed_questions = {}
    training_state.total_correct = 0
    training_state.total_attempts = 0
    training_state.total_mistakes = 0
    training_state.passed = False
    training_state.failed = False
    training_state.current_question_index = 0
    training_state.clear_feedback()
    # Left populated so the round uses the same items as the first pass. The
    # training route re-seeds it only when empty, so clearing it here would
    # re-read the training file and could hand out a different set.

    user_state.advance_to_phase(UserPhase.TRAINING, None)


def _record(config: Dict[str, Any], started_by: str, reason: str,
            usernames: List[str]) -> Optional[int]:
    """Persist the round. Returns its id, or None if the DB is unavailable."""
    try:
        conn = _db(config.get("task_dir", "."))
        cursor = conn.execute(
            """INSERT INTO calibration_rounds
                   (project, started_at, started_by, reason, usernames)
               VALUES (?, ?, ?, ?, ?)""",
            (config.get("annotation_task_name", "default"), time.time(),
             started_by, reason, json.dumps(usernames)),
        )
        conn.commit()
        return int(cursor.lastrowid)
    except Exception:
        # A round that ran but was not logged is far better than an exception
        # after the annotators have already been moved.
        logger.exception("Calibration round could not be recorded")
        return None


def round_history(config: Dict[str, Any], limit: int = 20) -> List[dict]:
    """Past calibration rounds, newest first."""
    try:
        rows = _db(config.get("task_dir", ".")).execute(
            """SELECT id, started_at, started_by, reason, usernames, closed_at
               FROM calibration_rounds WHERE project = ?
               ORDER BY started_at DESC LIMIT ?""",
            (config.get("annotation_task_name", "default"), int(limit)),
        ).fetchall()
    except Exception:
        logger.debug("Could not read calibration rounds", exc_info=True)
        return []

    history = []
    for row in rows:
        try:
            usernames = json.loads(row["usernames"])
        except (TypeError, ValueError):
            usernames = []
        history.append({
            "id": int(row["id"]),
            "started_at": float(row["started_at"]),
            "started_by": row["started_by"],
            "reason": row["reason"] or "",
            "usernames": usernames,
            "closed_at": row["closed_at"],
        })
    return history


def round_progress(user_state_manager, usernames: Iterable[str]) -> List[dict]:
    """
    Where each recalled annotator has got to.

    ``state`` is one of ``passed``, ``failed``, ``in_progress`` or ``unknown``.
    """
    progress = []
    for username in usernames:
        try:
            user_state = user_state_manager.get_user_state(username)
            training = user_state.get_training_state() if user_state else None
        except Exception:
            training = None

        if training is None:
            progress.append({"username": username, "state": "unknown",
                             "answered": 0, "total": 0, "correct": 0})
            continue

        if training.passed:
            state = "passed"
        elif training.failed:
            state = "failed"
        else:
            state = "in_progress"
        progress.append({
            "username": username,
            "state": state,
            "answered": len(training.completed_questions),
            "total": len(training.training_instances),
            "correct": training.total_correct,
        })
    return progress
