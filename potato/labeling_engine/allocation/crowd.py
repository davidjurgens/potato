"""
Recruiting crowd workers for the engine's open requests (Prolific).

Each pass the planner works out how many places the open crowd-pool requests
need (``ceil(open / per_worker_quota)`` on top of the places already taken)
and what they would cost (``crowd.reward_usd`` per place, plus Prolific's fee
as its cost calculator reports it when live).

It spends nothing unless ``features.crowd_live_spend`` is on. Without it the
plan is recorded and reported (``dry_run``), so a study can watch what the
engine would do before letting it. With it, places are added only while the
spend stays within ``budgets.human_usd``; the config refuses live spend
without that budget.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

#: Prolific's service fee for researchers, used only when the cost calculator
#: cannot be reached (dry runs). The live path reads the real figure.
FALLBACK_FEE = 0.333


def _client_from_config(app_config: Dict[str, Any]):
    from potato.crowdsourcing.prolific_api import ProlificClient
    settings = (app_config.get("crowdsourcing") or {}).get("prolific") or \
        app_config.get("prolific") or {}
    token = settings.get("token")
    return ProlificClient(token) if token else None


def plan_crowd(engine, client_factory: Optional[Callable[[], Any]] = None) -> Dict[str, Any]:
    cfg = engine.cfg
    if "crowd" not in cfg.humans.pools or not cfg.feature("crowd_recruit"):
        return {"action": "off"}
    open_reqs = len(engine.store.requests(status=["open", "assigned"], pool="crowd"))
    quota = max(1, cfg.crowd.per_worker_quota)
    reward = cfg.crowd.reward_usd
    plan: Dict[str, Any] = {"open_requests": open_reqs, "per_worker_quota": quota,
                            "reward_usd": reward, "study_id": cfg.crowd.study_id}
    if open_reqs == 0:
        plan["action"] = "nothing_to_do"
        return plan
    new_places = math.ceil(open_reqs / quota)
    plan["new_places"] = new_places
    est = None if reward is None else round(new_places * reward * (1 + FALLBACK_FEE), 2)
    plan["estimated_cost_usd"] = est
    budget = engine.store.get_budget("human_usd")
    spent = budget.spent if budget else 0.0
    limit = cfg.budgets.get("human_usd")
    plan["human_usd"] = {"spent": spent, "limit": limit}

    if not cfg.feature("crowd_live_spend"):
        plan["action"] = "dry_run"
        plan["note"] = ("features.crowd_live_spend is off, so no places were added. "
                        "This is what the engine would add.")
        return plan
    if not cfg.crowd.study_id or reward is None:
        plan["action"] = "refused"
        plan["note"] = "crowd.study_id and crowd.reward_usd are needed to recruit."
        return plan
    client = (client_factory or (lambda: _client_from_config(engine.app_config)))()
    if client is None:
        plan["action"] = "refused"
        plan["note"] = "No Prolific API token is configured."
        return plan
    study = client.get_study(cfg.crowd.study_id)
    taken = int(study.get("places_taken", 0) or 0)
    current = int(study.get("total_available_places", 0) or 0)
    target = max(current, taken + new_places)
    add = target - current
    if add <= 0:
        plan["action"] = "enough_places"
        return plan
    try:
        quote = client.calculate_cost(int(round(reward * 100)), add)
        cost = float(quote.get("total_cost", 0)) / 100.0 if isinstance(quote, dict) else None
    except Exception:
        cost = None
    cost = cost if cost else round(add * reward * (1 + FALLBACK_FEE), 2)
    plan["quoted_cost_usd"] = cost
    if limit is not None and spent + cost > limit + 1e-9:
        plan["action"] = "refused_budget"
        plan["note"] = (f"Adding {add} places would cost ${cost:.2f}, taking crowd spend "
                        f"to ${spent + cost:.2f} against budgets.human_usd ${limit:.2f}.")
        return plan
    client.increase_places(cfg.crowd.study_id, target)
    engine.store.add_spend("human_usd", cost)
    plan.update(action="increased", added_places=add, target_places=target)
    logger.info("labeling engine: added %d Prolific places ($%.2f)", add, cost)
    return plan
