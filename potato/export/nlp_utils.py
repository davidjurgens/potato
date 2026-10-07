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
    scheme: str = "BIO",
    warnings: Optional[List[str]] = None,
    where: str = "",
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
            # No token is mostly inside the span ("Trump" in "anti-Trump").
            # Dropping it lost the entity without a word; tag the tokens it
            # touches instead and say so, since the token is wider than what
            # was marked.
            span_tokens = [
                i for i, tok in enumerate(tokens)
                if not assigned[i]
                and min(tok["end"], span_end) > max(tok["start"], span_start)
            ]
            if not span_tokens:
                continue
        if warnings is not None and (tokens[span_tokens[0]]["start"] != span_start
                                     or tokens[span_tokens[-1]]["end"] != span_end):
            covered = " ".join(tokens[i]["token"] for i in span_tokens)
            warnings.append(
                f"{where}: {label} span {span_start}-{span_end} does not "
                f"align with token boundaries; tagged '{covered}'")

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


#: Tokens ending in a period that do not end a sentence.
_ABBREVIATIONS = frozenset({"mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "jr.",
                            "sr.", "vs.", "e.g.", "i.e.", "no.", "fig."})
_INITIALISM = re.compile(r"^(?:[A-Za-z]\.){2,}$")


def group_sentences(tokens: List[Dict], text: str,
                    tags: Optional[List[str]] = None) -> List[List[int]]:
    """
    Group token indices into sentences based on sentence-ending punctuation.

    A period does not end a sentence inside an entity (``tags``: the next
    token's tag continues one), after an initialism such as "U.S.", or after a
    title such as "Dr.". "the U.S. Army" with an ORG span used to export as
    ``U.S. B-ORG``, a sentence break, then ``Army I-ORG``: one entity cut
    across two sentences, which a CoNLL reader cannot put back together.

    Args:
        tokens: List of token dicts
        text: Original text
        tags: BIO tags for the tokens, when known

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
        if ends_with_sent_punct and (
                (tags and i + 1 < len(tags) and tags[i + 1][:2] in ("I-", "E-"))
                or token_text.lower() in _ABBREVIATIONS
                or _INITIALISM.match(token_text)):
            continue
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


def annotator_groups(annotations: List[Dict], annotator: Optional[str],
                     warnings: List[str], fmt: str) -> List[Tuple[str, List[Dict]]]:
    """``[(file suffix, records)]``: one group, or one per annotator.

    CoNLL has one tag column, so it holds one annotator's spans. With
    ``annotator`` set, that annotator's records; otherwise, with several
    annotators, one file each. Keeping only the first record per item made
    the export depend on which annotator was read first, and an annotator
    who marked nothing could replace one who marked everything.
    """
    users = sorted({str(a.get("user_id", "")) for a in annotations})
    if annotator:
        chosen = [a for a in annotations if str(a.get("user_id", "")) == annotator]
        if not chosen:
            warnings.append(f"No annotations by '{annotator}' to export")
        return [("", chosen)]
    if len(users) <= 1:
        return [("", list(annotations))]
    warnings.append(
        f"{len(users)} annotators: wrote one {fmt} file per annotator. Pass "
        f"the 'annotator' option to export one of them as the main file.")
    return [(u, [a for a in annotations if str(a.get("user_id", "")) == u]) for u in users]


def conll_documents(context, records: List[Dict], schema_name: Optional[str],
                    tokenization: str, warnings: List[str]):
    """Yield ``(doc_id, text, tokens, tags, sentences)`` per annotated field.

    The text is what the span offsets were measured against: the field the
    span names (``target_field``), rendered the way the browser renders it
    (``ExportContext._span_anchor_text``). Reading ``item[text_key]`` raw
    tokenised a dialogue field as Python reprs (``{'speaker':``) and tagged
    every token O.
    """
    text_key = (context.config.get("item_properties", {}) or {}).get("text_key", "text")
    for ann in records:
        instance_id = ann.get("instance_id", "")
        item = context.items.get(instance_id, {})
        by_field: Dict[str, List[Dict]] = {}
        for span_schema, span_list in (ann.get("spans", {}) or {}).items():
            if schema_name and span_schema != schema_name:
                continue
            for sp in span_list or []:
                field = sp.get("target_field") or text_key
                by_field.setdefault(field, []).append({
                    "start": sp.get("start", 0),
                    "end": sp.get("end", 0),
                    "label": sp.get("name") or sp.get("label", "ENTITY"),
                })
        if not by_field:
            by_field[text_key] = []
        for field, spans in by_field.items():
            text = context._span_anchor_text(item, field) if isinstance(item, dict) else None
            if text is None and isinstance(item, dict):
                for alt in (text_key, "text", "sentence", "content"):
                    if isinstance(item.get(alt), str):
                        text = item[alt]
                        break
            if not isinstance(text, str) or not text:
                warnings.append(f"No text found for {instance_id}"
                                + (f" field '{field}'" if field != text_key else ""))
                continue
            tokens = tokenize_text(text, method=tokenization)
            if not tokens:
                continue
            doc_id = instance_id if field == text_key else f"{instance_id}:{field}"
            tags = char_spans_to_bio_tags(tokens, spans, warnings=warnings, where=doc_id)
            yield doc_id, text, tokens, tags, group_sentences(tokens, text, tags)
