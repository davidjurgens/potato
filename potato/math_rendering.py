"""
Math rendering (KaTeX) for item text, display fields and trace steps.

Opt-in through a top-level ``math`` block:

.. code-block:: yaml

    math:
      enabled: true
      delimiters: ["$$", "$", "\\\\(", "\\\\["]   # the default
      fields: [problem, solution]               # instance_display keys; default: all
      macros:
        "\\\\R": "\\\\mathbb{R}"

Rendering happens in the browser, after the server has sanitized the item
HTML, by ``static/potato-math.js``. KaTeX runs with ``trust: false`` (so
``\\href``, ``\\url``, ``\\includegraphics`` and the ``\\html*`` commands
produce no link, image or attribute), ``strict`` reporting, and
``throwOnError`` on, so a parse error shows the source text rather than
partial output. KaTeX writes its output with DOM calls and escapes text, so a
string such as ``$<img onerror=...>$`` renders as characters.

Span annotation is unaffected because span targets are never rendered: a
field with ``span_target: true`` and, in the legacy single-text layout, the
item text of a project that has a text-selection scheme keep showing the
LaTeX source. Span offsets therefore count the source characters
(``$x^2$`` is five code points), the same as they do with math rendering off.
:func:`math_span_conflicts` names the fields this applies to, and the config
loader logs it as a warning.

This module imports nothing heavy; boot reads it for validation only.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Delimiter name -> what the browser scanner looks for. Order in the client
#: config is longest-first so ``$$`` is not read as two empty ``$`` spans.
DELIMITERS: Dict[str, Dict[str, Any]] = {
    "$$": {"left": "$$", "right": "$$", "display": True},
    "\\[": {"left": "\\[", "right": "\\]", "display": True},
    "\\(": {"left": "\\(", "right": "\\)", "display": False},
    "$": {"left": "$", "right": "$", "display": False},
}
DEFAULT_DELIMITERS = ["$$", "$", "\\(", "\\["]

#: Scheme types that select or read characters of the legacy item text
#: (``#text-content``). With any of these present, the item text is left as
#: source so their offsets and their ``textContent`` reads stay correct.
TEXT_SELECTION_TYPES = frozenset({
    "span", "span_link", "coreference", "error_span", "event_annotation",
    "extractive_qa", "text_edit",
})

_MACRO_NAME = re.compile(r"^\\[A-Za-z]+$")
_KNOWN_KEYS = {"enabled", "delimiters", "fields", "macros"}
#: Bound on macro count and length: KaTeX expands macros itself (with its own
#: maxExpand limit), this only keeps a config from shipping a novel per page.
_MAX_MACROS = 200
_MAX_MACRO_LEN = 2000


class MathConfigError(ValueError):
    """A bad ``math`` block. Re-raised as ConfigValidationError by the loader."""


def _block(config_data: Optional[dict]) -> Optional[dict]:
    block = (config_data or {}).get("math")
    return block if isinstance(block, dict) else None


def math_enabled(config_data: Optional[dict]) -> bool:
    block = _block(config_data)
    return bool(block and block.get("enabled") is True)


def _display_fields(config_data: dict) -> List[dict]:
    display = config_data.get("instance_display")
    if not isinstance(display, dict):
        return []
    return [f for f in (display.get("fields") or []) if isinstance(f, dict)]


def validate_math_config(config_data: Optional[dict]) -> List[str]:
    """Check the ``math`` block. Raises :class:`MathConfigError` on a bad
    value; returns (and logs) the warnings about fields left as source."""
    if not config_data or "math" not in config_data:
        return []
    block = config_data.get("math")
    if not isinstance(block, dict):
        raise MathConfigError("math must be a mapping, e.g. math: {enabled: true}")

    errors: List[str] = []
    unknown = sorted(set(block) - _KNOWN_KEYS)
    if unknown:
        errors.append(f"math has unknown key(s): {', '.join(unknown)} "
                      f"(known: {', '.join(sorted(_KNOWN_KEYS))})")

    if "enabled" in block and not isinstance(block["enabled"], bool):
        errors.append("math.enabled must be true or false")

    if "delimiters" in block:
        delims = block["delimiters"]
        if not isinstance(delims, list) or not delims:
            errors.append("math.delimiters must be a non-empty list drawn from: "
                          + ", ".join(DEFAULT_DELIMITERS))
        else:
            bad = [d for d in delims if d not in DELIMITERS]
            if bad:
                errors.append(f"math.delimiters has unsupported value(s) {bad!r}; "
                              "use any of: " + ", ".join(DEFAULT_DELIMITERS))
            if len(set(map(str, delims))) != len(delims):
                errors.append("math.delimiters lists a delimiter twice")

    if "fields" in block:
        fields = block["fields"]
        if not isinstance(fields, list) or not all(isinstance(f, str) and f for f in fields):
            errors.append("math.fields must be a list of instance_display field keys")
        else:
            display_fields = _display_fields(config_data)
            if not display_fields:
                errors.append("math.fields names instance_display fields, but the "
                              "config has no instance_display.fields; remove "
                              "math.fields to render the item text")
            else:
                keys = {str(f.get("key")) for f in display_fields}
                missing = [f for f in fields if f not in keys]
                if missing:
                    errors.append(f"math.fields names {missing!r}, which are not "
                                  f"instance_display field keys ({', '.join(sorted(keys))})")

    if "macros" in block:
        macros = block["macros"]
        if not isinstance(macros, dict):
            errors.append("math.macros must be a mapping such as {'\\\\R': '\\\\mathbb{R}'}")
        else:
            if len(macros) > _MAX_MACROS:
                errors.append(f"math.macros has {len(macros)} entries; the limit is {_MAX_MACROS}")
            for name, body in macros.items():
                if not isinstance(name, str) or not _MACRO_NAME.match(name):
                    errors.append(f"math.macros key {name!r} must be a backslash "
                                  "followed by letters, e.g. \\R")
                if not isinstance(body, str) or len(body) > _MAX_MACRO_LEN:
                    errors.append(f"math.macros[{name!r}] must be a string of at "
                                  f"most {_MAX_MACRO_LEN} characters")

    if errors:
        raise MathConfigError("Invalid math configuration:\n  - " + "\n  - ".join(errors))

    warnings = math_span_conflicts(config_data) if math_enabled(config_data) else []
    for message in warnings:
        logger.warning(message)
    return warnings


def math_span_conflicts(config_data: dict) -> List[str]:
    """Where math is NOT rendered because annotators select text there."""
    out: List[str] = []
    display_fields = _display_fields(config_data)
    if display_fields:
        chosen = (_block(config_data) or {}).get("fields")
        for f in display_fields:
            if not f.get("span_target"):
                continue
            key = str(f.get("key"))
            if chosen is None or key in chosen:
                out.append(
                    f"math: instance_display field '{key}' is a span target, so its "
                    "math is shown as LaTeX source. Span offsets count the source "
                    "characters. Add a second, non-target field with the same "
                    "data to show it rendered.")
        return out
    types = sorted({s.get("annotation_type") for s in (config_data.get("annotation_schemes") or [])
                    if isinstance(s, dict) and s.get("annotation_type") in TEXT_SELECTION_TYPES})
    if types:
        out.append(
            f"math: the item text is not rendered because the project has a "
            f"text-selection scheme ({', '.join(types)}); span offsets count the "
            "LaTeX source characters. Use instance_display with a separate "
            "non-target field to show the rendered math beside it.")
    return out


def get_math_client_config(config_data: Optional[dict]) -> Optional[Dict[str, Any]]:
    """What ``potato-math.js`` reads, or None when math rendering is off."""
    if not math_enabled(config_data):
        return None
    block = _block(config_data) or {}
    names = block.get("delimiters") or DEFAULT_DELIMITERS
    order = list(DELIMITERS)  # longest-first
    delimiters = [dict(DELIMITERS[n]) for n in sorted(
        (n for n in names if n in DELIMITERS), key=order.index)]
    has_display = bool(_display_fields(config_data))
    instance_text = not has_display and not any(
        isinstance(s, dict) and s.get("annotation_type") in TEXT_SELECTION_TYPES
        for s in (config_data.get("annotation_schemes") or []))
    fields = block.get("fields")
    return {
        "delimiters": delimiters,
        "fields": list(fields) if isinstance(fields, list) else None,
        "macros": dict(block.get("macros") or {}),
        "instance_text": instance_text,
    }


def register_math_context(app) -> None:
    """Expose ``math_client_config`` to every template render.

    A context processor rather than a variable passed by each render path:
    annotation pages and phase pages (training, surveys) are built by two
    different functions, and a value wired into one of them only works on
    half the workflow.
    """
    @app.context_processor
    def _inject_math_client_config():
        try:
            from potato.server_utils.config_module import config
            return {"math_client_config": get_math_client_config(config)}
        except Exception:  # never the reason a page fails to render
            logger.exception("math: could not build the client config")
            return {"math_client_config": None}
