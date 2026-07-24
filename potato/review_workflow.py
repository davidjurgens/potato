"""
Reviewer routing + kanban review workflow (D4 enterprise parity).

A *parallel* review-state store over annotation instances — the
Braintrust-style review board. Each enrolled instance carries a workflow
state (pending → in_review → needs_second → adjudication → done), an
optional assignee, and a priority. The store is deliberately independent
of ItemStateManager: it never changes what annotators are served, it
tracks *review process* state on top (R5 — assignment internals stay
untouched). The adjudication column hands off to the existing
adjudication UI via the /adjudicate?instance= deep link.

Config::

    review_workflow:
      enabled: true
      reviewers: [alice, bob]      # assignment pool (round-robin default)
      auto_enroll: true            # enroll all loaded instances at startup
      routing:                     # first matching rule wins (optional)
        - when:                    # shared condition grammar (conditions.py)
            - {field: "metadata.outcome", equals: "error"}
          state: in_review
          assign_to: alice         # explicit assignee...
          round_robin: true        # ...or spread over `reviewers`
          priority: 10

Runtime-ingested items enroll via the ``enroll_review`` automation action.

Layers in this module: SQLite store (review_items / review_transitions in
project.sqlite), routing/service functions, and the Flask blueprint
(admin kanban page + APIs + reviewer my-queue).
"""

from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

logger = logging.getLogger(__name__)

#: Review workflow states, in board order.
STATES = ("pending", "in_review", "needs_second", "adjudication", "done")

_REVIEW_MIGRATION = Migration(
    name="0003_review_workflow",
    sql="""
    CREATE TABLE IF NOT EXISTS review_items (
        project     TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        state       TEXT NOT NULL DEFAULT 'pending',
        assignee    TEXT,
        priority    INTEGER NOT NULL DEFAULT 0,
        note        TEXT,
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL,
        PRIMARY KEY (project, instance_id)
    );
    CREATE INDEX IF NOT EXISTS idx_review_items_state
        ON review_items (project, state);

    CREATE TABLE IF NOT EXISTS review_transitions (
        project     TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        from_state  TEXT,
        to_state    TEXT NOT NULL,
        actor       TEXT,
        at          REAL NOT NULL
    );
    """,
)

register_migration(_REVIEW_MIGRATION)


def _db(task_dir: str):
    register_migration(_REVIEW_MIGRATION)
    return get_db(task_dir)


def review_enabled(config: Dict[str, Any]) -> bool:
    return bool((config.get("review_workflow") or {}).get("enabled"))


def _project(config: Dict[str, Any]) -> str:
    return config.get("annotation_task_name") or "default"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def get_review_item(task_dir: str, project: str, instance_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM review_items WHERE project = ? AND instance_id = ?",
        (project, instance_id),
    ).fetchone()
    return dict(row) if row else None


def enroll_instance(
    task_dir: str, *, project: str, instance_id: str,
    state: str = "pending", assignee: Optional[str] = None,
    priority: int = 0, actor: str = "system",
) -> bool:
    """Enroll one instance. Idempotent — an already-enrolled instance is
    left untouched (returns False)."""
    if state not in STATES:
        raise ValueError(f"unknown review state: {state}")
    conn = _db(task_dir)
    now = time.time()
    cur = conn.execute(
        """INSERT OR IGNORE INTO review_items
           (project, instance_id, state, assignee, priority,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (project, str(instance_id), state, assignee, int(priority), now, now),
    )
    created = cur.rowcount > 0
    if created:
        conn.execute(
            """INSERT INTO review_transitions
               (project, instance_id, from_state, to_state, actor, at)
               VALUES (?, ?, NULL, ?, ?, ?)""",
            (project, str(instance_id), state, actor, now),
        )
    conn.commit()
    return created


def move_instance(
    task_dir: str, *, project: str, instance_id: str, state: str,
    actor: str, note: Optional[str] = None,
) -> Dict[str, Any]:
    """Move an enrolled instance to a new state (audit-logged)."""
    if state not in STATES:
        raise ValueError(f"unknown review state: {state}")
    item = get_review_item(task_dir, project, instance_id)
    if item is None:
        raise KeyError(f"instance not enrolled: {instance_id}")
    conn = _db(task_dir)
    now = time.time()
    if note is None:
        conn.execute(
            """UPDATE review_items SET state = ?, updated_at = ?
               WHERE project = ? AND instance_id = ?""",
            (state, now, project, str(instance_id)),
        )
    else:
        conn.execute(
            """UPDATE review_items SET state = ?, note = ?, updated_at = ?
               WHERE project = ? AND instance_id = ?""",
            (state, note, now, project, str(instance_id)),
        )
    if state != item["state"]:
        conn.execute(
            """INSERT INTO review_transitions
               (project, instance_id, from_state, to_state, actor, at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project, str(instance_id), item["state"], state, actor, now),
        )
    conn.commit()
    return get_review_item(task_dir, project, instance_id)


def assign_instance(
    task_dir: str, *, project: str, instance_id: str,
    assignee: Optional[str], priority: Optional[int] = None,
) -> Dict[str, Any]:
    item = get_review_item(task_dir, project, instance_id)
    if item is None:
        raise KeyError(f"instance not enrolled: {instance_id}")
    conn = _db(task_dir)
    if priority is None:
        conn.execute(
            """UPDATE review_items SET assignee = ?, updated_at = ?
               WHERE project = ? AND instance_id = ?""",
            (assignee, time.time(), project, str(instance_id)),
        )
    else:
        conn.execute(
            """UPDATE review_items SET assignee = ?, priority = ?, updated_at = ?
               WHERE project = ? AND instance_id = ?""",
            (assignee, int(priority), time.time(), project, str(instance_id)),
        )
    conn.commit()
    return get_review_item(task_dir, project, instance_id)


def board(task_dir: str, project: str) -> Dict[str, List[Dict[str, Any]]]:
    """The kanban board: state -> items (priority desc, oldest first)."""
    rows = _db(task_dir).execute(
        """SELECT * FROM review_items WHERE project = ?
           ORDER BY priority DESC, created_at ASC""",
        (project,),
    ).fetchall()
    out: Dict[str, List[Dict[str, Any]]] = {s: [] for s in STATES}
    for row in rows:
        d = dict(row)
        out.setdefault(d["state"], []).append(d)
    return out


def my_queue(task_dir: str, project: str, username: str) -> List[Dict[str, Any]]:
    """Open review items assigned to a reviewer (not pending/done)."""
    rows = _db(task_dir).execute(
        """SELECT * FROM review_items
           WHERE project = ? AND assignee = ?
             AND state IN ('in_review', 'needs_second', 'adjudication')
           ORDER BY priority DESC, created_at ASC""",
        (project, username),
    ).fetchall()
    return [dict(r) for r in rows]


def transitions_for(task_dir: str, project: str, instance_id: str) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        """SELECT * FROM review_transitions
           WHERE project = ? AND instance_id = ? ORDER BY at ASC""",
        (project, str(instance_id)),
    ).fetchall()
    return [dict(r) for r in rows]


def _open_counts_by_assignee(task_dir: str, project: str) -> Dict[str, int]:
    rows = _db(task_dir).execute(
        """SELECT assignee, COUNT(*) AS n FROM review_items
           WHERE project = ? AND assignee IS NOT NULL AND state != 'done'
           GROUP BY assignee""",
        (project,),
    ).fetchall()
    return {r["assignee"]: r["n"] for r in rows}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_instance(
    config: Dict[str, Any], instance_id: str, item_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve the initial state/assignee/priority for an instance from the
    configured routing rules (first matching rule wins). Round-robin picks
    the pool reviewer with the fewest open assignments."""
    rw = config.get("review_workflow") or {}
    task_dir = config.get("task_dir", ".")
    project = _project(config)
    resolved = {"state": "pending", "assignee": None, "priority": 0}

    from potato.server_utils.conditions import matches_all
    for rule in rw.get("routing") or []:
        if not isinstance(rule, dict):
            continue
        if not matches_all(rule.get("when"), item_data or {}):
            continue
        state = rule.get("state", "in_review")
        resolved["state"] = state if state in STATES else "in_review"
        resolved["priority"] = int(rule.get("priority", 0))
        if rule.get("assign_to"):
            resolved["assignee"] = str(rule["assign_to"])
        elif rule.get("round_robin"):
            pool = [str(r) for r in (rw.get("reviewers") or [])]
            if pool:
                counts = _open_counts_by_assignee(task_dir, project)
                resolved["assignee"] = min(
                    pool, key=lambda r: (counts.get(r, 0), pool.index(r)))
        break
    return resolved


def enroll_with_routing(
    config: Dict[str, Any], instance_id: str, item_data: Dict[str, Any],
    actor: str = "system",
) -> bool:
    """Enroll one instance, applying routing rules. Idempotent."""
    routed = route_instance(config, instance_id, item_data)
    return enroll_instance(
        config.get("task_dir", "."), project=_project(config),
        instance_id=instance_id, state=routed["state"],
        assignee=routed["assignee"], priority=routed["priority"],
        actor=actor,
    )


def init_review_workflow_from_config(config: Dict[str, Any]) -> Dict[str, int]:
    """Server-start entry point: enroll all loaded instances (idempotent).
    No-op when disabled or ``auto_enroll: false``."""
    if not review_enabled(config):
        return {"enrolled": 0}
    rw = config.get("review_workflow") or {}
    if rw.get("auto_enroll") is False:
        return {"enrolled": 0}

    from potato.item_state_management import get_item_state_manager
    ism = get_item_state_manager()
    enrolled = 0
    for iid in ism.get_instance_ids():
        try:
            data = ism.get_item(iid).get_data()
        except KeyError:
            continue
        if enroll_with_routing(config, str(iid),
                               data if isinstance(data, dict) else {}):
            enrolled += 1
    if enrolled:
        logger.info("Review workflow: enrolled %d instance(s)", enrolled)
    return {"enrolled": enrolled}


# ---------------------------------------------------------------------------
# Blueprint (admin kanban + APIs)
# ---------------------------------------------------------------------------

from flask import Blueprint, jsonify, render_template, request, session  # noqa: E402

review_bp = Blueprint("review_workflow", __name__)


def _config() -> dict:
    from potato.server_utils.config_module import config
    return config


def _admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        from potato.server_utils.rbac import get_rbac_manager, Permission
        if not get_rbac_manager().check(
                Permission.VIEW_ADMIN_DASHBOARD, request, session):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return wrapper


def _enabled_guard(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not review_enabled(_config()):
            return jsonify({
                "error": "Review workflow is not enabled.",
                "hint": "Set review_workflow.enabled: true",
            }), 503
        return f(*args, **kwargs)
    return wrapper


def _preview(instance_id: str) -> str:
    try:
        from potato.item_state_management import get_item_state_manager
        from potato.server_utils.config_module import config
        data = get_item_state_manager().get_item(instance_id).get_data()
        if isinstance(data, dict):
            text_key = (config.get("item_properties") or {}).get("text_key", "text")
            raw = data.get(text_key) or data.get("task_description") or ""
            return str(raw)[:140]
    except Exception:
        pass
    return ""


@review_bp.route("/admin/review", methods=["GET"])
@_enabled_guard
@_admin_required
def review_board_page():
    config = _config()
    rw = config.get("review_workflow") or {}
    return render_template(
        "admin/review_board.html",
        annotation_task_name=config.get("annotation_task_name", "Annotation Task"),
        states=list(STATES),
        reviewers=[str(r) for r in (rw.get("reviewers") or [])],
    )


@review_bp.route("/admin/api/review/board", methods=["GET"])
@_enabled_guard
@_admin_required
def review_board_api():
    config = _config()
    data = board(config.get("task_dir", "."), _project(config))
    for items in data.values():
        for item in items:
            item["preview"] = _preview(item["instance_id"])
    return jsonify({"states": list(STATES), "board": data})


@review_bp.route("/admin/api/review/move", methods=["POST"])
@_enabled_guard
@_admin_required
def review_move_api():
    config = _config()
    payload = request.get_json(silent=True) or {}
    instance_id = payload.get("instance_id")
    state = payload.get("state")
    if not instance_id or state not in STATES:
        return jsonify({"error": f"state must be one of {list(STATES)}"}), 400
    actor = session.get("username") or "admin-api"
    try:
        item = move_instance(
            config.get("task_dir", "."), project=_project(config),
            instance_id=str(instance_id), state=state, actor=actor,
            note=payload.get("note"),
        )
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"item": item})


@review_bp.route("/admin/api/review/assign", methods=["POST"])
@_enabled_guard
@_admin_required
def review_assign_api():
    config = _config()
    payload = request.get_json(silent=True) or {}
    instance_id = payload.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id required"}), 400
    assignee = payload.get("assignee") or None
    priority = payload.get("priority")
    try:
        item = assign_instance(
            config.get("task_dir", "."), project=_project(config),
            instance_id=str(instance_id), assignee=assignee,
            priority=priority if priority is None else int(priority),
        )
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"item": item})


@review_bp.route("/api/review/my_queue", methods=["GET"])
@_enabled_guard
def review_my_queue_api():
    """A reviewer's open assignments (login-scoped, no admin needed)."""
    username = session.get("username")
    if not username:
        return jsonify({"error": "Authentication required"}), 401
    config = _config()
    items = my_queue(config.get("task_dir", "."), _project(config), username)
    for item in items:
        item["preview"] = _preview(item["instance_id"])
    return jsonify({"queue": items})
