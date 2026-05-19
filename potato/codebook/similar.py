"""
Soft suggest-on-create helpers (Phase 2 #1 resolution).

When an annotator (or, in solo mode, the LLM) is about to add a code —
especially via in-vivo coding where the name is derived from a text
selection — near-duplicates proliferate fast ("cost", "costs", "cost
concerns"). Rather than block or silently merge, we *suggest*: surface
existing codes that closely match the proposed name so the annotator
can reuse one. Non-destructive and adjudicator-free, so it works in
solo mode too.

Pure functions, no I/O — unit-testable in isolation.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher, get_close_matches
from typing import List

_WS = re.compile(r"\s+")
# Conservative default: 0.78 catches "cost concern" ~ "cost concerns"
# and case/space variants without dragging in merely topical names.
DEFAULT_CUTOFF = 0.78
MAX_CODE_NAME = 60


def _norm(s: str) -> str:
    return _WS.sub(" ", str(s or "")).strip().lower()


def derive_code_name(text: str, cap: int = MAX_CODE_NAME) -> str:
    """Propose a code name from a raw text selection: collapse
    whitespace, trim, and cap length at a word boundary when possible.
    Mirrors the client-side derivation (codebook.js) — keep in sync."""
    s = _WS.sub(" ", str(text or "")).strip()
    if len(s) <= cap:
        return s
    head = s[:cap].rsplit(" ", 1)[0]
    return (head or s[:cap]).strip()


def similar_code_names(
    names: List[str], proposed: str,
    cutoff: float = DEFAULT_CUTOFF, n: int = 5,
) -> List[str]:
    """Existing code names that closely match `proposed` (normalized),
    ordered best-first, returned in their ORIGINAL casing. An exact
    normalized match is always included first."""
    p = _norm(proposed)
    if not p:
        return []
    norm_to_orig = {}
    for original in names:
        norm_to_orig.setdefault(_norm(original), original)
    keys = list(norm_to_orig.keys())

    ordered: List[str] = []
    if p in norm_to_orig:                       # exact (normalized) hit
        ordered.append(norm_to_orig[p])

    for key in get_close_matches(p, keys, n=n, cutoff=cutoff):
        orig = norm_to_orig[key]
        if orig not in ordered:
            ordered.append(orig)

    # Stable best-first ordering by similarity ratio.
    ordered.sort(
        key=lambda o: SequenceMatcher(None, p, _norm(o)).ratio(),
        reverse=True,
    )
    return ordered[:n]
