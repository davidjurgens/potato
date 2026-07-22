"""
Length-k summarization for over-long codebook prose fields.

The codebook's internal representation (the ``codes`` table) always keeps
the full text an author wrote — this module only shortens what gets
*rendered* into the prompt when a field exceeds the configured token
threshold (``DistillConfig.summarize_above_tokens``). Best-effort: on any
failure the caller keeps the original (full) text, so a broken summarizer
never blocks labeling.

Deliberately endpoint-injected rather than importing solo_mode: this
package (``potato.codebook``) is universal (standard annotation, solo
mode, QDA), so it never assumes solo_mode's model configuration. Callers
(e.g. ``potato.solo_mode.llm_labeler``) build the endpoint themselves,
the same way ``potato.solo_mode.guideline_updater`` does.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Callable, Optional

from potato.codebook import summary_cache

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """Compress the following annotation-codebook instruction \
to under {target_tokens} words while preserving every distinction it makes \
(what to include, what to exclude, edge cases). Do not add new claims.

Instruction:
---
{text}
---

Respond with JSON: {{"summary": "<the compressed instruction>"}}
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_summary(response: Any) -> Optional[str]:
    if isinstance(response, dict):
        return response.get("summary")
    if hasattr(response, "model_dump"):
        return response.model_dump().get("summary")
    content = str(response).strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if match:
        content = match.group(1).strip()
    try:
        return json.loads(content).get("summary")
    except (json.JSONDecodeError, AttributeError):
        return None


def make_summarizer(
    task_dir: str, endpoint: Any, target_tokens: int = 150,
) -> Callable[[Optional[str], str, str], str]:
    """Return a ``(code_id, field, text) -> str`` callback for
    ``render_from_codebook(..., summarize=...)``. Cached by content hash
    so an unchanged field is only summarized once.
    """

    def summarize(code_id: Optional[str], field: str, text: str) -> str:
        if not code_id:
            return text
        source_hash = _hash(text)
        cached = summary_cache.get_cached(task_dir, code_id, field, source_hash)
        if cached:
            return cached
        try:
            prompt = _PROMPT_TEMPLATE.format(
                target_tokens=target_tokens, text=text)
            response = endpoint.query(prompt)
            summary = _parse_summary(response)
            if not summary:
                return text
            summary_cache.set_cached(
                task_dir, code_id, field, source_hash, summary)
            return summary
        except Exception:
            logger.warning(
                "codebook field summarization failed for %s/%s; using "
                "full text", code_id, field, exc_info=True)
            return text

    return summarize
