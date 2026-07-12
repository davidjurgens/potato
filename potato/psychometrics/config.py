"""Configuration parsing for Psychometrics (``psychometrics:`` YAML block)."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Scheme types the IRT model can score: single categorical choice per item.
SUPPORTED_SCHEME_TYPES = ("radio", "likert")


@dataclass
class PsychometricsConfig:
    """Parsed ``psychometrics`` configuration.

    Attributes:
        enabled: Master switch for the psychometric layer (model fitting,
            dashboard, export). Adaptive routing additionally requires
            ``assignment_strategy: psychometric`` at the top level.
        schema: Annotation scheme the model scores. Defaults to the first
            radio or likert scheme.
        refit_interval: Refit the model once this many new labels have
            arrived since the last fit (fits are milliseconds; the dashboard
            always forces a fresh fit).
        min_observations: Cold-start gate — adaptive routing defers to the
            random fallback until this many labels exist, so early
            assignments build the annotator overlap the model needs.
        min_annotators_per_item: An item is never early-stopped with fewer
            annotators than this, no matter how confident the posterior.
        confidence_threshold: Posterior probability at which an item counts
            as resolved: routing deprioritizes it and the dashboard counts
            its remaining annotator slots as saved judgments.
        cost_per_judgment: Optional cost (any currency) used to express
            saved judgments as money on the dashboard and in the designer.
        discrimination_flag_threshold: Items whose ability-vs-correctness
            correlation falls below this are flagged as likely codebook
            bugs (best annotators losing to the crowd).
    """

    enabled: bool = False
    schema: Optional[str] = None
    refit_interval: int = 5
    min_observations: int = 20
    min_annotators_per_item: int = 2
    confidence_threshold: float = 0.95
    cost_per_judgment: Optional[float] = None
    discrimination_flag_threshold: float = -0.2


def parse_psychometrics_config(config: Dict[str, Any]) -> PsychometricsConfig:
    """Build a :class:`PsychometricsConfig` from the full app config dict."""
    block = config.get("psychometrics") or {}
    ps = PsychometricsConfig(
        enabled=bool(block.get("enabled", False)),
        schema=block.get("schema"),
        refit_interval=max(1, int(block.get("refit_interval", 5))),
        min_observations=max(0, int(block.get("min_observations", 20))),
        min_annotators_per_item=max(1, int(block.get("min_annotators_per_item", 2))),
        confidence_threshold=float(block.get("confidence_threshold", 0.95)),
        discrimination_flag_threshold=float(
            block.get("discrimination_flag_threshold", -0.2)
        ),
    )
    if not 0.5 <= ps.confidence_threshold <= 1.0:
        logger.warning(
            "psychometrics.confidence_threshold %.2f outside [0.5, 1.0]; using 0.95",
            ps.confidence_threshold,
        )
        ps.confidence_threshold = 0.95
    cost = block.get("cost_per_judgment")
    if cost is not None:
        try:
            ps.cost_per_judgment = float(cost)
        except (TypeError, ValueError):
            logger.warning("psychometrics.cost_per_judgment %r is not a number", cost)

    if ps.schema is None:
        for scheme in config.get("annotation_schemes", []) or []:
            if scheme.get("annotation_type") in SUPPORTED_SCHEME_TYPES:
                ps.schema = scheme.get("name")
                break
        if ps.enabled and ps.schema is None:
            logger.warning(
                "psychometrics enabled but no radio/likert scheme found; "
                "the model will have nothing to score"
            )
    return ps
