"""Render instance text to a PNG so the page never carries the text itself.

Set ``text_as_image: true`` in the config and an annotator sees a picture of the
instance instead of the words. "Select all", "copy" and "view source" then yield
nothing to paste into a chatbot, because the text never reaches the browser. An
annotator can still retype the instance or run OCR on the picture, so this
raises the cost of the shortcut rather than removing it.

The server renders the PNG and inlines it as a ``data:`` URI. The markup is
built here from PIL output and a base64 payload, so no annotation content
reaches the attribute. The template marks it safe for that reason.

A span scheme cannot run beside this feature. Every span scheme anchors its
annotations to character offsets in the plain text, and the feature removes
that text. ``validate_text_as_image_config`` refuses the combination at
startup, because the failure is otherwise silent: the annotator sees a picture,
selects nothing, and the study collects empty spans. ``SPAN_SCHEME_TYPES``
below is the list it checks.

One cost remains, and no check can remove it: a screen reader gets nothing. The
alt text stays generic on purpose, because real alt text would put the words
back into the page.
"""

from __future__ import annotations

import base64
import html
import io
import logging
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Rendered at twice the requested size and displayed at half, so the text stays
#: sharp on a high-density screen.
_SCALE = 2

#: A light card holds the instance text, so the picture matches it.
_BACKGROUND = "#ffffff"
_FOREGROUND = "#111111"

DEFAULTS: Dict[str, int] = {"font_size": 18, "max_width": 900}

#: Schemes that anchor annotations to character offsets in the instance text.
#: The feature removes that text, so the two cannot work together.
SPAN_SCHEME_TYPES = frozenset({
    "span",
    "span_link",
    "error_span",
    "coreference",
    "event_annotation",
    "extractive_qa",
    "context_attribution",
    "multi_document_event",
})


def settings(config: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Return the resolved options, or None when the feature is off.

    Accepts ``text_as_image: true`` and the mapping form::

        text_as_image:
          enabled: true
          font_size: 20
          max_width: 800
    """
    raw = config.get("text_as_image")
    if raw is True:
        return dict(DEFAULTS)
    if not isinstance(raw, dict) or not raw.get("enabled", True):
        return None
    resolved = dict(DEFAULTS)
    for key in DEFAULTS:
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            resolved[key] = value
    return resolved


#: Displays that own the page themselves. The instance-text box is not what the
#: annotator reads on these, so the feature stays out of their way.
MEDIA_SCHEME_TYPES = frozenset({
    "video_annotation",
    "audio_annotation",
    "image_annotation",
})


def applies(config: Dict[str, Any],
            annotation_schemes: Any) -> Optional[Dict[str, int]]:
    """Return the options when the picture replaces the text here, else None.

    The shared template shows the instance text in its own box only when no
    media display and no ``instance_display`` block owns the page. On those
    projects the text box is a hidden fallback, not the thing the annotator
    reads, so a picture there would help nobody.
    """
    options = settings(config)
    if options is None or "instance_display" in config:
        return None
    for scheme in annotation_schemes or ():
        if not isinstance(scheme, dict):
            continue
        kind = scheme.get("annotation_type")
        if kind in MEDIA_SCHEME_TYPES:
            return None
        if kind == "tiered_annotation" and scheme.get("media_type") in {"video", "audio"}:
            return None
    return options


def span_schemes(annotation_schemes: Any) -> List[str]:
    """Configured scheme types that need the plain text in the DOM."""
    return sorted({
        scheme.get("annotation_type")
        for scheme in annotation_schemes or ()
        if isinstance(scheme, dict)
        and scheme.get("annotation_type") in SPAN_SCHEME_TYPES
    })


def schemes_reading_removed_fields(annotation_schemes: Any,
                                  text_key: str) -> List[str]:
    """Scheme names that point at a data field the feature removes.

    A scheme names the field it reads with an attribute of its own:
    ``source_field`` for text_edit, ``items_field`` for card_sort,
    ``profiles_field`` for conjoint, and about thirty more across the registry.
    Tracking that list would go stale on the next schema, so this checks the
    VALUES instead. Any ``*_field`` or ``*_key`` attribute whose value names a
    field ``without_text`` drops is a scheme that would read an absent field.
    """
    removed = removed_fields(text_key)
    conflicts = []
    for scheme in annotation_schemes or ():
        if not isinstance(scheme, dict):
            continue
        for attribute, value in scheme.items():
            if (isinstance(attribute, str)
                    and attribute.endswith(("_field", "_key"))
                    and isinstance(value, str)
                    and value in removed):
                label = scheme.get("name") or scheme.get("annotation_type") or "?"
                conflicts.append(f"{label} ({attribute}: {value})")
                break
    return sorted(conflicts)


def removed_fields(text_key: str) -> frozenset:
    """The item-record fields the feature blanks."""
    return frozenset({"displayed_text", "text", text_key})


def without_text(record: Any, text_key: str) -> Dict[str, Any]:
    """Copy ``record`` without the fields that carry the instance text.

    The page embeds the item record as JSON for dynamic schemas. That JSON
    would hand back every word the picture just hid.
    """
    if not isinstance(record, dict):
        return {}
    dropped = removed_fields(text_key)
    return {k: v for k, v in record.items() if k not in dropped}


def to_plain(markup: str) -> str:
    """Strip HTML from the displayed text but keep the paragraph breaks.

    ``instance_plain_text`` collapses every run of whitespace, newlines
    included, because span offsets need one flat string. A picture reads better
    with its paragraphs intact, so this keeps them.
    """
    if not markup:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", markup, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|div|li|tr|h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _wrap(text: str, font, width: int) -> List[str]:
    """Break text into lines that fit inside ``width`` pixels."""
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}" if current else word
            if font.getlength(candidate) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            # A single word can be wider than the image (a long URL, a hash).
            # Break it by character so no text is lost off the right edge.
            while font.getlength(word) > width:
                cut = 1
                while cut < len(word) and font.getlength(word[: cut + 1]) <= width:
                    cut += 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
    return lines or [""]


@lru_cache(maxsize=512)
def render_png(text: str, font_size: int, max_width: int) -> bytes:
    """Render ``text`` to PNG bytes. Cached, because a page reload repeats it."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=font_size * _SCALE)
    width = max_width * _SCALE
    padding = 12 * _SCALE
    line_height = int(font_size * _SCALE * 1.45)

    lines = _wrap(text, font, width - 2 * padding)
    height = padding * 2 + line_height * len(lines)

    image = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((padding, padding + index * line_height), line,
                  font=font, fill=_FOREGROUND)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def image_html(markup: str, options: Dict[str, int]) -> str:
    """Return the <img> that replaces the instance text, or "" if there is none."""
    text = to_plain(markup)
    if not text:
        return ""
    png = render_png(text, options["font_size"], options["max_width"])
    payload = base64.b64encode(png).decode("ascii")
    return (
        f'<img src="data:image/png;base64,{payload}" '
        f'alt="The text for this item, shown as an image" '
        f'style="max-width:100%;width:{options["max_width"]}px;'
        f'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;" '
        f'draggable="false" oncontextmenu="return false;">'
    )
