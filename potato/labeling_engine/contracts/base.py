"""
What a contract reads and what it returns.

A contract never queries the store. It is handed a ``CalibrationView``:
human-labeled items with their split, inclusion probability and each cascade
tier's prediction, plus the machine predictions over the whole population.
That keeps every contract a pure function of its inputs, which is what lets
the validity tests drive them with simulated data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass
class TierPred:
    value: Any
    conf: float = 0.0
    status: str = "ok"
    dist: Optional[Dict[str, float]] = None

    @property
    def answered(self) -> bool:
        return self.status == "ok" and self.value is not None


@dataclass
class CalItem:
    """One item a human labeled for the engine, through a random request."""
    item_id: str
    human: Any
    split: str                      # dev | cert | audit
    pi: Optional[float]             # inclusion probability under its design
    tiers: List[Optional[TierPred]] = field(default_factory=list)
    stratum: Optional[str] = None
    group: Optional[str] = None     # ppi `by` / distributional groups
    #: The cascade's routed answer for this item (see Engine.routed_output),
    #: computed exactly as for an unsampled item.
    output: Optional[TierPred] = None
    #: Every person's label on the item: user id -> label.
    humans: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PopItem:
    """One item in the population the contract's claims are about."""
    item_id: str
    tiers: List[Optional[TierPred]] = field(default_factory=list)
    group: Optional[str] = None
    #: Inclusion probability under the calibration design, sampled or not.
    #: Items with equal pi form one sampling stratum.
    pi: Optional[float] = None
    output: Optional[TierPred] = None


@dataclass
class CalibrationView:
    scheme: str
    labels: List[str]
    tier_ids: List[str]
    cal: List[CalItem] = field(default_factory=list)
    population: List[PopItem] = field(default_factory=list)
    #: correct(pred_value, human_value) -> bool. One-of-N: equality.
    correct: Callable[[Any, Any], bool] = lambda a, b: a == b
    #: class_of(pred_value) -> the class a per-class contract groups it under.
    class_of: Callable[[Any], str] = lambda v: str(v)
    #: How the human label was decided when several people labeled the item.
    truth_note: str = ""
    #: True when every population item has a routed cascade output. Estimators
    #: use it only then: an output that existed for sampled items but not for
    #: others would depend on the sampling and bias every estimate.
    output_complete: bool = False
    #: item id -> the item fields a contract groups by (ppi ``by``).
    item_fields: Dict[str, Dict[str, str]] = field(default_factory=dict)
    #: user id -> that person's attributes (distributional ``groups_by``).
    user_groups: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def split(self, name: str) -> List[CalItem]:
        return [c for c in self.cal if c.split == name]

    @property
    def n_cert(self) -> int:
        return sum(1 for c in self.cal if c.split == "cert")


@dataclass
class ContractResult:
    status: str                                 # insufficient | met | violated | infeasible | stale
    #: tier id -> class (or "*") -> threshold; None means "accept nothing".
    acceptance: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    projection: Dict[str, Any] = field(default_factory=dict)
    look: int = 0
    alpha: Optional[float] = None
    statement: str = ""
    notes: List[str] = field(default_factory=list)
    #: False when the evaluation never reached a test (too few labels, no
    #: tiers, a projection only). Such an evaluation spends no look.
    ran: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "acceptance": self.acceptance,
                "metrics": self.metrics, "projection": self.projection,
                "look": self.look, "alpha": self.alpha, "statement": self.statement,
                "notes": list(self.notes), "ran": self.ran}


class Contract:
    kind = ""
    #: Bump when the procedure changes, so stored results from the old code
    #: are recomputed rather than reused.
    VERSION = "1"

    def __init__(self, cfg):
        self.cfg = cfg

    def evaluate(self, view: CalibrationView, look: int = 1) -> ContractResult:
        raise NotImplementedError
