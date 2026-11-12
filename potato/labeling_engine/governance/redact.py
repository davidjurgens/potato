"""
Masking personal data before text leaves for a remote model.

Applied by ``RunContext.call`` when ``features.pii_redaction`` is on and the
endpoint is remote. What is recorded is the category counts and a short hash
of each masked span, never the span itself: the call log is exported with the
dataset, and a log that kept the redacted text would leak exactly what the
redaction was for.

The patterns are deliberately simple and err toward masking. They are not a
compliance tool, and the docs say so. A study under an IRB that forbids
sending personal data off-site should use only local sources, which the
config can enforce by listing none that are remote.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, Optional, Tuple

PATTERNS: Dict[str, re.Pattern] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "url": re.compile(r"\bhttps?://[^\s<>\"']+"),
    "ip": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(
        r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?!\w)"),
    "handle": re.compile(r"(?<![\w@])@[A-Za-z0-9_]{2,30}\b"),
}

#: Applied in this order, so a URL containing an email-like part is masked as
#: a URL and a card number is not half-masked as a phone number.
ORDER = ("email", "url", "ip", "card", "ssn", "phone", "handle")
DEFAULT_CATEGORIES = ORDER


def _span_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def redact(text: str, categories: Optional[Iterable[str]] = None
           ) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Return ``(masked_text, info)``; ``info`` is None when nothing matched.

    Each match becomes ``[EMAIL]``, ``[PHONE]`` and so on, so the model still
    knows something was there.
    """
    if not text:
        return text, None
    wanted = [c for c in ORDER if c in set(categories or DEFAULT_CATEGORIES)]
    counts: Dict[str, int] = {}
    hashes = []
    out = text
    for cat in wanted:
        def _sub(m, cat=cat):
            counts[cat] = counts.get(cat, 0) + 1
            hashes.append(f"{cat}:{_span_hash(m.group(0))}")
            return f"[{cat.upper()}]"
        out = PATTERNS[cat].sub(_sub, out)
    if not counts:
        return text, None
    return out, {"categories": counts, "spans": hashes}
