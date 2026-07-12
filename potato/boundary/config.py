"""Configuration parsing for Boundary Lab (``boundary_probing:`` YAML block)."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VALID_SOURCES = ("precomputed", "llm", "rules")


@dataclass
class BoundaryConfig:
    """Parsed ``boundary_probing`` configuration.

    Attributes:
        enabled: Master switch for the feature.
        schema: Name of the annotation scheme whose labels are probed.
            Defaults to the first radio scheme in ``annotation_schemes``.
        probes_per_item: Total probes shown per (instance, label), including
            the invariance probe when ``include_invariance`` is on.
        include_invariance: Whether to include a meaning-preserving paraphrase
            probe (the quality-control signal).
        sources: Ordered generation tiers. Earlier tiers win; later tiers fill
            remaining probe slots.
        precomputed_key: Item-data field holding precomputed counterfactuals:
            a list of ``{"text": ..., "kind": "flip"|"invariance"}`` dicts.
        rationale_on_flip: Ask for a short free-text rationale when the
            annotator says a probe flips their label.
        debounce_ms: Frontend delay between label selection and probe fetch.
        ai_support: Optional endpoint override; falls back to the global
            ``ai_support`` block when omitted.
    """

    enabled: bool = False
    schema: Optional[str] = None
    probes_per_item: int = 3
    include_invariance: bool = True
    sources: List[str] = field(default_factory=lambda: list(VALID_SOURCES))
    precomputed_key: str = "counterfactuals"
    rationale_on_flip: bool = True
    debounce_ms: int = 900
    ai_support: Optional[Dict[str, Any]] = None


def parse_boundary_config(config: Dict[str, Any]) -> BoundaryConfig:
    """Build a :class:`BoundaryConfig` from the full app config dict.

    Resolves the default probed schema to the first radio scheme when the
    ``schema`` key is omitted.
    """
    block = config.get("boundary_probing") or {}
    bc = BoundaryConfig(
        enabled=bool(block.get("enabled", False)),
        schema=block.get("schema"),
        probes_per_item=int(block.get("probes_per_item", 3)),
        include_invariance=bool(block.get("include_invariance", True)),
        sources=list(block.get("sources", list(VALID_SOURCES))),
        precomputed_key=block.get("precomputed_key", "counterfactuals"),
        rationale_on_flip=bool(block.get("rationale_on_flip", True)),
        debounce_ms=int(block.get("debounce_ms", 900)),
        ai_support=block.get("ai_support"),
    )

    bad_sources = [s for s in bc.sources if s not in VALID_SOURCES]
    if bad_sources:
        logger.warning(
            "boundary_probing.sources contains unknown entries %s; valid: %s",
            bad_sources,
            list(VALID_SOURCES),
        )
        bc.sources = [s for s in bc.sources if s in VALID_SOURCES]

    if bc.probes_per_item < 1:
        logger.warning("boundary_probing.probes_per_item must be >= 1; using 1")
        bc.probes_per_item = 1

    if bc.enabled and not bc.schema:
        for scheme in config.get("annotation_schemes", []) or []:
            if scheme.get("annotation_type") == "radio":
                bc.schema = scheme.get("name")
                break
        if bc.schema:
            logger.info("boundary_probing.schema not set; defaulting to '%s'", bc.schema)
        else:
            logger.warning(
                "boundary_probing enabled but no radio scheme found and no "
                "schema configured; probing will be inactive"
            )

    return bc
