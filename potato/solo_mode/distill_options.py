"""
Live per-session override for the codebook -> prompt distill options.

``DistillConfig`` (potato/solo_mode/config.py) sets the YAML-configured
defaults. This module lets the "Prompt the LLM sees" panel change those
values for the running session without touching the config file — same
lightweight JSON-file persistence style as
``potato.solo_mode.prompt_manager``'s ``prompts.json``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_FILENAME = "distill_options.json"

_FIELDS = (
    "show_examples", "max_examples", "include_rationale",
    "summarize_above_tokens",
)


def _path(state_dir: str) -> str:
    return os.path.join(state_dir, _FILENAME)


def load_override(state_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    """The stored override dict, or None if there isn't one / it can't be
    read. Best-effort: a bad or missing file must never break rendering."""
    if not state_dir:
        return None
    try:
        with open(_path(state_dir)) as f:
            data = json.load(f)
        return {k: data[k] for k in _FIELDS if k in data}
    except FileNotFoundError:
        return None
    except Exception:
        logger.debug("could not read distill options override",
                     exc_info=True)
        return None


def save_override(state_dir: str, options: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a (partial) override, merged on top of any existing one.
    Returns the resulting merged dict."""
    os.makedirs(state_dir, exist_ok=True)
    merged = load_override(state_dir) or {}
    merged.update({k: options[k] for k in _FIELDS if k in options})
    tmp = _path(state_dir) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(merged, f, indent=2)
    os.replace(tmp, _path(state_dir))
    return merged


def clear_override(state_dir: str) -> None:
    try:
        os.remove(_path(state_dir))
    except FileNotFoundError:
        pass


def effective_options(solo_config: Any) -> Dict[str, Any]:
    """DistillConfig defaults merged with any live override for this
    project's state_dir."""
    distill = getattr(solo_config, "distill", None)
    base = {
        "show_examples": getattr(distill, "show_examples", True),
        "max_examples": getattr(distill, "max_examples", 5),
        "include_rationale": getattr(distill, "include_rationale", True),
        "summarize_above_tokens":
            getattr(distill, "summarize_above_tokens", 400),
    }
    state_dir = getattr(solo_config, "state_dir", None)
    override = load_override(state_dir)
    if override:
        base.update(override)
    return base
