"""
Signal-based triage scoring for the annotation queue.

Captures a per-item quality signal — an agent error, a production thumbs-down, a
low automated score, or any custom field — and turns it into a numeric
*triage priority* so the assignment queue can surface the worst / most-suspect
traces first instead of annotating in arrival (FIFO) order.

The same scorer runs over statically loaded data and over traces ingested at
runtime (webhook / Langfuse), because both funnel through
``ItemStateManager.add_item``. The priority is stored on the item's metadata
(``triage_priority`` / ``triage_reason`` / ``triage_rule``); the ``priority``
assignment strategy reads it; the inline badge and the admin queue page surface it.

Config (all optional):

    triage:
      enabled: true
      order: desc            # high priority first (default); 'asc' = low first
      default_priority: 0    # items matching no rule
      show_badge: true       # show a "why prioritized" banner during annotation
      signal_field: null     # read a numeric priority straight from this field
      invert_signal: false   # if true, a LOWER field value => HIGHER priority
      rules:                 # evaluated in order; highest matching priority wins
        - name: "Agent errored"
          when: {field: "status", equals: "error"}
          priority: 100
          badge: "Agent errored"
        - name: "Negative feedback"
          when: {field: "feedback", in: ["thumbs_down", "negative"]}
          priority: 80
        - name: "Low score"
          when: {field: "score", lt: 0.5}
          priority: 60

When ``enabled`` with no ``rules`` and no ``signal_field``, a turnkey set of
built-in defaults is used (error status, negative feedback, low score) so
ingested traces are triaged out of the box.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Turnkey defaults applied when triage is enabled but no rules/signal_field are
# configured. These match the signals ingested traces most commonly carry.
DEFAULT_RULES = [
    {"name": "Agent errored", "badge": "Agent errored", "priority": 100,
     "when": {"field": "status", "in": ["error", "failed", "failure"]}},
    {"name": "Negative feedback", "badge": "Negative feedback", "priority": 80,
     "when": {"field": "feedback", "in": ["thumbs_down", "negative", "down", "👎"]}},
    {"name": "Low score", "badge": "Low score", "priority": 60,
     "when": {"field": "score", "lt": 0.5}},
]


@dataclass
class TriageScore:
    """The triage outcome for one item."""
    priority: float
    reason: str | None = None   # human-readable badge text (None when unflagged)
    rule: str | None = None     # the rule name that matched (None for default/field)

    def to_metadata(self) -> dict:
        return {
            "triage_priority": self.priority,
            "triage_reason": self.reason,
            "triage_rule": self.rule,
        }


# The condition matcher now lives in the shared ``conditions`` module so the
# automation-rules engine evaluates the exact same ``when`` grammar. The private
# aliases are kept for backward compatibility (imported by tests and elsewhere).
from potato.server_utils.conditions import (  # noqa: E402
    lookup as _lookup,
    as_number as _as_number,
    matches as _matches,
)


class TriageScorer:
    """Scores items into a triage priority from the ``triage`` config block."""

    def __init__(self, triage_config: dict):
        cfg = triage_config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.order = str(cfg.get("order", "desc")).lower()
        self.default_priority = float(cfg.get("default_priority", 0) or 0)
        self.show_badge = bool(cfg.get("show_badge", True))
        self.signal_field = cfg.get("signal_field")
        self.invert_signal = bool(cfg.get("invert_signal", False))

        rules = cfg.get("rules")
        if not rules and not self.signal_field:
            rules = DEFAULT_RULES
        self.rules = rules or []

    def score(self, item_data: dict) -> TriageScore:
        """Return the TriageScore for one item (highest matching rule wins)."""
        if not self.enabled:
            return TriageScore(priority=self.default_priority)

        best: TriageScore | None = None
        for rule in self.rules:
            cond = rule.get("when") or {}
            try:
                if _matches(cond, item_data):
                    pr = float(rule.get("priority", 0) or 0)
                    if best is None or pr > best.priority:
                        badge = rule.get("badge") or rule.get("name")
                        best = TriageScore(priority=pr, reason=badge, rule=rule.get("name"))
            except Exception as e:  # a malformed rule must never break loading
                logger.warning(f"Triage rule {rule.get('name')!r} failed: {e}")

        if best is not None:
            return best

        # No rule matched: optionally read a direct numeric signal.
        if self.signal_field is not None:
            raw = _as_number(_lookup(item_data, self.signal_field))
            if raw is not None:
                pr = -raw if self.invert_signal else raw
                return TriageScore(priority=pr, reason=None, rule=None)

        return TriageScore(priority=self.default_priority)


def build_scorer(config: dict) -> TriageScorer | None:
    """Build a TriageScorer from a server config, or None when triage is off."""
    triage_cfg = (config or {}).get("triage") or {}
    if not triage_cfg.get("enabled"):
        return None
    return TriageScorer(triage_cfg)


def compute_triage_queue(config: dict) -> dict:
    """Build the admin triage-queue report from the live ItemStateManager.

    Returns the remaining (incomplete) items ranked by triage priority, with the
    reason/rule that flagged them, current annotation count, and whether they are
    already assigned. Used by the ``/admin/triage-queue`` page.
    """
    from potato.item_state_management import get_item_state_manager

    scorer = build_scorer(config)
    order = (scorer.order if scorer else "desc")
    reverse = order != "asc"

    ism = get_item_state_manager()
    rows = []
    # Preserve the configured/global ordering as the deterministic tie-break.
    ordering = {iid: i for i, iid in enumerate(ism.instance_id_ordering)}
    for iid in ism.instance_id_ordering:
        item = ism.get_item(iid)
        if item is None:
            continue
        # Skip items that have reached their annotation cap.
        try:
            if ism._item_is_saturated(iid):
                continue
        except Exception:
            pass
        priority = item.get_metadata("triage_priority")
        if priority is None:
            priority = scorer.default_priority if scorer else 0
        n_ann = len(ism.instance_annotators.get(iid, set()))
        rows.append({
            "id": iid,
            "priority": priority,
            "reason": item.get_metadata("triage_reason"),
            "rule": item.get_metadata("triage_rule"),
            "annotations": n_ann,
            "assigned": n_ann > 0,
            "_order": ordering.get(iid, 0),
        })

    rows.sort(key=lambda r: (r["priority"], -r["_order"]), reverse=reverse)
    for r in rows:
        r.pop("_order", None)

    return {
        "enabled": bool(scorer),
        "order": order,
        "n_items": len(rows),
        "n_flagged": sum(1 for r in rows if r["reason"]),
        "items": rows,
    }
