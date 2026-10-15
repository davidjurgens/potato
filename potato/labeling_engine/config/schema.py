"""
The ``labeling_engine`` config block.

    labeling_engine:
      enabled: true
      schemas: [sentiment]          # default: every scheme the engine can label
      sources:
        - id: laya
          kind: decision
          endpoint_type: laya
          model: convaiinnovations/laya
        - id: gemma
          kind: llm
          endpoint_type: vllm
          model: google/gemma-4-12B-it-qat-w4a16-ct
          base_url: http://burger.si.umich.edu:8001/v1
          confidence: {method: verbalized}
      cascade: [laya, gemma]        # tried in order; humans after the last
      contracts:
        - id: accuracy
          kind: selective_risk
          schema: sentiment
          error: 0.05
          confidence: 0.9
          per_class: true
      humans:
        pools: [team]
      budgets:
        model_usd: 20
        human_labels: 600

Parsing never imports a model backend. ``parse_engine_config`` returns an
``EngineConfig`` or raises ``EngineConfigError`` listing every problem, so a
bad block stops boot with all of its errors at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..model.records import POOLS, content_hash

SOURCE_KINDS = ("llm", "vlm", "decision", "detector", "asr", "trained", "lf",
                "jury", "judge", "static", "fixture", "simulator")
CONTRACT_KINDS = ("selective_risk", "ppi", "no_worse_than_human", "budget_first",
                  "distributional", "threshold_legacy")
CONFIDENCE_METHODS = ("auto", "verbalized", "k_sample", "logprob", "native")
VISIBILITIES = ("blind", "shown")
#: Features on unless the config turns them off. drift: audits that show the
#: accepted labels' error above target stop acceptance. Someone who sets an
#: audit rate expects the audits to do something; off, 88 of 91 failed audits
#: left 182 labels delivered as certified.
DEFAULT_FEATURES = {"drift": True}

FEATURES = ("distill", "optimize", "drift", "crowd_recruit", "crowd_live_spend",
            "pii_redaction", "payload_capture")

#: Keys a source may carry besides the ones parsed into named fields. They are
#: passed to the backend untouched (endpoint options, detector thresholds, ...).
#: Endpoint types that pick a label from a fixed set instead of writing one.
DECISION_ENDPOINT_TYPES = ("laya", "systemone")

SOURCE_FIELDS = ("id", "kind", "endpoint_type", "model", "base_url", "api_key",
                 "temperature", "max_tokens", "timeout", "prompt", "confidence",
                 "concurrency", "members", "aggregation", "options", "field",
                 "predictions_file", "schemas", "error_rate", "seed", "revision",
                 "judge")


class EngineConfigError(ValueError):
    def __init__(self, errors: List[str]):
        self.errors = list(errors)
        super().__init__("Invalid labeling_engine configuration:\n  - "
                         + "\n  - ".join(self.errors))


@dataclass
class SourceConfig:
    id: str
    kind: str
    endpoint_type: str = ""
    model: str = ""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 256
    timeout: Optional[float] = None
    prompt: Optional[str] = None
    confidence: Dict[str, Any] = field(default_factory=lambda: {"method": "auto"})
    concurrency: Optional[int] = None
    #: For a jury: member source ids and how their votes combine.
    members: List[str] = field(default_factory=list)
    aggregation: str = "plurality"
    #: Restrict the source to these schemes (default: all engine schemes).
    schemas: Optional[List[str]] = None
    options: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def public_params(self) -> Dict[str, Any]:
        """Everything that can change the answer, without secrets.

        This goes into the source version hash, so a changed temperature or
        prompt is a new version and invalidates certificates bound to the old
        one. The API key never changes an answer and must never be hashed into
        something that is exported.
        """
        return {k: v for k, v in sorted(self.raw.items())
                if k not in ("api_key", "id", "concurrency", "timeout")}


@dataclass
class ContractConfig:
    id: str
    kind: str
    schema: str
    #: selective_risk: the largest tolerated error rate among accepted labels.
    error: Optional[float] = None
    #: 1 - delta: the probability the guarantee holds.
    confidence: float = 0.9
    per_class: bool = False
    #: ppi: what to estimate (prevalence of each label, or the mean score).
    estimand: str = "prevalence"
    by: Optional[str] = None
    #: ppi: the contract is met once every interval is at most this wide.
    max_width: Optional[float] = None
    #: no_worse_than_human: the alt-test's cost-benefit allowance.
    epsilon: float = 0.1
    #: budget_first: the human budget the report is computed for.
    human_labels: Optional[int] = None
    human_usd: Optional[float] = None
    #: distributional: tolerated distance between machine and human label
    #: distributions, and the annotator field that defines groups.
    max_distance: Optional[float] = None
    groups_by: Optional[str] = None
    #: threshold_legacy: accept above this raw confidence, no guarantee.
    threshold: Optional[float] = None
    #: Loss tolerance for families with graded correctness (IoU, span F1,
    #: ordinal distance): an item counts as correct when its loss <= tolerance.
    tolerance: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def delta(self) -> float:
        return 1.0 - self.confidence


@dataclass
class HumansConfig:
    pools: List[str] = field(default_factory=lambda: ["team"])
    #: Fraction of calibration labels kept for fitting and threshold choice;
    #: the rest are held out for certification.
    dev_fraction: float = 0.5
    #: Calibration sampling rate; "auto" lets the planner choose from the
    #: contracts' labels-needed projections.
    calibration_rate: Any = "auto"
    min_calibration_per_class: int = 10
    audit_rate: float = 0.02
    overlap: float = 0.0
    #: People per item on the overlap share (at least 2; the alt-test wants 3).
    overlap_k: int = 3
    verify_visibility: str = "shown"
    #: Human labels per item for distributional contracts.
    distribution_k: int = 5
    #: How several people's labels on one item become the label contracts
    #: test against: majority or dawid_skene.
    truth: str = "majority"


@dataclass
class CrowdConfig:
    provider: str = "prolific"
    study_id: Optional[str] = None
    reward_usd: Optional[float] = None
    per_worker_quota: int = 20


@dataclass
class RuntimeConfig:
    batch_size: int = 32
    concurrency: int = 4
    cache: bool = True
    #: Extra attempts for a call that failed transiently (timeout, connection
    #: error, 429/5xx). Every attempt is logged.
    retries: int = 2
    #: Seconds between planner ticks in the server.
    planner_interval: float = 30.0
    #: Minutes a person may hold a request without answering before it goes
    #: back to the pool for someone else.
    hold_minutes: float = 60.0


@dataclass
class EngineConfig:
    enabled: bool = False
    schemas: Optional[List[str]] = None
    sources: List[SourceConfig] = field(default_factory=list)
    cascade: List[str] = field(default_factory=list)
    contracts: List[ContractConfig] = field(default_factory=list)
    humans: HumansConfig = field(default_factory=HumansConfig)
    crowd: CrowdConfig = field(default_factory=CrowdConfig)
    budgets: Dict[str, float] = field(default_factory=dict)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    features: Dict[str, bool] = field(default_factory=dict)
    redaction: Dict[str, Any] = field(default_factory=dict)
    distill: Dict[str, Any] = field(default_factory=dict)
    #: Set when the block was produced by translating legacy keys.
    translated_from: List[str] = field(default_factory=list)

    def source(self, source_id: str) -> Optional[SourceConfig]:
        return next((s for s in self.sources if s.id == source_id), None)

    def feature(self, name: str) -> bool:
        return bool(self.features.get(name, DEFAULT_FEATURES.get(name, False)))

    def config_hash(self) -> str:
        return content_hash({
            "schemas": self.schemas, "cascade": self.cascade,
            "sources": [s.public_params() for s in self.sources],
            "contracts": [c.raw for c in self.contracts],
        })


def _num(errors, path, value, lo=None, hi=None, open_lo=False, open_hi=False,
         integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{path} must be a number (got {value!r})")
        return None
    if integer and int(value) != value:
        errors.append(f"{path} must be a whole number (got {value!r})")
        return None
    if lo is not None and (value <= lo if open_lo else value < lo):
        errors.append(f"{path} must be {'>' if open_lo else '>='} {lo} (got {value})")
        return None
    if hi is not None and (value >= hi if open_hi else value > hi):
        errors.append(f"{path} must be {'<' if open_hi else '<='} {hi} (got {value})")
        return None
    return int(value) if integer else float(value)


def _parse_source(errors, i, raw) -> Optional[SourceConfig]:
    path = f"labeling_engine.sources[{i}]"
    if not isinstance(raw, dict):
        errors.append(f"{path} must be a mapping")
        return None
    sid = raw.get("id")
    kind = raw.get("kind")
    if not sid or not isinstance(sid, str):
        errors.append(f"{path}.id is required")
    if kind not in SOURCE_KINDS:
        errors.append(f"{path}.kind must be one of {', '.join(SOURCE_KINDS)} (got {kind!r})")
    unknown = sorted(set(raw) - set(SOURCE_FIELDS))
    if unknown:
        errors.append(f"{path} has unknown keys: {', '.join(unknown)}")
    conf = raw.get("confidence") or {"method": "auto"}
    if isinstance(conf, str):
        conf = {"method": conf}
    if not isinstance(conf, dict) or conf.get("method", "auto") not in CONFIDENCE_METHODS:
        errors.append(f"{path}.confidence.method must be one of "
                      f"{', '.join(CONFIDENCE_METHODS)}")
        conf = {"method": "auto"}
    if kind == "detector" and not raw.get("endpoint_type"):
        raw = {**raw, "endpoint_type": "yolo"}
    if kind in ("llm", "vlm", "decision", "judge") and not raw.get("endpoint_type"):
        errors.append(f"{path}.endpoint_type is required for a {kind} source")
    etype = raw.get("endpoint_type")
    if kind == "decision" and etype and etype not in DECISION_ENDPOINT_TYPES:
        errors.append(f"{path}: endpoint_type {etype!r} is not a decision model "
                      f"({', '.join(DECISION_ENDPOINT_TYPES)}); for a model that writes "
                      "its answer, use kind: llm")
    if kind in ("llm", "vlm", "judge") and etype in DECISION_ENDPOINT_TYPES:
        errors.append(f"{path}: endpoint_type {etype!r} is a decision model, which picks "
                      f"a label but cannot write text; use kind: decision")
    if etype == "systemone" and not raw.get("base_url"):
        errors.append(f"{path}.base_url is required for endpoint_type systemone "
                      "(the /v1/systemone server, e.g. http://localhost:8009)")
    if kind == "jury" and len(raw.get("members") or []) < 2:
        errors.append(f"{path}.members must list at least two source ids")
    if kind == "static" and not (raw.get("field") or raw.get("predictions_file")):
        errors.append(f"{path} needs field or predictions_file")
    if raw.get("temperature") is not None:
        _num(errors, f"{path}.temperature", raw["temperature"], 0, 2)
    if raw.get("max_tokens") is not None:
        _num(errors, f"{path}.max_tokens", raw["max_tokens"], 1, integer=True)
    if errors and (not sid or kind not in SOURCE_KINDS):
        return None
    return SourceConfig(
        id=sid, kind=kind, endpoint_type=raw.get("endpoint_type") or "",
        model=raw.get("model") or "", base_url=raw.get("base_url"),
        api_key=raw.get("api_key"), temperature=float(raw.get("temperature") or 0.0),
        max_tokens=int(raw.get("max_tokens") or 256), timeout=raw.get("timeout"),
        prompt=raw.get("prompt"), confidence=dict(conf),
        concurrency=raw.get("concurrency"), members=list(raw.get("members") or []),
        aggregation=raw.get("aggregation") or "plurality",
        schemas=raw.get("schemas"), options=dict(raw.get("options") or {}),
        raw=dict(raw))


#: Keys each contract kind reads (beyond id, kind, schema, confidence). An
#: unknown key, a typo of one of these, used to be ignored without a word.
CONTRACT_FIELDS = {
    "selective_risk": ("error", "per_class", "tolerance"),
    "ppi": ("estimand", "by", "max_width", "tier"),
    "no_worse_than_human": ("epsilon", "tolerance", "metric", "min_items_per_annotator"),
    "budget_first": ("human_labels", "human_usd", "error", "reward_per_label_usd"),
    "distributional": ("max_distance", "groups_by"),
    "threshold_legacy": ("threshold", "per_class"),
}


def _parse_contract(errors, i, raw, scheme_names) -> Optional[ContractConfig]:
    path = f"labeling_engine.contracts[{i}]"
    if not isinstance(raw, dict):
        errors.append(f"{path} must be a mapping")
        return None
    kind = raw.get("kind")
    if kind not in CONTRACT_KINDS:
        errors.append(f"{path}.kind must be one of {', '.join(CONTRACT_KINDS)} (got {kind!r})")
        return None
    known = {"id", "kind", "schema", "confidence"} | set(CONTRACT_FIELDS.get(kind, ()))
    unknown = sorted(set(raw) - known)
    if unknown:
        errors.append(f"{path} ({kind}) has unknown keys: {', '.join(unknown)} "
                      f"(known: {', '.join(sorted(known))})")
    schema = raw.get("schema")
    if not schema:
        errors.append(f"{path}.schema is required")
    elif scheme_names is not None and schema not in scheme_names:
        errors.append(f"{path}.schema {schema!r} is not an annotation scheme")
    conf = raw.get("confidence", 0.9)
    conf = _num(errors, f"{path}.confidence", conf, 0, 1, open_lo=True, open_hi=True)
    c = ContractConfig(id=raw.get("id") or f"{kind}:{schema}", kind=kind,
                       schema=schema or "", confidence=conf if conf is not None else 0.9,
                       per_class=bool(raw.get("per_class", False)), raw=dict(raw))
    if raw.get("tolerance") is not None:
        c.tolerance = _num(errors, f"{path}.tolerance", raw["tolerance"], 0, 1)
    if kind == "selective_risk":
        if raw.get("error") is None:
            errors.append(f"{path}.error is required for selective_risk")
        else:
            c.error = _num(errors, f"{path}.error", raw["error"], 0, 1, open_hi=True)
    elif kind == "ppi":
        c.estimand = raw.get("estimand", "prevalence")
        if c.estimand not in ("prevalence", "mean"):
            errors.append(f"{path}.estimand must be prevalence or mean")
        c.by = raw.get("by")
        if raw.get("max_width") is not None:
            c.max_width = _num(errors, f"{path}.max_width", raw["max_width"], 0, 1,
                               open_lo=True)
    elif kind == "no_worse_than_human":
        eps = _num(errors, f"{path}.epsilon", raw.get("epsilon", 0.1), 0, 1)
        c.epsilon = 0.1 if eps is None else eps
    elif kind == "budget_first":
        if raw.get("human_labels") is None and raw.get("human_usd") is None:
            errors.append(f"{path} needs human_labels or human_usd")
        if raw.get("human_labels") is not None:
            c.human_labels = _num(errors, f"{path}.human_labels", raw["human_labels"],
                                  0, integer=True)
        if raw.get("human_usd") is not None:
            c.human_usd = _num(errors, f"{path}.human_usd", raw["human_usd"], 0)
    elif kind == "distributional":
        if raw.get("max_distance") is not None:
            c.max_distance = _num(errors, f"{path}.max_distance", raw["max_distance"], 0, 1)
        c.groups_by = raw.get("groups_by")
    elif kind == "threshold_legacy":
        if raw.get("threshold") is None:
            errors.append(f"{path}.threshold is required for threshold_legacy")
        else:
            c.threshold = _num(errors, f"{path}.threshold", raw["threshold"], 0, 1)
    return c


#: Keys of each mapping in the labeling_engine block; anything else is refused.
BLOCK_KEYS = ("enabled", "schemas", "sources", "cascade", "contracts", "humans", "crowd",
              "budgets", "runtime", "features", "redaction", "distill")
HUMANS_KEYS = ("pools", "dev_fraction", "calibration_rate", "min_calibration_per_class",
               "distribution_k", "overlap_k", "audit_rate", "overlap", "truth",
               "verify_visibility")
CROWD_KEYS = ("provider", "study_id", "reward_usd", "per_worker_quota")
RUNTIME_KEYS = ("batch_size", "concurrency", "retries", "cache", "planner_interval",
                "hold_minutes")
REDACTION_KEYS = ("categories",)
DISTILL_KEYS = ("trainer", "min_labels", "every", "include_silver", "modality",
                "image_field")


def parse_engine_config(config_data: Dict[str, Any]) -> EngineConfig:
    """Parse and validate ``config_data['labeling_engine']``."""
    block = config_data.get("labeling_engine")
    if block is None:
        return EngineConfig(enabled=False)
    if not isinstance(block, dict):
        raise EngineConfigError(["labeling_engine must be a mapping"])
    errors: List[str] = []
    schemes = config_data.get("annotation_schemes")
    scheme_names = ({s.get("name") for s in schemes if isinstance(s, dict)}
                    if isinstance(schemes, list) else None)

    # A typo in any of these blocks used to be ignored without a word.
    for where, mapping, known in (("labeling_engine", block, BLOCK_KEYS),
                                  ("labeling_engine.humans", block.get("humans"), HUMANS_KEYS),
                                  ("labeling_engine.crowd", block.get("crowd"), CROWD_KEYS),
                                  ("labeling_engine.runtime", block.get("runtime"), RUNTIME_KEYS),
                                  ("labeling_engine.redaction", block.get("redaction"),
                                   REDACTION_KEYS),
                                  ("labeling_engine.distill", block.get("distill"), DISTILL_KEYS)):
        if isinstance(mapping, dict):
            unknown = sorted(set(mapping) - set(known))
            if unknown:
                hint = [f" (turn it on with features.{k})" for k in unknown
                        if where == "labeling_engine" and k in FEATURES]
                errors.append(f"{where} has unknown keys: {', '.join(unknown)}"
                              f"{hint[0] if len(unknown) == 1 and hint else ''}; "
                              f"known: {', '.join(known)}")

    cfg = EngineConfig(enabled=bool(block.get("enabled", False)))
    if block.get("schemas") is not None:
        if not isinstance(block["schemas"], list):
            errors.append("labeling_engine.schemas must be a list of scheme names")
        else:
            cfg.schemas = list(block["schemas"])
            for name in cfg.schemas:
                if scheme_names is not None and name not in scheme_names:
                    errors.append(f"labeling_engine.schemas: {name!r} is not an "
                                  "annotation scheme")

    raw_sources = block.get("sources") or []
    if not isinstance(raw_sources, list):
        errors.append("labeling_engine.sources must be a list")
        raw_sources = []
    for i, raw in enumerate(raw_sources):
        s = _parse_source(errors, i, raw)
        if s is not None:
            cfg.sources.append(s)
    ids = [s.id for s in cfg.sources]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        errors.append(f"labeling_engine.sources: duplicate ids {', '.join(dupes)}")
    for s in cfg.sources:
        for m in s.members:
            if m not in ids:
                errors.append(f"labeling_engine.sources[{s.id}].members: unknown source {m!r}")
            elif m == s.id:
                errors.append(f"labeling_engine.sources[{s.id}] cannot be its own member")

    cascade = block.get("cascade")
    if cascade is None:
        cfg.cascade = ids[:1]
    elif not isinstance(cascade, list):
        errors.append("labeling_engine.cascade must be a list of source ids")
    else:
        cfg.cascade = [c if isinstance(c, str) else (c or {}).get("source") for c in cascade]
        for c in cfg.cascade:
            if c not in ids:
                errors.append(f"labeling_engine.cascade: unknown source {c!r}")
    if cfg.enabled and not cfg.sources:
        errors.append("labeling_engine.sources: an enabled engine needs at least one source")

    raw_contracts = block.get("contracts") or []
    if not isinstance(raw_contracts, list):
        errors.append("labeling_engine.contracts must be a list")
        raw_contracts = []
    for i, raw in enumerate(raw_contracts):
        c = _parse_contract(errors, i, raw, scheme_names)
        if c is not None:
            cfg.contracts.append(c)
    cids = [c.id for c in cfg.contracts]
    dupes = sorted({x for x in cids if cids.count(x) > 1})
    if dupes:
        errors.append(f"labeling_engine.contracts: duplicate ids {', '.join(dupes)}")

    hb = block.get("humans") or {}
    if not isinstance(hb, dict):
        errors.append("labeling_engine.humans must be a mapping")
        hb = {}
    h = HumansConfig()
    pools = hb.get("pools", h.pools)
    if isinstance(pools, str):
        pools = [pools]
    bad = [p for p in pools or [] if p not in POOLS]
    if bad or not pools:
        errors.append(f"labeling_engine.humans.pools must list some of {', '.join(POOLS)}")
    h.pools = [p for p in pools or [] if p in POOLS] or ["team"]
    if "dev_fraction" in hb:
        h.dev_fraction = _num(errors, "labeling_engine.humans.dev_fraction",
                              hb["dev_fraction"], 0, 1, open_lo=True, open_hi=True) or 0.5
    if "calibration_rate" in hb and hb["calibration_rate"] != "auto":
        h.calibration_rate = _num(errors, "labeling_engine.humans.calibration_rate",
                                  hb["calibration_rate"], 0, 1, open_lo=True) or "auto"
    for key, integer in (("min_calibration_per_class", True), ("distribution_k", True),
                         ("overlap_k", True)):
        if key in hb:
            val = _num(errors, f"labeling_engine.humans.{key}", hb[key], 1, integer=integer)
            if val is not None:
                setattr(h, key, val)
    for key in ("audit_rate", "overlap"):
        if key in hb:
            val = _num(errors, f"labeling_engine.humans.{key}", hb[key], 0, 1)
            if val is not None:
                setattr(h, key, val)
    if "truth" in hb:
        if hb["truth"] not in ("majority", "dawid_skene"):
            errors.append("labeling_engine.humans.truth must be majority or dawid_skene")
        else:
            h.truth = hb["truth"]
    if "verify_visibility" in hb:
        if hb["verify_visibility"] not in VISIBILITIES:
            errors.append("labeling_engine.humans.verify_visibility must be blind or shown")
        else:
            h.verify_visibility = hb["verify_visibility"]
    cfg.humans = h

    cb = block.get("crowd") or {}
    cfg.crowd = CrowdConfig(
        provider=cb.get("provider", "prolific"), study_id=cb.get("study_id"),
        reward_usd=cb.get("reward_usd"), per_worker_quota=int(cb.get("per_worker_quota", 20)))
    if "crowd" in cfg.humans.pools and cfg.crowd.provider != "prolific":
        errors.append("labeling_engine.crowd.provider: only prolific can be driven by "
                      "the engine")

    budgets = block.get("budgets") or {}
    for key, val in budgets.items():
        if key not in ("model_usd", "human_usd", "human_labels"):
            errors.append(f"labeling_engine.budgets.{key} is not a budget "
                          "(model_usd, human_usd, human_labels)")
            continue
        v = _num(errors, f"labeling_engine.budgets.{key}", val, 0)
        if v is not None:
            cfg.budgets[key] = v

    rb = block.get("runtime") or {}
    rt = RuntimeConfig()
    for key, lo in (("batch_size", 1), ("concurrency", 1), ("retries", 0)):
        if key in rb:
            v = _num(errors, f"labeling_engine.runtime.{key}", rb[key], lo, integer=True)
            if v is not None:
                setattr(rt, key, v)
    if "cache" in rb:
        rt.cache = bool(rb["cache"])
    if "planner_interval" in rb:
        rt.planner_interval = _num(errors, "labeling_engine.runtime.planner_interval",
                                   rb["planner_interval"], 1) or rt.planner_interval
    if "hold_minutes" in rb:
        rt.hold_minutes = _num(errors, "labeling_engine.runtime.hold_minutes",
                               rb["hold_minutes"], 1) or rt.hold_minutes
    cfg.runtime = rt

    feats = block.get("features") or {}
    for key, val in feats.items():
        if key not in FEATURES:
            errors.append(f"labeling_engine.features.{key} is not a feature "
                          f"({', '.join(FEATURES)})")
        else:
            cfg.features[key] = bool(val)
    if cfg.feature("crowd_live_spend"):
        if "crowd" not in cfg.humans.pools:
            errors.append("labeling_engine.features.crowd_live_spend needs the crowd pool")
        if cfg.budgets.get("human_usd") is None:
            errors.append("labeling_engine.features.crowd_live_spend needs "
                          "budgets.human_usd: live crowd spend is never unbounded")

    for key in ("redaction", "distill"):
        val = block.get(key) or {}
        if not isinstance(val, dict):
            errors.append(f"labeling_engine.{key} must be a mapping")
        else:
            setattr(cfg, key, dict(val))
    if cfg.distill.get("modality", "auto") not in ("auto", "text", "image"):
        errors.append("labeling_engine.distill.modality must be auto, text or image")

    # Setups the documentation says cannot work, caught here rather than
    # discovered at run time.
    labels_of = {s.get("name"): len(s.get("labels") or [])
                 for s in (schemes or []) if isinstance(s, dict)}
    for src in cfg.sources:
        method = (src.confidence or {}).get("method", "auto")
        if method == "native" and src.kind == "llm":
            errors.append(f"labeling_engine.sources[{src.id}].confidence.method native "
                          "comes from decision models and detectors; an llm source "
                          "uses verbalized, k_sample or logprob")
        if method == "logprob":
            names = src.schemas or [n for n in labels_of if n in (cfg.schemas or labels_of)]
            wide = [n for n in names if labels_of.get(n, 0) > 20]
            if wide:
                errors.append(f"labeling_engine.sources[{src.id}]: logprob confidence reads "
                              f"at most 20 alternatives per answer, and {', '.join(wide)} "
                              "has more labels; use verbalized or k_sample there")
    if any(c.kind == "no_worse_than_human" for c in cfg.contracts) \
            and int(cfg.humans.overlap_k or 0) < 3:
        errors.append("labeling_engine.humans.overlap_k must be at least 3 for a "
                      "no_worse_than_human contract (the alt-test leaves one person out "
                      "and compares with at least two others)")

    if errors:
        raise EngineConfigError(errors)
    return cfg
