"""
Pocket Mode: mobile-first annotation as a PWA.

A separate touch-optimized surface at ``/pocket`` for the schema types that
make sense on a phone (radio, multiselect, likert, slider, text, number):
card-stack UI, thumb-zone label buttons, swipe navigation, haptics, offline
annotation with background sync, installable to the home screen.

Deliberately additive: saves go through the same ``/updateinstance`` endpoint
the desktop page uses, and desktop-class schemas (spans, bounding boxes,
video timelines) are reported as incompatible rather than degraded onto touch.
"""

from potato.pocket.config import (
    POCKET_CAPABLE_TYPES,
    PocketConfig,
    parse_pocket_config,
    pocket_capability,
)
from potato.pocket.routes import pocket_bp

__all__ = [
    "PocketConfig",
    "parse_pocket_config",
    "POCKET_CAPABLE_TYPES",
    "pocket_capability",
    "pocket_bp",
]
