"""Configuration and schema-capability rules for Pocket Mode."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Schema types that translate well to a phone-sized touch UI. Everything else
# (spans, bounding boxes, video timelines, rating matrices, ...) is a desktop
# task and is reported as incompatible rather than degraded onto touch.
POCKET_CAPABLE_TYPES = {
    "radio",
    "multiselect",
    "likert",
    "slider",
    "number",
    "text",
    "textbox",
    "pure_display",
}


@dataclass
class PocketConfig:
    """Parsed ``pocket`` configuration.

    Attributes:
        enabled: Master switch for the /pocket surface.
        batch_size: Items served per /pocket/api/batch request (prefetch +
            offline queue depth).
        auto_redirect: When the task is pocket-capable, send phones/tablets
            that open /annotate to /pocket automatically. They can opt back
            out via the "Desktop site" link (?desktop=1).
    """

    enabled: bool = False
    batch_size: int = 25
    auto_redirect: bool = True


def parse_pocket_config(config: Dict[str, Any]) -> PocketConfig:
    block = config.get("pocket") or {}
    pc = PocketConfig(
        enabled=bool(block.get("enabled", False)),
        batch_size=int(block.get("batch_size", 25)),
        auto_redirect=bool(block.get("auto_redirect", True)),
    )
    if not 1 <= pc.batch_size <= 200:
        logger.warning("pocket.batch_size must be 1-200; using 25")
        pc.batch_size = 25
    return pc


def pocket_capability(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """(capable, incompatible_scheme_names) for the configured task."""
    incompatible = []
    for scheme in config.get("annotation_schemes", []) or []:
        if scheme.get("annotation_type") not in POCKET_CAPABLE_TYPES:
            incompatible.append(scheme.get("name", "?"))
    return (len(incompatible) == 0, incompatible)
