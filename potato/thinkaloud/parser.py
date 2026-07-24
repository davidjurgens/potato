"""Rule-based label-phrase detection for Think-Aloud Mode.

The annotator may say anything while thinking, but commits a label with a set
phrasing such as "I label this Polite" or "my answer is impolite". Detection is
two-stage and entirely deterministic:

1. **Stem matching** — regexes for the accepted phrasings capture the words
   that follow the stem ("i label this as", "my answer is", ...).
2. **Fuzzy label matching** — the captured words are compared against the
   configured labels: exact normalized match first, then prefix match, then
   ``difflib`` similarity (>= 0.8) to absorb STT mishearings ("in polite" for
   "Impolite").

No LLM anywhere. Transcripts are lowercase-normalized and punctuation-stripped
before matching, since STT punctuation is unreliable.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Sequence

# Stem patterns: each must end by capturing the words that follow into 'rest'.
# {rest} is appended automatically. Kept as plain strings so YAML can override.
DEFAULT_STEMS = [
    r"i(?:'?d|\s+would|\s+will)?\s+(?:label|mark|call|rate|classify|tag)\s+(?:this|it|that)(?:\s+one)?\s+(?:as\s+)?",
    r"label\s+(?:this|it|that)(?:\s+one)?\s+(?:as\s+)?",
    r"my\s+(?:label|answer|rating|choice|verdict)\s+(?:is|would\s+be)\s+",
    r"(?:the\s+)?final\s+answer\s*(?:is\s+)?",
    r"i\s+(?:choose|pick|select|go\s+with|say)\s+",
    r"(?:this|it|that)\s+(?:one\s+)?is\s+definitely\s+",
]

_REST = r"(?P<rest>\S.{0,60})"


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = re.sub(r"[^\w\s'-]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class LabelDetection:
    label: str            # the configured label, verbatim
    matched_text: str     # what the annotator actually said
    stem_text: str        # the phrase stem that triggered detection
    confidence: str       # "exact" | "prefix" | "fuzzy"
    start: int            # character offset of the stem in the normalized text


class LabelPhraseParser:
    """Detects label-commitment phrases in (rolling) transcript text."""

    def __init__(self, labels: Sequence[str],
                 stems: Optional[Sequence[str]] = None,
                 fuzzy_threshold: float = 0.8) -> None:
        self.labels = list(labels)
        self.fuzzy_threshold = fuzzy_threshold
        self._normalized_labels = [(label, normalize(label)) for label in self.labels]
        stems = list(stems) if stems else list(DEFAULT_STEMS)
        self._patterns = [re.compile(stem + _REST, re.IGNORECASE) for stem in stems]

    # ---------------------------------------------------------------- match --
    def _match_label(self, rest: str) -> Optional[tuple]:
        """Match the words following a stem against the configured labels.

        Returns (label, matched_text, confidence) or None. Tries the first
        1..n-word prefixes of `rest`, preferring exact > prefix > fuzzy and
        longer matches over shorter ones within the same tier.
        """
        words = normalize(rest).split()
        if not words:
            return None
        best = None  # (sort_key, label, matched_text, tier)
        for label, norm_label in self._normalized_labels:
            label_words = len(norm_label.split())
            # Try prefixes around the label's own word count (+1 slack for
            # split mishearings like "in polite").
            for k in range(1, min(len(words), label_words + 2) + 1):
                candidate = " ".join(words[:k])
                ratio = SequenceMatcher(None, candidate, norm_label).ratio()
                if candidate == norm_label:
                    tier, ratio = 0, 1.0
                elif norm_label.startswith(candidate) and k >= label_words:
                    tier = 1
                elif candidate.replace(" ", "") == norm_label.replace(" ", ""):
                    tier, ratio = 1, 0.99  # "in polite" -> "impolite"
                elif ratio >= self.fuzzy_threshold:
                    tier = 2
                else:
                    continue
                # Prefer lower tier, then higher similarity, then longer match
                key = (tier, -ratio, -k)
                if best is None or key < best[0]:
                    best = (key, label, candidate, tier)
        if best is None:
            return None
        _key, label, matched, tier = best
        confidence = {0: "exact", 1: "prefix", 2: "fuzzy"}[tier]
        return label, matched, confidence

    @staticmethod
    def _iter_stems(pattern, text: str):
        """Yield every stem match, including ones starting inside an earlier match.

        ``rest`` deliberately captures greedily (labels can be several words),
        so a repeated stem — "I label this polite. I label this neutral." —
        falls inside the first match's ``rest`` and ``finditer`` would skip it,
        silently dropping the annotator's correction. Resuming the scan one
        character past each stem's *start* keeps every commitment visible.
        """
        pos = 0
        while pos <= len(text):
            match = pattern.search(text, pos)
            if match is None:
                return
            yield match
            pos = match.start() + 1

    def parse(self, text: str) -> Optional[LabelDetection]:
        """Return the LAST label-commitment phrase in `text`, or None.

        Last wins so an annotator can change their mind mid-stream, whether or
        not the correction reuses the same phrasing ("I'd call this polite...
        no wait, my answer is neutral" / "I label this polite. I label this
        neutral.").
        """
        if not text:
            return None
        normalized = normalize(text)
        result = None
        for pattern in self._patterns:
            for match in self._iter_stems(pattern, normalized):
                hit = self._match_label(match.group("rest"))
                if not hit:
                    continue
                label, matched_text, confidence = hit
                if result is None or match.start() >= result.start:
                    result = LabelDetection(
                        label=label,
                        matched_text=matched_text,
                        stem_text=normalized[match.start():match.start("rest")].strip(),
                        confidence=confidence,
                        start=match.start(),
                    )
        return result


def count_fillers(text: str, fillers: Sequence[str]) -> int:
    """Occurrences of filler words/phrases (deterministic hesitation signal)."""
    normalized = " " + normalize(text) + " "
    total = 0
    for filler in fillers:
        needle = " " + normalize(filler) + " "
        total += normalized.count(needle)
    return total
