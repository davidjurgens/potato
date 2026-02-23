"""
Gallery Display Type

Scrollable image gallery for displaying screenshot sequences, step-by-step
visual traces, or any ordered collection of images with optional captions.
"""

import html
from typing import Dict, Any, List

from .base import BaseDisplay


class GalleryDisplay(BaseDisplay):
    """
    Display type for ordered image galleries with captions.

    Supports data as:
        - List of image URLs/paths (strings)
        - List of dicts with url/caption keys
    """

    name = "gallery"
    required_fields = ["key"]
    optional_fields = {
        "layout": "horizontal",  # horizontal, vertical, grid
        "thumbnail_size": 300,
        "show_captions": True,
        "caption_key": "caption",
        "url_key": "url",
        "zoomable": True,
        "max_height": 400,
        "columns": 3,  # for grid layout
    }
    description = "Scrollable image gallery with captions"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return '<div class="gallery-placeholder">No images provided</div>'

        options = self.get_display_options(field_config)
        layout = options.get("layout", "horizontal")
        thumbnail_size = options.get("thumbnail_size", 300)
        show_captions = options.get("show_captions", True)
        caption_key = options.get("caption_key", "caption")
        url_key = options.get("url_key", "url")
        zoomable = options.get("zoomable", True)
        max_height = options.get("max_height", 400)
        columns = options.get("columns", 3)

        field_key = html.escape(field_config.get("key", ""), quote=True)

        # Normalize data to list of {url, caption} dicts
        items = self._normalize_items(data, url_key, caption_key)
        if not items:
            return '<div class="gallery-placeholder">No valid images found</div>'

        # Build CSS
        css = self._build_css(layout, thumbnail_size, max_height, columns, zoomable)

        # Build gallery items
        item_html_list = []
        for i, item in enumerate(items):
            url = html.escape(str(item["url"]), quote=True)
            caption = item.get("caption", "")

            caption_html = ""
            if show_captions and caption:
                escaped_caption = html.escape(str(caption))
                caption_html = f'<div class="gallery-caption">{escaped_caption}</div>'

            zoom_attr = 'data-zoomable="true"' if zoomable else ''

            item_html = f'''
            <div class="gallery-item" data-index="{i}">
                <div class="gallery-img-wrapper">
                    <img src="{url}" alt="Image {i + 1}"
                         class="gallery-img" loading="lazy" {zoom_attr} />
                </div>
                {caption_html}
            </div>
            '''
            item_html_list.append(item_html)

        all_items = "\n".join(item_html_list)

        # Navigation counter for horizontal layout
        nav_html = ""
        counter_js = ""
        if layout == "horizontal" and len(items) > 1:
            nav_html = '''
            <div class="gallery-nav">
                <span class="gallery-counter" data-total="{total}">1 / {total}</span>
            </div>
            '''.format(total=len(items))
            counter_js = '''
            <script>
            (function() {{
                var container = document.querySelector('[data-field-key="{field_key}"] .gallery-container');
                var counter = document.querySelector('[data-field-key="{field_key}"] .gallery-counter');
                if (!container || !counter) return;
                var total = parseInt(counter.getAttribute('data-total')) || 1;
                container.addEventListener('scroll', function() {{
                    var items = container.querySelectorAll('.gallery-item');
                    if (!items.length) return;
                    var containerRect = container.getBoundingClientRect();
                    var centerX = containerRect.left + containerRect.width / 2;
                    var closest = 1;
                    var minDist = Infinity;
                    for (var i = 0; i < items.length; i++) {{
                        var rect = items[i].getBoundingClientRect();
                        var dist = Math.abs(rect.left + rect.width / 2 - centerX);
                        if (dist < minDist) {{ minDist = dist; closest = i + 1; }}
                    }}
                    counter.textContent = closest + ' / ' + total;
                }});
            }})();
            </script>
            '''.format(field_key=field_key)

        return f'''
        <style>{{css}}</style>
        <div class="gallery-display gallery-{{layout}}" data-field-key="{{field_key}}">
            {{nav_html}}
            <div class="gallery-container">
                {{all_items}}
            </div>
        </div>
        {{counter_js}}
        '''.format(css=css, layout=layout, field_key=field_key,
                   nav_html=nav_html, all_items=all_items, counter_js=counter_js)

    def _normalize_items(self, data: Any, url_key: str, caption_key: str) -> List[Dict[str, str]]:
        """Normalize gallery data to list of {url, caption} dicts."""
        items = []

        if isinstance(data, str):
            items.append({"url": data, "caption": ""})
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, str):
                    items.append({"url": item, "caption": f"Step {i + 1}"})
                elif isinstance(item, dict):
                    url = item.get(url_key, item.get("src", item.get("path", "")))
                    caption = item.get(caption_key, item.get("label", item.get("description", "")))
                    if url:
                        items.append({"url": url, "caption": caption})

        return items

    def _build_css(self, layout: str, thumbnail_size: int, max_height: int,
                   columns: int, zoomable: bool) -> str:
        """Build CSS for the gallery layout."""
        # Ensure numeric types for CSS arithmetic
        try:
            thumbnail_size = int(thumbnail_size)
        except (ValueError, TypeError):
            thumbnail_size = 300
        try:
            max_height = int(max_height)
        except (ValueError, TypeError):
            max_height = 400
        try:
            columns = int(columns)
        except (ValueError, TypeError):
            columns = 3

        layout_css = ""

        if layout == "horizontal":
            layout_css = f'''
            .gallery-horizontal .gallery-container {{
                display: flex; overflow-x: auto; gap: 12px;
                padding: 8px 0; max-height: {max_height}px;
                scroll-snap-type: x mandatory;
            }}
            .gallery-horizontal .gallery-item {{
                flex: 0 0 auto; scroll-snap-align: start;
            }}
            .gallery-horizontal .gallery-img {{
                max-height: {max_height - 40}px; width: auto;
                max-width: {thumbnail_size}px;
            }}
            '''
        elif layout == "vertical":
            layout_css = f'''
            .gallery-vertical .gallery-container {{
                display: flex; flex-direction: column; gap: 12px;
                max-height: {max_height}px; overflow-y: auto;
            }}
            .gallery-vertical .gallery-img {{
                max-width: 100%; height: auto;
                max-height: {thumbnail_size}px;
            }}
            '''
        elif layout == "grid":
            layout_css = f'''
            .gallery-grid .gallery-container {{
                display: grid; grid-template-columns: repeat({columns}, 1fr);
                gap: 12px; max-height: {max_height}px; overflow-y: auto;
            }}
            .gallery-grid .gallery-img {{
                width: 100%; height: auto; max-height: {thumbnail_size}px;
                object-fit: cover;
            }}
            '''

        zoom_css = ""
        if zoomable:
            zoom_css = '''
            .gallery-img[data-zoomable]:hover {
                cursor: zoom-in; opacity: 0.9;
            }
            '''

        return f'''
        .gallery-display {{ font-family: inherit; }}
        .gallery-item {{
            border: 1px solid #e0e0e0; border-radius: 6px;
            overflow: hidden; background: #fafafa;
        }}
        .gallery-img-wrapper {{ display: flex; justify-content: center; padding: 4px; }}
        .gallery-img {{ border-radius: 4px; }}
        .gallery-caption {{
            padding: 6px 10px; font-size: 0.85em; color: #555;
            background: #f5f5f5; border-top: 1px solid #e0e0e0;
            text-align: center;
        }}
        .gallery-nav {{
            display: flex; justify-content: center; padding: 4px 0;
            margin-bottom: 8px;
        }}
        .gallery-counter {{ font-size: 0.85em; color: #666; }}
        {layout_css}
        {zoom_css}
        '''
