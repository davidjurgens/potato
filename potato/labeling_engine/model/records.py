"""
Records the engine keeps, one dataclass per table in ``engine.sqlite``.

The field lists here are the contract between the store, the runner, the
contracts and the exporters. Three of them carry the invariants the
certificate depends on:

- ``Prediction`` is append-only. A re-run writes a new row; the latest row per
  (item, schema, source version) is the current one.
- ``HumanRequest.inclusion_prob`` is the probability the item was chosen for
  this request under its sampling design. Estimates weight by its inverse, and
  a request without one (``purpose='organic'``) never reaches an estimator.
- ``SourceVersion.version_id`` hashes everything that can change a model's
  answer, so a certificate bound to it goes stale when any of it changes.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def canonical_json(value: Any) -> str:
    """JSON with sorted keys and no whitespace, so equal values hash equally."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    """sha256 of the canonical JSON of ``value`` (a string is hashed as-is)."""
    data = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _now() -> float:
    return time.time()


# --- Purposes, statuses and other closed vocabularies -----------------------

#: Why a human was asked. Only the random purposes feed estimators.
PURPOSES = (
    "calibration",    # blind, random: fits calibrators and thresholds (dev split)
    "certification",  # blind, random: tests the contract (cert split)
    "verify",         # below threshold: the human checks a machine label
    "resolve",        # the machine abstained or failed: the human labels it
    "audit",          # blind, random over auto-accepted labels: drift
    "adjudicate",     # conflict between raters
    "gold",           # hidden quality check
    "distribution",   # k-way overlap for subjective schemas
    "organic",        # a label made outside the engine; never estimated from
    "assist",         # the human used the interactive assistant
)
RANDOM_PURPOSES = ("calibration", "certification", "audit", "distribution")
SPLITS = ("dev", "cert", "audit", "none")
VISIBILITY = ("blind", "shown")
POOLS = ("team", "crowd", "solo")
REQUEST_STATUSES = ("open", "assigned", "done", "expired", "cancelled")
PREDICTION_STATUSES = ("ok", "abstain", "error")
RUN_KINDS = ("predict", "calibrate", "certify", "distill", "optimize", "audit")
RUN_STATUSES = ("pending", "running", "paused", "cancelled", "done", "failed")
DESIGN_KINDS = ("bernoulli", "stratified", "active", "fixed", "census")
LABEL_ORIGINS = ("auto", "human", "adjudicated", "inferred", "static")
LABEL_STATUSES = ("accepted", "pending", "pending_recert", "revoked")
CONTRACT_STATUSES = ("insufficient", "met", "violated", "stale", "infeasible")
BUDGET_KINDS = ("model_usd", "human_usd", "human_labels")


@dataclass
class SourceVersion:
    """One exact configuration of a machine source."""
    source_id: str
    kind: str                       # llm, vlm, decision, detector, asr, ...
    model: str = ""
    endpoint_type: str = ""
    revision: str = ""              # model revision / weights hash, if known
    params: Dict[str, Any] = field(default_factory=dict)
    prompt_template_hash: str = ""
    code_version: str = ""
    version_id: str = ""
    created_at: float = field(default_factory=_now)

    def __post_init__(self):
        if not self.version_id:
            self.version_id = self.compute_version_id()

    def compute_version_id(self) -> str:
        return content_hash({
            "kind": self.kind, "model": self.model,
            "endpoint_type": self.endpoint_type, "revision": self.revision,
            "params": self.params,
            "prompt_template_hash": self.prompt_template_hash,
            "code_version": self.code_version,
        })[:32]


@dataclass
class Run:
    kind: str
    source_version_id: Optional[str] = None
    config_hash: str = ""
    status: str = "pending"
    cursor: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None
    started_at: float = field(default_factory=_now)
    finished_at: Optional[float] = None
    error: Optional[str] = None


@dataclass
class Prediction:
    item_id: str
    schema: str
    source_version_id: str
    value: Any
    status: str = "ok"
    raw_conf: Optional[float] = None
    #: A class -> probability map, or per-object confidences for regions.
    conf: Optional[Dict[str, Any]] = None
    calibrated_conf: Optional[float] = None
    calibrator_id: Optional[str] = None
    call_ids: List[int] = field(default_factory=list)
    run_id: Optional[int] = None
    reasoning: Optional[str] = None
    id: Optional[int] = None
    created_at: float = field(default_factory=_now)


@dataclass
class ModelCall:
    """One request to a model. Hashes only; raw text is never stored here."""
    source_version_id: str
    endpoint_type: str
    model: str
    prompt_hash: str
    input_hash: str
    response_hash: str = ""
    run_id: Optional[int] = None
    revision: str = ""
    sample_idx: int = 0
    started_at: float = field(default_factory=_now)
    latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    #: True when tokens/cost were estimated rather than reported by the API.
    estimated: bool = True
    cache_hit: bool = False
    #: Redaction categories and span hashes; never the redacted text.
    redaction: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    payload_ref: Optional[str] = None
    id: Optional[int] = None


@dataclass
class SamplingDesign:
    """How items were drawn for a set of requests, so π can be recomputed."""
    kind: str
    params: Dict[str, Any] = field(default_factory=dict)
    seed: int = 0
    id: Optional[int] = None
    created_at: float = field(default_factory=_now)


@dataclass
class HumanRequest:
    item_id: str
    schema: str
    purpose: str
    inclusion_prob: Optional[float]
    visibility: str = "blind"
    split: str = "none"
    pool: str = "team"
    design_id: Optional[int] = None
    shown_prediction_id: Optional[int] = None
    eligible_group: Optional[str] = None
    assigned_user: Optional[str] = None
    status: str = "open"
    contract_id: Optional[str] = None
    priority: float = 0.0
    label: Any = None
    user_id: Optional[str] = None
    cost_usd: Optional[float] = None
    id: Optional[int] = None
    created_at: float = field(default_factory=_now)
    completed_at: Optional[float] = None
    assigned_at: Optional[float] = None


@dataclass
class ResolvedLabel:
    item_id: str
    schema: str
    value: Any
    origin: str
    status: str = "pending"
    source_version_id: Optional[str] = None
    request_ids: List[int] = field(default_factory=list)
    contract_version_id: Optional[int] = None
    certificate_id: Optional[int] = None
    updated_at: float = field(default_factory=_now)


@dataclass
class ContractVersion:
    contract_id: str
    kind: str
    params: Dict[str, Any]
    cascade_hash: str
    status: str = "insufficient"
    looks: int = 0
    result: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None
    created_at: float = field(default_factory=_now)


@dataclass
class Certificate:
    cascade_hash: str
    dataset_hash: str
    contract_version_ids: List[int]
    sections: Dict[str, Any]
    budget: Dict[str, Any] = field(default_factory=dict)
    content_sha256: str = ""
    id: Optional[int] = None
    created_at: float = field(default_factory=_now)


@dataclass
class Budget:
    kind: str
    scope: str = "study"
    limit: Optional[float] = None
    spent: float = 0.0
