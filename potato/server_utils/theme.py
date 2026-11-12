"""Light and dark themes for the annotator pages.

``ui.theme`` chooses how a study's pages pick one:

* ``auto`` (the default): follow the browser's ``prefers-color-scheme``, and
  let the annotator override it with the header toggle, remembered per
  browser;
* ``light`` or ``dark``: every annotator gets that theme and the toggle is
  hidden, for a study whose conditions must be the same for everyone.

The page sets ``data-theme`` on ``<html>`` in ``templates/_theme_head.html``
before any stylesheet paints; ``styles.css`` holds the dark token values.
Admin pages are light whatever this says.
"""

from __future__ import annotations

import colorsys
import re
from typing import Any, Mapping

THEMES = ("auto", "light", "dark")
DEFAULT_THEME = "auto"


def resolve_ui_theme(config: Mapping[str, Any]) -> str:
    """The configured theme mode; ``auto`` when unset or unreadable."""
    ui = config.get("ui") if isinstance(config, Mapping) else None
    value = ui.get("theme") if isinstance(ui, Mapping) else None
    if isinstance(value, str) and value.strip().lower() in THEMES:
        return value.strip().lower()
    return DEFAULT_THEME


def validate_ui_theme(config: Mapping[str, Any]) -> None:
    """Refuse a ``ui.theme`` that is not one of THEMES."""
    from potato.server_utils.config_module import ConfigValidationError

    ui = config.get("ui")
    if not isinstance(ui, Mapping) or "theme" not in ui:
        return
    value = ui["theme"]
    if not isinstance(value, str) or value.strip().lower() not in THEMES:
        raise ConfigValidationError(
            f"ui.theme must be one of {', '.join(THEMES)}, not {value!r}")


_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def themed_background(colour: str) -> str:
    """A background colour that follows the theme.

    For a light hex colour (a config-set step or panel tint such as
    ``#e8f5e9``) this returns ``light-dark(<colour>, <dark twin>)``: the
    colour itself in the light theme, and a dark surface of the same hue in
    the dark one, so the text on it (which follows the theme) stays readable.
    Anything else -- a mid-tone accent, a dark colour, a var() or gradient --
    is returned unchanged. The static stylesheets got their twins the same
    way.
    """
    if not isinstance(colour, str) or not _HEX.fullmatch(colour.strip()):
        return colour
    value = colour.strip()[1:]
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    if 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b) <= 0.5:
        return colour
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    target = max(0.09, min(0.2, 0.10 + (1 - lightness) * 0.6))
    dr, dg, db = colorsys.hls_to_rgb(hue, target, min(1.0, saturation * 0.55))
    twin = "#" + "".join(f"{round(c * 255):02x}" for c in (dr, dg, db))
    return f"light-dark({colour.strip()}, {twin})"
