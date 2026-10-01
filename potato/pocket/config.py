"""Configuration and schema-capability rules for Pocket Mode."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Schema types that translate well to a phone-sized touch UI. Everything else
# (spans, bounding boxes, video timelines, rating matrices, ...) is a desktop
# task and is reported as incompatible rather than degraded onto touch.
# `textbox` was in this set and is not one of the registry's 61 annotation
# types -- the free-text type is `text`, which is also here. Harmless while
# nobody reads the set as the list of what works, which is the only thing it is
# for. `tests/unit/test_audit34_pocket.py` asserts every name against the
# registry so the next dead entry fails a test instead of shipping.
POCKET_CAPABLE_TYPES = {
    "radio",
    "multiselect",
    "likert",
    "slider",
    "number",
    "text",
    "pure_display",
}

#: Types that work on the regular annotate page from a phone, checked by
#: driving them with touch input in tests/playwright/test_mobile_layouts.py.
#: A superset of POCKET_CAPABLE_TYPES: Pocket is one card per item with one
#: tap per label, which is a narrower thing than "usable by touch". The
#: "use a desktop browser" warning is shown only for types outside this set,
#: where it used to fire for every task Pocket could not host -- including
#: pairwise and best-worst scaling, which are big-button tasks. Add a type
#: here only with a test that drives it by touch.
TOUCH_USABLE_TYPES = POCKET_CAPABLE_TYPES | {
    "select",
    "multirate",
    "pairwise",
    "bws",
    "ranking",
    "semantic_differential",
    "span",
    "image_annotation",
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


def touch_usability(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """(usable_by_touch, scheme_names_that_are_not) for the configured task."""
    limited = [scheme.get("name", "?")
               for scheme in config.get("annotation_schemes", []) or []
               if scheme.get("annotation_type") not in TOUCH_USABLE_TYPES]
    return (len(limited) == 0, limited)


def pocket_capability(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """(capable, incompatible_scheme_names) for the configured task."""
    incompatible = []
    for scheme in config.get("annotation_schemes", []) or []:
        if scheme.get("annotation_type") not in POCKET_CAPABLE_TYPES:
            incompatible.append(scheme.get("name", "?"))
    return (len(incompatible) == 0, incompatible)
