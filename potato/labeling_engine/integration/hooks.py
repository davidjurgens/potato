"""
Where the running server meets the engine.

- ``init_engine(config)`` at boot, when ``labeling_engine.enabled``.
- ``on_human_save(user_state, instance_id)`` after every annotation write
  (``potato/annotation_commit.py`` calls it), which closes the request the
  label answers or records it as organic.
- ``claim_for_user`` / ``has_work_for_user`` behind the ``engine``
  assignment strategy.
- ``is_blind(user_id, instance_id)`` for routes that would otherwise show a
  machine suggestion.

Every hook is a no-op when the engine is off, and none raises: a failure here
is logged and the annotation write it follows still stands.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from potato.server_utils.annotation_values import group_by_schema, user_values

logger = logging.getLogger(__name__)

_ENGINE = None
_PLANNER = None
_LOCK = threading.Lock()


def init_engine(config: Dict[str, Any], start_planner: bool = True):
    """Build the study's engine if the config enables it; return it or None."""
    global _ENGINE
    block = config.get("labeling_engine") or {}
    if not block.get("enabled"):
        return None
    from ..service import Engine
    with _LOCK:
        _ENGINE = Engine(config)
        _ENGINE.release_listeners.append(_drop_released_hold)
        _ENGINE.user_attributes = user_attributes
    if start_planner:
        start_background_planner(config)
    return _ENGINE


def user_attributes(user_id: str) -> Dict[str, str]:
    """A person's answers outside the annotation phase (prestudy and other
    survey pages), as {scheme name: answer}: what distributional
    ``groups_by`` names. A choice question's answer is the chosen label."""
    from potato.user_state_management import get_user_state_manager
    usm = get_user_state_manager()
    if not usm.has_user(user_id):
        return {}
    state = usm.get_user_state(user_id)
    out: Dict[str, str] = {}
    pages = getattr(state, "phase_to_page_to_label_to_value", {}) or {}
    for phase, by_page in pages.items():
        if str(phase).lower().endswith("annotation"):
            continue
        for _page, label_to_value in (by_page or {}).items():
            for label, value in (label_to_value or {}).items():
                try:
                    schema, name = label.get_schema(), label.get_name()
                except AttributeError:
                    continue
                if value in (None, "", False, "false"):
                    continue
                chosen = value in (True, "true", "on", name)
                out[schema] = str(name if chosen else value)
    return out


def _drop_released_hold(user_id: str, item_id: str) -> None:
    """Take an item whose request timed out off its holder's page.

    Left there, a tab open past the timeout would show the item with no
    request behind it, so with the machine's answer, and its saves would be
    organic labels the person thinks are their assigned work. An item they
    already saved something on stays (their answer is kept)."""
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager
    usm = get_user_state_manager()
    if not usm.has_user(user_id):
        return
    user_state = usm.get_user_state(user_id)
    ism = get_item_state_manager()
    with ism._lock:
        dropped = ism._reclaim_unannotated_assignment(
            user_state, item_id, reason="labeling engine request timed out")
    if dropped:
        usm.save_user_state(user_state)


def get_engine():
    return _ENGINE


def clear_engine() -> None:
    global _ENGINE, _PLANNER
    with _LOCK:
        if _PLANNER is not None:
            _PLANNER.stop()
        _ENGINE, _PLANNER = None, None


def start_background_planner(config: Dict[str, Any]):
    global _PLANNER
    from ..allocation.planner import BackgroundPlanner
    if _ENGINE is None:
        return None
    with _LOCK:
        if _PLANNER is None:
            _PLANNER = BackgroundPlanner(_ENGINE, item_source=_server_items)
            _PLANNER.start()
    return _PLANNER


def get_planner():
    return _PLANNER


def is_quality_control_item(item_id: str) -> bool:
    """Attention checks and injected gold items: they test the annotator, so
    they are never engine items, sampled, predicted or exported."""
    try:
        from potato.quality_control import get_quality_control_manager
        qc = get_quality_control_manager()
    except Exception:
        return False
    if qc is None:
        return False
    return bool(qc.is_attention_check(str(item_id)) or qc.is_gold_standard(str(item_id)))


def _server_items(engine):
    """The live study's items, as the engine sees them."""
    from potato.item_state_management import get_item_state_manager
    from ..items import views_from_item_manager
    try:
        ism = get_item_state_manager()
    except Exception:
        return []
    ids = [i for i in ism.get_instance_ids() if not is_quality_control_item(i)]
    return views_from_item_manager(ism, engine.app_config, ids)


# === Human labels ===========================================================

def _is_machine(user_state) -> bool:
    try:
        from potato.annotator_origin import is_machine
        return bool(is_machine(user_state))
    except Exception:
        return False


def answer_for(engine, scheme, grouped: Dict[str, Dict[str, Any]]) -> Optional[Any]:
    """A person's answer for one engine scheme, read by the scheme's family."""
    values = grouped.get(scheme.name)
    if values is None:
        return None
    value = engine.family(scheme).human_value(values)
    if value is None or value == "" or (isinstance(value, list) and not value
                                        and scheme.is_one_of_n):
        return None
    return value


def on_human_save(user_state, instance_id: str) -> None:
    engine = _ENGINE
    if engine is None or user_state is None:
        return
    try:
        if _is_machine(user_state) or is_quality_control_item(instance_id):
            return
        user_id = str(getattr(user_state, "user_id", ""))
        # Data order: the engine's own answers are about the candidates as
        # the data lists them, not as this annotator's page showed them.
        grouped = user_values(user_state, instance_id)
        for scheme in engine.schemes():
            value = answer_for(engine, scheme, grouped)
            if value is not None:
                engine.record_human_label(str(instance_id), scheme.name, value, user_id)
    except Exception:
        logger.exception("labeling engine: could not record %s's label on %s",
                         getattr(user_state, "user_id", "?"), instance_id)


def on_adjudication(decision) -> None:
    """An adjudicator settled an item: that label wins for every engine scheme
    it covers, and any adjudicate request on it is closed."""
    engine = _ENGINE
    if engine is None or decision is None:
        return
    try:
        for scheme in engine.schemes():
            raw = (decision.label_decisions or {}).get(scheme.name)
            if raw is None:
                continue
            value = engine.family(scheme).human_value(raw) if isinstance(raw, dict) else raw
            if value is not None:
                engine.record_adjudication(str(decision.instance_id), scheme.name, value,
                                           str(decision.adjudicator_id))
    except Exception:
        logger.exception("labeling engine: could not record adjudication of %s",
                         getattr(decision, "instance_id", "?"))


# === Assignment =============================================================

def _pool_for(engine, user_state) -> Optional[str]:
    pools = engine.cfg.humans.pools
    if len(pools) == 1:
        return pools[0]
    crowd = getattr(user_state, "crowd_provider", None) or \
        (getattr(user_state, "metadata", None) or {}).get("crowd_provider")
    return "crowd" if crowd and "crowd" in pools else ("team" if "team" in pools else pools[0])


def claim_for_user(user_state, n: int, exclude=()) -> List[str]:
    engine = _ENGINE
    if engine is None or _is_machine(user_state):
        return []
    # The per-annotator cap (max_annotations_per_user) holds here too: Pocket
    # claims a whole batch at once, and without this one batch took 23 items
    # from a person capped at 3 (potato-skill M1).
    try:
        cap = int(user_state.get_max_assignments())
    except Exception:
        cap = -1
    if cap >= 0:   # -1 is unlimited; 0 is none at all, as desktop treats it
        from potato.item_state_management import get_item_state_manager
        n = min(n, cap - get_item_state_manager()._dataset_assignment_count(user_state))
    if n <= 0:
        return []
    try:
        reqs = engine.claim_requests(str(user_state.user_id), n,
                                     pool=_pool_for(engine, user_state), exclude=exclude)
        return [r.item_id for r in reqs]
    except Exception:
        logger.exception("labeling engine: could not claim requests")
        return []


def held_item_ids_for_user(user_state) -> List[str]:
    """Items on which this person holds an unanswered engine request."""
    engine = _ENGINE
    if engine is None:
        return []
    try:
        return sorted({r.item_id for r in engine.store.requests(
            status=["assigned"], user=str(user_state.user_id))})
    except Exception:
        logger.exception("labeling engine: could not list held requests")
        return []


def has_work_for_user(user_state, exclude=()) -> bool:
    engine = _ENGINE
    if engine is None or _is_machine(user_state):
        return False
    try:
        return engine.has_work_for(str(user_state.user_id),
                                   pool=_pool_for(engine, user_state), exclude=exclude)
    except Exception:
        logger.exception("labeling engine: could not check for work")
        return False


def work_item_ids_for_user(user_state) -> List[str]:
    engine = _ENGINE
    if engine is None or _is_machine(user_state):
        return []
    try:
        return engine.work_item_ids_for(str(user_state.user_id),
                                        pool=_pool_for(engine, user_state))
    except Exception:
        logger.exception("labeling engine: could not list work")
        return []


def finished_for_user(user_state) -> Optional[str]:
    """Why this person has nothing more to do under the engine, or None when
    more work may still come (they should wait and come back)."""
    engine = _ENGINE
    if engine is None:
        return None
    try:
        quota = getattr(user_state, "max_assignments", -1)
        if quota is not None and quota > 0 and \
                len(user_state.get_assigned_instance_ids()) >= quota:
            return "per-annotator cap reached"
        if engine.human_work_remaining() is None:
            return "no more human labels will be requested"
    except Exception:
        logger.exception("labeling engine: could not tell whether the study is finished")
    return None


def _shown_key(request_id: int) -> str:
    return f"shown_prefill:{request_id}"


def served_without_prediction(user_id: Optional[str], instance_id: Optional[str]) -> int:
    """Record that this person's requests on this item were answered blind.

    For surfaces that cannot show a machine answer (Pocket Mode): a verify
    request left as ``shown`` would claim the person saw a prediction they
    never saw, and the anchoring a shown request is discounted for never
    happened. Returns how many requests were changed.
    """
    engine = _ENGINE
    if engine is None or not user_id or instance_id is None:
        return 0
    n = 0
    try:
        for r in engine.store.requests(item_id=str(instance_id), status=["assigned"]):
            if r.assigned_user == str(user_id) and r.visibility != "blind":
                if engine.store.kv_get(_shown_key(r.id)):
                    # The desktop page already showed this person the machine's
                    # answer: their label is anchored on it whatever this
                    # surface shows, so it stays "shown".
                    continue
                engine.store.update_request(r.id, visibility="blind", shown_prediction_id=None)
                n += 1
    except Exception:
        logger.exception("labeling engine: could not record a blind serve")
    return n


def is_blind(user_id: Optional[str], instance_id: Optional[str]) -> bool:
    """Whether this person is answering this item blind for the engine."""
    engine = _ENGINE
    if engine is None or not user_id or instance_id is None:
        return False
    try:
        return engine.visibility_for(str(user_id), str(instance_id)) == "blind"
    except Exception:
        logger.exception("labeling engine: could not read visibility")
        # Fail closed: when in doubt, do not show a suggestion.
        return True


def machine_fields(blind: bool) -> set:
    """Item fields that hold machine answers: every static source's ``field``,
    and on a blind request the pre-annotation field too. The page and the
    item-data routes leave them out, or a blind label could be read off the
    page source."""
    engine = _ENGINE
    if engine is None:
        return set()
    out = set()
    for src in engine.cfg.sources:
        if src.kind == "static":
            f = (src.options or {}).get("field") or src.raw.get("field")
            if f:
                out.add(str(f))
    if blind:
        pa = engine.app_config.get("pre_annotation") or {}
        if isinstance(pa, dict) and pa.get("enabled"):
            out.add(str(pa.get("field") or "predictions"))
    return out


def strip_machine_fields(record, user_id: Optional[str], instance_id: Optional[str]):
    """``record`` without the fields ``machine_fields`` names."""
    if _ENGINE is None or not isinstance(record, dict):
        return record
    drop = machine_fields(is_blind(user_id, instance_id))
    if not drop or not drop & set(record):
        return record
    return {k: v for k, v in record.items() if k not in drop}


def request_context(user_id: Optional[str], instance_id: Optional[str]) -> Optional[Dict]:
    """What the annotate page shows about the engine request on this item."""
    engine = _ENGINE
    if engine is None or not user_id or instance_id is None:
        return None
    try:
        mine = engine.requests_of(str(user_id), str(instance_id))
        if not mine:
            return None
        held = [r for r in mine if r.status == "assigned"]
        r = sorted(held or mine, key=engine._purpose_rank)[0]
        # Blind on any of this person's requests on the item (held or
        # answered) makes the whole page blind; see Engine.visibility_for.
        visibility = "blind" if any(x.visibility == "blind" for x in mine) else r.visibility
        shown = None
        if visibility == "shown" and r.shown_prediction_id:
            p = engine.store.get_prediction(r.shown_prediction_id)
            page_value = None
            if p is not None:
                try:
                    page_value = engine.family(engine.scheme(r.schema)).to_page(p.value)
                except Exception:
                    logger.exception("labeling engine: could not shape a verify prefill")
            if page_value is not None:
                shown = {"value": page_value, "confidence": p.raw_conf}
                if r.status == "assigned" and not engine.store.kv_get(_shown_key(r.id)):
                    # The page is about to prefill it: from now on the
                    # request cannot honestly be recorded as blind.
                    engine.store.kv_set(_shown_key(r.id), time.time())
            elif r.status == "assigned":
                # The page cannot show this answer (a family with no prefill):
                # the person answers without it, so record the request blind
                # rather than claim a prefill nobody saw.
                served_without_prediction(user_id, instance_id)
                visibility = "blind"
        # The question as annotators see it, not the scheme's internal name.
        label = r.schema
        try:
            spec = engine.scheme(r.schema)
            label = (spec.description or spec.name or r.schema).strip()
        except KeyError:
            pass
        if len(label) > 90:
            label = label[:87].rstrip() + "…"
        return {"purpose": r.purpose, "visibility": visibility, "schema": r.schema,
                "schema_label": label, "split": r.split, "shown": shown}
    except Exception:
        logger.exception("labeling engine: could not build request context")
        return None
