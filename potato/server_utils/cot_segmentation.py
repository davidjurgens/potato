"""
Chain-of-thought (CoT) step segmentation.

Splits a single long reasoning string into a list of labelable *steps* so a
long CoT can be annotated with per-step process rewards (PRM). The step list
this produces is consumed by the ``cot_trace`` display and the
``process_reward`` schema (both point their ``steps_key`` at the segmentation
``target_key``).

Segmentation runs once, server-side, when items are loaded (see
``apply_cot_segmentation``) and the result is written back onto the item so the
display and schema read an identical, cached list.

The strategy is chosen in YAML via the ``cot_segmentation`` block::

    cot_segmentation:
      source_key: reasoning      # item field holding the long CoT string
      strategy: auto             # blank_line | numbered | markers | sentence | llm | auto
      target_key: cot_steps      # item field the step list is written to
      min_step_chars: 40         # merge steps shorter than this into the previous
      max_steps: 200             # hard cap (protects the UI from pathological input)
      markers: ["<step>", "\\n---\\n"]   # markers strategy only
      sentences_per_step: 1      # sentence strategy only

All strategies are pure-Python with no heavy dependencies except ``llm``,
which delegates boundary detection to a configured AI/judge endpoint.

Each returned step is a dict::

    {"index": i, "text": "...", "type": "thought|action|observation|...",
     "char_start": s, "char_end": e}

``type`` is inferred with the shared trace-normalization heuristics so a
segmented CoT types its steps the same way ``agent_trace``/``eval_trace`` do.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .displays._trace_normalize import infer_type_from_text

logger = logging.getLogger(__name__)

VALID_STRATEGIES = ("blank_line", "numbered", "markers", "sentence", "llm", "auto")

# A numbered/step-list boundary at the start of a line: "1. ", "2) ", "Step 3:",
# "3 - ". Matched multiline so each list item begins a new step.
_NUMBERED_RE = re.compile(
    r"(?m)^[ \t]*(?:step[ \t]+\d+[.):]?|\d+[.)]|\d+[ \t]*[-–])[ \t]+",
    re.IGNORECASE,
)

# Blank-line paragraph separator.
_BLANK_RE = re.compile(r"\n[ \t]*\n")

# Sentence end followed by whitespace and a capital / digit (naive but
# dependency-free; grouped by ``sentences_per_step`` and merged by
# ``min_step_chars`` so occasional over-splitting is harmless).
_SENTENCE_RE = re.compile(r"(?<=[.!?])[ \t]+(?=[A-Z0-9\"'(])")

# Default markers for the ``markers`` strategy. ``<think>``/``</think>`` and
# ``<step>``/``</step>`` tag pairs are common in reasoning-model output.
DEFAULT_MARKERS = ["<step>", "</step>", "<think>", "</think>", "\n---\n", "\n***\n"]


def _segments_from_separators(
    text: str, sep_spans: List[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Return ``(start, end)`` spans of the text *between* separator spans.

    ``sep_spans`` are ``(start, end)`` ranges to remove. Empty/whitespace-only
    segments are dropped. Offsets are into the original ``text``.
    """
    spans: List[Tuple[int, int]] = []
    cursor = 0
    for s, e in sorted(sep_spans):
        if s > cursor:
            spans.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < len(text):
        spans.append((cursor, len(text)))
    # Trim whitespace at the edges of each span, drop empties.
    trimmed: List[Tuple[int, int]] = []
    for s, e in spans:
        chunk = text[s:e]
        lead = len(chunk) - len(chunk.lstrip())
        trail = len(chunk) - len(chunk.rstrip())
        ns, ne = s + lead, e - trail
        if ne > ns:
            trimmed.append((ns, ne))
    return trimmed


def _boundaries_to_spans(text: str, starts: List[int]) -> List[Tuple[int, int]]:
    """Given boundary *start* offsets that each begin a new step, return the
    ``(start, end)`` span of every step (a preamble before the first boundary
    becomes its own step)."""
    cuts = sorted(set([0] + [s for s in starts if 0 < s < len(text)] + [len(text)]))
    spans: List[Tuple[int, int]] = []
    for i in range(len(cuts) - 1):
        s, e = cuts[i], cuts[i + 1]
        chunk = text[s:e]
        lead = len(chunk) - len(chunk.lstrip())
        trail = len(chunk) - len(chunk.rstrip())
        ns, ne = s + lead, e - trail
        if ne > ns:
            spans.append((ns, ne))
    return spans


def _split_blank_line(text: str) -> List[Tuple[int, int]]:
    return _segments_from_separators(text, [m.span() for m in _BLANK_RE.finditer(text)])


def _split_numbered(text: str) -> List[Tuple[int, int]]:
    return _boundaries_to_spans(text, [m.start() for m in _NUMBERED_RE.finditer(text)])


def _split_markers(text: str, markers: List[str]) -> List[Tuple[int, int]]:
    sep_spans: List[Tuple[int, int]] = []
    for marker in markers:
        if not marker:
            continue
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx == -1:
                break
            sep_spans.append((idx, idx + len(marker)))
            start = idx + len(marker)
    return _segments_from_separators(text, sep_spans)


def _split_sentence(text: str, sentences_per_step: int = 1) -> List[Tuple[int, int]]:
    sent_spans = _segments_from_separators(
        text, [m.span() for m in _SENTENCE_RE.finditer(text)]
    )
    if sentences_per_step <= 1:
        return sent_spans
    # Group consecutive sentences into one step.
    grouped: List[Tuple[int, int]] = []
    for i in range(0, len(sent_spans), sentences_per_step):
        chunk = sent_spans[i : i + sentences_per_step]
        grouped.append((chunk[0][0], chunk[-1][1]))
    return grouped


def _merge_short(
    text: str, spans: List[Tuple[int, int]], min_chars: int
) -> List[Tuple[int, int]]:
    """Merge a step shorter than ``min_chars`` into the previous step (or the
    next one when it is the first). Keeps offsets contiguous over the merge."""
    if min_chars <= 0 or len(spans) <= 1:
        return spans
    merged: List[Tuple[int, int]] = []
    for span in spans:
        s, e = span
        if (e - s) < min_chars and merged:
            ps, _ = merged[-1]
            merged[-1] = (ps, e)
        else:
            merged.append(span)
    # If the very first step was short, it stayed as its own head; fold it
    # forward so no sub-threshold fragment survives at the top.
    if len(merged) > 1 and (merged[0][1] - merged[0][0]) < min_chars:
        s0, _ = merged[0]
        _, e1 = merged[1]
        merged = [(s0, e1)] + merged[2:]
    return merged


def _segment_llm(text: str, opts: Dict[str, Any], endpoint: Any) -> Optional[List[Tuple[int, int]]]:
    """Ask the configured AI/judge endpoint to return step boundary offsets.

    Returns ``None`` (so callers fall back to a heuristic) when no endpoint is
    available or the model output cannot be parsed. Reuses the endpoint's
    robust ``parseStringToJson`` when present (handles ```` ```json ```` fences
    and truncated output).
    """
    if endpoint is None:
        logger.warning("cot_segmentation strategy 'llm' requested but no endpoint provided")
        return None

    max_chars = int(opts.get("llm_max_chars", 12000))
    snippet = text[:max_chars]
    prompt = (
        "Segment the following chain-of-thought reasoning into its distinct "
        "logical steps. Return ONLY JSON of the form "
        '{\"steps\": [\"first step text\", \"second step text\", ...]} where each '
        "string is a verbatim, contiguous span of the original text, in order, "
        "with no text omitted or added.\n\n"
        "REASONING:\n" + snippet
    )
    try:
        # max_tokens must be generous: the model echoes the reasoning back.
        raw = endpoint.query(prompt, None) if _endpoint_takes_output_format(endpoint) else endpoint.query(prompt)
    except Exception as exc:  # noqa: BLE001 - fall back to heuristics on any endpoint error
        logger.warning("cot_segmentation llm query failed: %s", exc)
        return None

    parsed = _parse_endpoint_json(endpoint, raw)
    if not isinstance(parsed, dict):
        return None
    step_texts = parsed.get("steps")
    if not isinstance(step_texts, list) or not step_texts:
        return None

    # Map each returned span back to offsets in the original text with a moving
    # cursor (mirrors judge._locate_spans), so we keep verbatim offsets and
    # skip anything the model paraphrased.
    spans: List[Tuple[int, int]] = []
    cursor = 0
    for st in step_texts:
        if not isinstance(st, str) or not st.strip():
            continue
        idx = text.find(st.strip(), cursor)
        if idx == -1:
            idx = text.find(st.strip()[:40], cursor) if len(st.strip()) >= 40 else -1
        if idx == -1:
            continue
        end = idx + len(st.strip())
        spans.append((idx, end))
        cursor = end
    return spans or None


def _endpoint_takes_output_format(endpoint: Any) -> bool:
    """Anthropic's ``query`` has no ``output_format`` param; others do."""
    try:
        import inspect

        return "output_format" in inspect.signature(endpoint.query).parameters
    except (ValueError, TypeError):
        return True


def _parse_endpoint_json(endpoint: Any, raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parser = getattr(endpoint, "parseStringToJson", None)
        if callable(parser):
            try:
                return parser(raw)
            except Exception:  # noqa: BLE001
                pass
        try:
            import json

            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
    return None


def _auto(text: str, opts: Dict[str, Any], endpoint: Any) -> List[Tuple[int, int]]:
    """Pick the first heuristic that yields a real segmentation (>= 2 steps)."""
    markers = opts.get("markers", DEFAULT_MARKERS)
    for spans in (
        _split_markers(text, markers),
        _split_numbered(text),
        _split_blank_line(text),
        _split_sentence(text, int(opts.get("sentences_per_step", 1))),
    ):
        if len(spans) >= 2:
            return spans
    # Nothing split cleanly: single step covering the whole reasoning.
    stripped = text.strip()
    if not stripped:
        return []
    start = text.find(stripped[0]) if stripped else 0
    return [(start, start + len(stripped))]


def segment_cot(
    text: str,
    strategy: str = "auto",
    opts: Optional[Dict[str, Any]] = None,
    endpoint: Any = None,
) -> List[Dict[str, Any]]:
    """Segment a long CoT string into typed steps.

    Args:
        text: the raw reasoning string.
        strategy: one of :data:`VALID_STRATEGIES`.
        opts: strategy options (``min_step_chars``, ``max_steps``, ``markers``,
            ``sentences_per_step``, ...).
        endpoint: an AI/judge endpoint used only by the ``llm`` strategy.

    Returns:
        A list of step dicts (see the module docstring). Never raises on bad
        input — returns ``[]`` for empty/non-string text.
    """
    opts = dict(opts or {})
    if not isinstance(text, str) or not text.strip():
        return []
    if strategy not in VALID_STRATEGIES:
        logger.warning("Unknown cot_segmentation strategy %r; falling back to 'auto'", strategy)
        strategy = "auto"

    if strategy == "blank_line":
        spans = _split_blank_line(text)
    elif strategy == "numbered":
        spans = _split_numbered(text)
    elif strategy == "markers":
        spans = _split_markers(text, opts.get("markers", DEFAULT_MARKERS))
    elif strategy == "sentence":
        spans = _split_sentence(text, int(opts.get("sentences_per_step", 1)))
    elif strategy == "llm":
        spans = _segment_llm(text, opts, endpoint)
        if not spans:  # endpoint missing / unparseable -> deterministic fallback
            spans = _auto(text, opts, endpoint)
    else:  # auto
        spans = _auto(text, opts, endpoint)

    if not spans:
        stripped = text.strip()
        spans = [(text.find(stripped[0]) if stripped else 0, len(text.rstrip()))]

    spans = _merge_short(text, spans, int(opts.get("min_step_chars", 0)))

    max_steps = int(opts.get("max_steps", 200))
    if max_steps > 0 and len(spans) > max_steps:
        logger.warning(
            "cot_segmentation produced %d steps; capping to max_steps=%d",
            len(spans),
            max_steps,
        )
        spans = spans[:max_steps]

    steps: List[Dict[str, Any]] = []
    for i, (s, e) in enumerate(spans):
        chunk = text[s:e]
        steps.append(
            {
                "index": i,
                "text": chunk,
                "type": infer_type_from_text(chunk),
                "char_start": s,
                "char_end": e,
            }
        )
    return steps


def apply_cot_segmentation(
    item: Dict[str, Any],
    seg_config: Dict[str, Any],
    endpoint: Any = None,
) -> Dict[str, Any]:
    """Segment ``item[source_key]`` and write the step list to ``item[target_key]``.

    Idempotent and non-destructive: if ``target_key`` is already populated with
    a non-empty list (e.g. the data already ships pre-segmented steps, or a
    prior pass ran), the item is returned unchanged. Mutates and returns
    ``item`` for convenience.
    """
    if not isinstance(item, dict) or not isinstance(seg_config, dict):
        return item
    source_key = seg_config.get("source_key")
    target_key = seg_config.get("target_key", "cot_steps")
    if not source_key:
        return item

    existing = item.get(target_key)
    if isinstance(existing, list) and existing:
        return item

    raw = item.get(source_key)
    if not isinstance(raw, str) or not raw.strip():
        return item

    opts = {
        k: seg_config[k]
        for k in ("min_step_chars", "max_steps", "markers", "sentences_per_step", "llm_max_chars")
        if k in seg_config
    }
    steps = segment_cot(
        raw,
        strategy=seg_config.get("strategy", "auto"),
        opts=opts,
        endpoint=endpoint,
    )
    item[target_key] = steps
    return item
