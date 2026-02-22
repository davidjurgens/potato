"""
NLP Export Utilities

Shared helpers for NLP export formats (CoNLL-2003, CoNLL-U).
Provides tokenization and BIO tag alignment.
"""

from typing import List, Dict, Tuple, Optional
import logging
import re

logger = logging.getLogger(__name__)


def tokenize_text(text: str, method: str = "whitespace") -> List[Dict]:
    """
    Tokenize text into tokens with character offsets.

    Args:
        text: Input text string
        method: Tokenization method. Options:
            - "whitespace": Split on whitespace (default)
            - "word_punct": Split on word boundaries and punctuation

    Returns:
        List of dicts with keys: token, start, end
    """
    if not text:
        return []

    if method == "word_punct":
        tokens = []
        for match in re.finditer(r'\S+', text):
            raw = match.group()
            raw_start = match.start()
            # Split punctuation from word boundaries
            sub_tokens = re.finditer(r'[\w]+|[^\w\s]', raw)
            for sub in sub_tokens:
                tokens.append({
                    "token": sub.group(),
                    "start": raw_start + sub.start(),
                    "end": raw_start + sub.end(),
                })
        return tokens

    # Default: whitespace tokenization
    tokens = []
    for match in re.finditer(r'\S+', text):
        tokens.append({
            "token": match.group(),
            "start": match.start(),
            "end": match.end(),
        })
    return tokens


def char_spans_to_bio_tags(
    tokens: List[Dict],
    spans: List[Dict],
    scheme: str = "BIO"
) -> List[str]:
    """
    Convert character-level spans to token-level BIO tags.

    Handles:
    - Multi-token entities
    - Tokens partially inside spans (included if majority overlap)
    - Overlapping spans (longest match wins)

    Args:
        tokens: List of token dicts with keys: token, start, end
        spans: List of span dicts with keys: start, end, label (or name)
        scheme: Tagging scheme - "BIO" (default) or "BIOES"

    Returns:
        List of BIO tag strings, one per token (e.g., ["O", "B-PER", "I-PER"])
    """
    if not tokens:
        return []

    tags = ["O"] * len(tokens)

    if not spans:
        return tags

    # Sort spans by length (longest first) so longest match wins on overlap
    sorted_spans = sorted(
        spans,
        key=lambda s: (s.get("end", 0) - s.get("start", 0)),
        reverse=True,
    )

    # Track which tokens are already assigned
    assigned = [False] * len(tokens)

    for span in sorted_spans:
        span_start = span.get("start", 0)
        span_end = span.get("end", 0)
        label = span.get("label") or span.get("name", "ENTITY")

        if span_start >= span_end:
            continue

        # Find tokens that overlap with this span
        span_tokens = []
        for i, tok in enumerate(tokens):
            if assigned[i]:
                continue
            # Calculate overlap
            overlap_start = max(tok["start"], span_start)
            overlap_end = min(tok["end"], span_end)
            overlap = max(0, overlap_end - overlap_start)
            tok_len = tok["end"] - tok["start"]
            if tok_len > 0 and overlap > 0:
                # Include token if overlap covers majority of the token
                if overlap >= tok_len / 2:
                    span_tokens.append(i)

        if not span_tokens:
            continue

        # Assign BIO tags
        for j, tok_idx in enumerate(span_tokens):
            if j == 0:
                tags[tok_idx] = f"B-{label}"
            else:
                tags[tok_idx] = f"I-{label}"
            assigned[tok_idx] = True

        # Apply BIOES if requested
        if scheme == "BIOES" and span_tokens:
            if len(span_tokens) == 1:
                tags[span_tokens[0]] = f"S-{label}"
            else:
                tags[span_tokens[-1]] = f"E-{label}"

    return tags


def group_sentences(tokens: List[Dict], text: str) -> List[List[int]]:
    """
    Group token indices into sentences based on sentence-ending punctuation.

    Args:
        tokens: List of token dicts
        text: Original text

    Returns:
        List of lists of token indices, one list per sentence
    """
    if not tokens:
        return []

    sentences = []
    current = []

    for i, tok in enumerate(tokens):
        current.append(i)
        # Sentence boundary: token ends with sentence-final punctuation
        # and is followed by whitespace + uppercase or end of text
        token_text = tok["token"]
        ends_with_sent_punct = (
            token_text in (".", "!", "?", "...", "。")
            or token_text.endswith(".")
            or token_text.endswith("!")
            or token_text.endswith("?")
        )
        if ends_with_sent_punct:
            # Check if next token starts a new sentence (uppercase or end)
            if i + 1 >= len(tokens):
                sentences.append(current)
                current = []
            else:
                next_tok = tokens[i + 1]["token"]
                if next_tok and next_tok[0].isupper():
                    sentences.append(current)
                    current = []

    if current:
        sentences.append(current)

    return sentences
