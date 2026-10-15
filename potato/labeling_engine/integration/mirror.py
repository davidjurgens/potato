"""
Copying the older subsystems' machine labels into the engine's store.

Solo Mode, the ICL labeler, judge alignment and model-training write-back keep
running their own loops. When the labeling engine is also enabled, every
prediction they make is mirrored here as a prediction of a ``static`` source
named after the subsystem and versioned by its model and prompt version, so
the engine's certificate, exports and call log account for all machine
labels in the study, not only its own.

Mirrored predictions are evidence, not decisions: no contract accepts them
unless a mirrored source is put in the cascade by name. The call row records
that the call was observed rather than made (``estimated``, cost unknown),
because the subsystem that made it did not report its cost here.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def mirror(origin: str, model: str, version: Any, item_id: str, schema: str, value: Any,
           confidence: Optional[float], reasoning: Optional[str] = None) -> None:
    from .hooks import get_engine
    engine = get_engine()
    if engine is None:
        return
    try:
        from ..model.records import ModelCall, Prediction, SourceVersion, content_hash
        sv = SourceVersion(source_id=f"mirror:{origin}", kind="static",
                           model=str(model or origin), endpoint_type="static",
                           params={"origin": origin, "version": str(version)},
                           code_version=f"mirror/{origin}/1")
        store = engine.store
        store.register_source_version(sv)
        [cid] = store.add_calls([ModelCall(
            source_version_id=sv.version_id, endpoint_type=f"mirror:{origin}",
            model=str(model or origin), prompt_hash=str(version),
            input_hash=content_hash([item_id, schema])[:32],
            response_hash=content_hash(value)[:32], estimated=True, cost_usd=None,
            error=None)])
        store.add_predictions([Prediction(
            str(item_id), schema, sv.version_id, value, status="ok" if value is not None
            else "abstain", raw_conf=None if confidence is None else float(confidence),
            call_ids=[cid], reasoning=(reasoning or None) and str(reasoning)[:500])])
    except Exception:
        logger.debug("labeling engine: could not mirror %s prediction", origin,
                     exc_info=True)
