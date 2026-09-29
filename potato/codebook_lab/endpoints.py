"""
LLM endpoint construction and structured-response parsing for
codebook_lab, reusing the same AIEndpointFactory / ModelConfig machinery
Solo Mode uses so this package supports every endpoint type Potato
already supports (ollama, openai, anthropic, ...) for free.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def build_endpoint(model_config: Dict[str, Any]):
    """Create an AI endpoint from a plain dict shaped like a solo_mode
    ``labeling_models`` entry (endpoint_type, model, api_key, base_url,
    max_tokens, temperature, timeout). Returns None if it can't connect —
    callers should treat that as fatal for this run, not silently skip,
    since a scoring/generation run with no endpoint produces garbage."""
    from potato.solo_mode.config import _parse_model_config
    from potato.ai.ai_endpoint import AIEndpointFactory

    mc = _parse_model_config(model_config)
    endpoint_config = mc.to_endpoint_config()
    return AIEndpointFactory.create_endpoint(endpoint_config)


def query_json(
    endpoint: Any, prompt: str, schema: Type[BaseModel],
) -> Dict[str, Any]:
    """Query an endpoint with a pydantic output schema and return a plain
    dict, handling every response shape Potato's endpoints actually
    return in practice (a JSON string, a pydantic instance, or a dict
    that's already parsed) — mirrors
    potato.solo_mode.llm_labeler.LLMLabelingThread._label_instance's
    response handling so behavior matches production labeling exactly.
    Raises on unparseable output rather than silently returning {} —
    scoring needs to know a call actually failed, not treat it as a
    confident wrong answer.
    """
    response = endpoint.query(prompt, schema)

    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()

    content = str(response).strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if match:
        content = match.group(1).strip()
    return json.loads(content)
