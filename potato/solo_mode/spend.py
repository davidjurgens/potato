"""
What Solo Mode's background labeling costs, and refusing to overspend.

Solo Mode labels the whole corpus in the background, which is the largest AI
bill a Potato study can run up. This module applies the project-wide rules in
``potato/ai/cost.py`` to it:

- an estimate for the items still to label, before labeling starts;
- the ``ai_budget.cap_usd`` ceiling, checked before labeling starts and again
  before every batch. A refusal pauses labeling and says why;
- a running total, recorded per batch and per model actually called, so an
  item escalated through the confidence cascade is charged for each tier.

Prices come only from ``PRICE_TABLE`` or the study's ``ai_budget.prices``. A
model with no price reports tokens and ``cost_usd: None`` and never blocks:
the cap is a dollar ceiling and there is no dollar figure to compare.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Characters the labeling prompt adds to every item beyond the prompt text
#: itself: the label list, the JSON instruction and the edge-case clause.
PROMPT_SCAFFOLD_CHARS = 400

ACTION = 'solo_mode_labeling'


def calls_per_item(solo_config) -> int:
    """LLM calls one item costs: the label, plus the uncertainty estimate.

    ``sampling_diversity`` samples ``num_samples`` times. The other estimators
    ask the model once more. Labeling functions cost nothing, but which items
    they will catch is not known in advance, so the estimate assumes none.
    """
    strategy = solo_config.uncertainty.strategy
    if strategy == 'sampling_diversity':
        return 1 + max(1, int(solo_config.uncertainty.num_samples))
    return 2


def estimate(texts: Sequence[str], model_config, prompt_chars: int,
             solo_config, app_config: Dict[str, Any], calls: Optional[int] = None):
    """A CostEstimate for labeling ``texts`` with ``model_config``.

    A decision model (systemone, laya) answers in one call and generates no
    tokens, so it is estimated at one call and zero output whatever the
    uncertainty strategy or max_tokens say.
    """
    from potato.ai import cost
    from .config import DECISION_ENDPOINT_TYPES

    decision = model_config.endpoint_type in DECISION_ENDPOINT_TYPES
    if calls is None:
        calls = 1 if decision else calls_per_item(solo_config)
    return cost.estimate(
        list(texts),
        model=model_config.model,
        endpoint_type=model_config.endpoint_type,
        prompt_overhead_chars=prompt_chars + PROMPT_SCAFFOLD_CHARS,
        max_output_tokens=0 if decision else int(model_config.max_tokens or 100),
        calls_per_item=calls,
        price_overrides=(app_config.get('ai_budget') or {}).get('prices'),
    )


def check(app_config: Dict[str, Any], projected) -> None:
    """Raise cost.SpendCapExceeded if ``projected`` would cross the cap."""
    from potato.ai import cost

    spent = cost.total_spend(app_config).get('cost_usd', 0.0) or 0.0
    cost.check_before_running(app_config, projected, spent)


def record(app_config: Dict[str, Any], projected, n_attempted: int) -> None:
    """Charge the project for the ``n_attempted`` items of ``projected`` that ran."""
    from potato.ai import cost

    if n_attempted <= 0:
        return
    cost.record_spend(app_config, ACTION, projected.rescaled(n_attempted),
                      estimated=True)


def summary(app_config: Dict[str, Any], remaining=None,
            refusal: Optional[str] = None) -> Dict[str, Any]:
    """The dashboard's view: spent so far, the cap, the estimate, a refusal."""
    from potato.ai import cost

    total = cost.total_spend(app_config)
    return {
        'cap_usd': cost.cap_for(app_config),
        'spent': total,
        'remaining_estimate': remaining.to_dict() if remaining is not None else None,
        'remaining_summary': remaining.summary() if remaining is not None else None,
        'refusal': refusal,
    }
