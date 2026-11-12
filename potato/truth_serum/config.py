"""Configuration parsing for Truth Serum (``truth_serum:`` YAML block)."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_QUESTION = (
    "What percentage of other annotators will choose the same label as you?"
)


@dataclass
class TruthSerumConfig:
    """Parsed ``truth_serum`` configuration.

    Attributes:
        enabled: Master switch.
        schema: Annotation scheme whose labels get popularity predictions.
            Defaults to the first radio scheme.
        question: Prompt shown above the prediction slider.
        min_annotators: Minimum predictions per item before a
            surprisingly-popular verdict is computed.
    """

    enabled: bool = False
    schema: Optional[str] = None
    question: str = DEFAULT_QUESTION
    min_annotators: int = 3


def parse_truth_serum_config(config: Dict[str, Any]) -> TruthSerumConfig:
    """Build a :class:`TruthSerumConfig` from the full app config dict."""
    block = config.get("truth_serum") or {}
    ts = TruthSerumConfig(
        enabled=bool(block.get("enabled", False)),
        schema=block.get("schema"),
        question=str(block.get("question", DEFAULT_QUESTION)),
        min_annotators=int(block.get("min_annotators", 3)),
    )

    if ts.min_annotators < 2:
        logger.warning("truth_serum.min_annotators must be >= 2; using 2")
        ts.min_annotators = 2

    if ts.enabled and not ts.schema:
        for scheme in config.get("annotation_schemes", []) or []:
            if scheme.get("annotation_type") == "radio":
                ts.schema = scheme.get("name")
                break
        if ts.schema:
            logger.info("truth_serum.schema not set; defaulting to '%s'", ts.schema)
        else:
            logger.warning(
                "truth_serum enabled but no radio scheme found and no schema "
                "configured; predictions will be inactive"
            )

    return ts
