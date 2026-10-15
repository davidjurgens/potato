"""
Quality contracts. ``build_contract`` maps a ``ContractConfig.kind`` to its
class.
"""

from .base import (  # noqa: F401
    CalibrationView, CalItem, Contract, ContractResult, PopItem, TierPred)

_KINDS = {}


def _register():
    from .budget_first import BudgetFirst
    from .distributional import Distributional
    from .no_worse_than_human import NoWorseThanHuman
    from .ppi import PPI
    from .selective_risk import SelectiveRisk
    from .threshold_legacy import ThresholdLegacy
    for cls in (SelectiveRisk, PPI, NoWorseThanHuman, BudgetFirst, Distributional,
                ThresholdLegacy):
        _KINDS[cls.kind] = cls


def build_contract(cfg) -> Contract:
    if not _KINDS:
        _register()
    cls = _KINDS.get(cfg.kind)
    if cls is None:
        raise ValueError(f"contract kind {cfg.kind!r} is not available")
    return cls(cfg)
