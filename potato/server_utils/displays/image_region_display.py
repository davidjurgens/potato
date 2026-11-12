"""
Image Region Display

Shows one rectangle of a larger image: a text line on a manuscript page, a
detected word, a figure on a scanned page. The full image is served once and
cropped in the browser with CSS, so a page with forty lines is one download
whichever line is on screen.

The field value is an object::

    {"image": "/media/page-001.png",   # the whole image
     "width": 2480, "height": 3508,    # its size in pixels
     "region": [x, y, w, h],           # the rectangle to show, in pixels
     "polygon": [[x, y], ...]}         # optional outline drawn over the crop

``potato import -f page_xml`` writes this shape for every text line. The crop
keeps the region's aspect ratio and is padded by ``padding`` pixels of the
image on each side, so the strokes at the edge of a line are not cut off.
Without ``width`` and ``height`` the crop cannot be computed in CSS, and the
whole image is shown instead with a note saying why.
"""

import html
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseDisplay


_CSS = """
.image-region { --ir-outline: var(--primary, #2563eb); }
.image-region-crop { position: relative; overflow: hidden; width: 100%;
  background: var(--muted, #f4f4f5); border: 1px solid var(--border, #e4e4e7);
  border-radius: 6px; }
.image-region-crop img { position: absolute; max-width: none; height: auto;
  user-select: none; -webkit-user-drag: none; }
.image-region-crop svg, .image-region-page svg { position: absolute; inset: 0;
  width: 100%; height: 100%; pointer-events: none; }
.image-region svg polygon, .image-region svg rect { fill: none;
  stroke: var(--ir-outline); stroke-width: 2px; vector-effect: non-scaling-stroke; }
.image-region-page-toggle { margin-top: 0.5rem; }
.image-region-page-toggle summary { cursor: pointer; color: var(--muted-foreground, #52525b);
  font-size: 0.875rem; width: fit-content; border-radius: 4px; padding: 2px 4px; }
.image-region-page-toggle summary:focus-visible { outline: 2px solid var(--ring, #2563eb);
  outline-offset: 2px; }
.image-region-page { position: relative; margin-top: 0.5rem; max-width: 100%; }
.image-region-page img { display: block; width: 100%; height: auto; }
.image-region-note { color: var(--muted-foreground, #52525b); font-size: 0.875rem; }
"""


def _num(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _pct(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") + "%"


class ImageRegionDisplay(BaseDisplay):
    """Display type that crops one region out of an image."""

    name = "image_region"
    required_fields = ["key"]
    optional_fields = {
        "padding": 8,
        "outline": True,
        "show_page": True,
        "max_scale": 2.0,
        "alt_text": "",
    }
    description = "One rectangle of a larger image (a text line, a word, a figure), cropped in the browser"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        options = self.get_display_options(field_config)
        field_key = html.escape(str(field_config.get("key", "")), quote=True)
        if not data:
            return '<div class="image-region-note">No image for this item.</div>'
        if isinstance(data, str):
            data = {"image": data}
        if not isinstance(data, dict) or not data.get("image"):
            return '<div class="image-region-note">This item has no image to show.</div>'

        url = str(data["image"])
        if url.lower().startswith(("javascript:", "vbscript:")):
            return '<div class="image-region-note">Invalid image URL.</div>'
        src = html.escape(url, quote=True)
        alt = html.escape(str(options.get("alt_text") or data.get("alt") or "Image region"), quote=True)
        width, height = _num(data.get("width")), _num(data.get("height"))
        region = self._region(data)
        style = f"<style>{_CSS}</style>"

        if not (width and height and width > 0 and height > 0 and region):
            note = ("" if region is None else
                    '<div class="image-region-note">The image size is not recorded, so '
                    'the region cannot be cropped; showing the whole image.</div>')
            return (f'{style}<div class="image-region" data-field-key="{field_key}">'
                    f'{note}<div class="image-region-page"><img src="{src}" alt="{alt}"></div></div>')

        pad = max(0.0, _num(options.get("padding")) or 0.0)
        x, y, w, h = region
        cx = max(0.0, x - pad)
        cy = max(0.0, y - pad)
        cw = min(width, x + w + pad) - cx
        ch = min(height, y + h + pad) - cy
        if cw <= 0 or ch <= 0:
            return (f'{style}<div class="image-region-note">The region lies outside '
                    f'the image.</div>')
        max_scale = _num(options.get("max_scale")) or 2.0

        img_style = (f"width: {_pct(width / cw * 100)}; left: {_pct(-cx / cw * 100)}; "
                     f"top: {_pct(-cy / ch * 100)};")
        crop_style = (f"aspect-ratio: {cw:g} / {ch:g}; max-width: {cw * max_scale:g}px;")
        outline = ""
        if options.get("outline", True):
            shape = self._shape(data, region)
            outline = (f'<svg viewBox="{cx:g} {cy:g} {cw:g} {ch:g}" preserveAspectRatio="none" '
                       f'aria-hidden="true" focusable="false">{shape}</svg>')
        page = ""
        if options.get("show_page", True):
            page = (f'<details class="image-region-page-toggle"><summary>Show the whole image</summary>'
                    f'<div class="image-region-page"><img src="{src}" alt="" loading="lazy">'
                    f'<svg viewBox="0 0 {width:g} {height:g}" preserveAspectRatio="none" '
                    f'aria-hidden="true" focusable="false">'
                    f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"/></svg></div></details>')
        return (f'{style}<div class="image-region" data-field-key="{field_key}" '
                f'data-region="{x:g},{y:g},{w:g},{h:g}">'
                f'<div class="image-region-crop" role="img" aria-label="{alt}" style="{crop_style}">'
                f'<img src="{src}" alt="" draggable="false" style="{img_style}">{outline}</div>'
                f'{page}</div>')

    @staticmethod
    def _region(data: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
        region = data.get("region")
        if isinstance(region, dict):
            region = [region.get("x"), region.get("y"), region.get("width", region.get("w")),
                      region.get("height", region.get("h"))]
        if isinstance(region, (list, tuple)) and len(region) == 4:
            values = [_num(v) for v in region]
            if all(v is not None for v in values) and values[2] > 0 and values[3] > 0:
                return values[0], values[1], values[2], values[3]
        polygon = data.get("polygon")
        points = ImageRegionDisplay._points(polygon)
        if len(points) >= 2:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            if max(xs) > min(xs) and max(ys) > min(ys):
                return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        return None

    @staticmethod
    def _points(polygon: Any) -> List[Tuple[float, float]]:
        out = []
        for point in polygon or []:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                px, py = _num(point[0]), _num(point[1])
            elif isinstance(point, dict):
                px, py = _num(point.get("x")), _num(point.get("y"))
            else:
                continue
            if px is not None and py is not None:
                out.append((px, py))
        return out

    def _shape(self, data: Dict[str, Any], region: Tuple[float, float, float, float]) -> str:
        points = self._points(data.get("polygon"))
        if len(points) >= 3:
            pts = " ".join(f"{px:g},{py:g}" for px, py in points)
            return f'<polygon points="{pts}"/>'
        x, y, w, h = region
        return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"/>'
