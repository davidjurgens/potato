"""
Depth Map Display

Shows a depth map as a colourised image over an optional RGB frame, with the
controls the format actually needs: a near/far window, a colormap, an overlay
opacity, and a readout of the depth **in metres** under the cursor.

## Why it is not the image display with a different URL

An image display would render a 16-bit depth PNG as a black rectangle, and if
it did not, the annotator would still be looking at colours with no way to know
what distance any of them means. The three things this adds are the three
things that make depth legible:

- **A window.** The interesting range is almost never the full range.
- **A colormap with a distinct invalid colour.** Zero means "no return", and
  painting it as near depth draws a bright wall across every hole in the
  sensor's coverage.
- **A metre readout.** A colourmapped PNG cannot be inverted back to metres at
  8 bits, so the raw floats are fetched separately and indexed by cursor
  position. Without it the colours are decorative.

The heavy lifting is in :mod:`potato.media.depth`; this class renders the shell
and `depth-viewer.js` wires the controls.
"""

import html
import json
from typing import Any, Dict, List

from .base import BaseDisplay, css_length


class DepthDisplay(BaseDisplay):
    """Display type for single-channel depth maps."""

    name = "depth_map"
    required_fields = ["key"]
    optional_fields = {
        "depth_scale": None,
        "colormap": "turbo",
        "invert": False,
        "rgb_field": None,
        "overlay_opacity": 0.75,
        "max_height": None,
        "show_controls": True,
    }
    description = "Depth map with windowing, colormap and a metre readout"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return ('<div class="depth-placeholder">No depth map for this '
                    'item.</div>')

        options = self.get_display_options(field_config)
        field_key = field_config.get("key", "depth")
        # The element id has to survive a field key with punctuation in it, and
        # two depth fields on one page must not collide.
        safe_id = "depth-" + "".join(
            c if c.isalnum() or c in "-_" else "-" for c in str(field_key))

        config = {
            "path": str(data),
            "fieldKey": str(field_key),
            "depthScale": options.get("depth_scale"),
            "colormap": options.get("colormap") or "turbo",
            "invert": bool(options.get("invert")),
            "rgbField": options.get("rgb_field") or None,
            "overlayOpacity": float(options.get("overlay_opacity", 0.75)),
            "showControls": options.get("show_controls", True) is not False,
        }

        style = ""
        if options.get("max_height"):
            style = (' style="max-height: '
                     f'{html.escape(css_length(options["max_height"]))}"')

        return f"""
        <div class="depth-display" id="{html.escape(safe_id, quote=True)}"
             data-field-key="{html.escape(str(field_key), quote=True)}"
             data-depth-config='{html.escape(json.dumps(config), quote=True)}'>
            <div class="depth-stage"{style}>
                <img class="depth-rgb" alt="" hidden>
                <img class="depth-overlay"
                     alt="Depth map, colourised. The readout below reports the
                          distance under the cursor.">
                <div class="depth-loading">Loading depth…</div>
            </div>
            <!-- NOT a live region. It was one, and it updated on every
                 mousemove — several announcements a second, which is a screen
                 reader that never stops talking. It is also a pointer-only
                 affordance: nobody samples depths by moving a mouse they are
                 not using. The information a non-pointer user needs is the
                 map's range and how much of it has no return, and that goes to
                 .depth-announce below, once, when the map loads. -->
            <p class="depth-readout">
                <span class="depth-readout-value">—</span>
            </p>
            <p class="depth-announce" role="status" aria-live="polite"></p>
            {self._controls(safe_id, config) if config["showControls"] else ""}
        </div>
        """

    def _controls(self, safe_id, config):
        colormaps = ["turbo", "viridis", "magma", "gray"]
        chosen = config["colormap"]
        options = "".join(
            f'<option value="{c}"{" selected" if c == chosen else ""}>'
            f'{c}</option>' for c in colormaps)
        return f"""
            <div class="depth-controls" role="group"
                 aria-label="Depth rendering controls">
                <label class="depth-control">
                    <span>Near (m)</span>
                    <input type="number" class="depth-near" step="0.1"
                           id="{safe_id}-near">
                </label>
                <label class="depth-control">
                    <span>Far (m)</span>
                    <input type="number" class="depth-far" step="0.1"
                           id="{safe_id}-far">
                </label>
                <label class="depth-control">
                    <span>Colours</span>
                    <select class="depth-colormap" id="{safe_id}-cmap">
                        {options}
                    </select>
                </label>
                <label class="depth-control">
                    <span>Overlay</span>
                    <input type="range" class="depth-opacity" min="0" max="100"
                           value="{int(config['overlayOpacity'] * 100)}"
                           id="{safe_id}-opacity">
                </label>
                <button type="button" class="depth-reset btn btn-sm">
                    Reset window
                </button>
            </div>
        """

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        classes.append("depth-display-container")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any],
                            data: Any) -> Dict[str, str]:
        attrs = super().get_data_attributes(field_config, data)
        if data:
            attrs["depth-path"] = str(data)
        return attrs
