"""
Region captioning: draw a region, describe it.

The inverse of :mod:`~potato.server_utils.schemas.grounding_eval`. There the
language is given and the annotator finds the region; here the annotator finds
the regions and supplies the language.

## Why this one does not swap the canvas

Grounding holds one expression's region on the canvas at a time, because a
shape has to be attributed to exactly one phrase and tagging shapes with a
foreign field is fragile. Captioning has the opposite shape: the regions are
drawn freely, all of them belong on screen together, and the caption is
attached to a region **by its position in the annotation list** rather than the
other way round.

That index is the fragile part, and it is why the caption list is rebuilt from
the canvas on every change rather than kept in parallel: deleting the second of
three regions must move the third region's caption up with it, and a
side-by-side list that is not rebuilt would leave the caption attached to the
wrong shape — silently, and looking exactly like a correct caption of a
different object.
"""

import json
import logging

from .identifier_utils import escape_html_content, safe_generate_layout

logger = logging.getLogger(__name__)


def generate_region_caption_layout(annotation_scheme):
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme):
    schema_name = annotation_scheme.get("name", "region_caption")
    escaped_name = escape_html_content(schema_name)
    description = escape_html_content(
        annotation_scheme.get("description", "Describe each region"))

    config = {
        "schemaName": schema_name,
        "placeholder": annotation_scheme.get(
            "placeholder", "Describe this region…"),
        "minLength": int(annotation_scheme.get("min_length", 0)),
        "maxLength": int(annotation_scheme.get("max_length", 0)),
        # Warn once before advancing with regions undescribed. Off by default:
        # an annotator legitimately draws every region first and captions them
        # afterwards, and a hard gate mid-pass is an obstacle.
        "requireAll": bool(annotation_scheme.get("require_all", False)),
    }

    html = f"""
<div class="region-caption-container" data-schema="{escaped_name}">
    <fieldset class="region-caption-fieldset">
        <legend class="region-caption-legend">{description}</legend>

        <p class="region-caption-help">
            Draw a region on the image, then describe it. The list below follows
            the regions on the canvas: delete a region and its description goes
            with it.
        </p>

        <ol id="region-caption-list-{escaped_name}" class="region-caption-list"></ol>

        <p class="region-caption-progress"
           id="region-caption-progress-{escaped_name}" aria-live="polite"></p>
        <span class="region-caption-announce sr-only" role="status"
              id="region-caption-announce-{escaped_name}"></span>

        <input type="hidden" name="{escaped_name}" id="input-{escaped_name}"
               class="annotation-data-input" value="">
    </fieldset>
</div>

<script>
(function () {{
    var config = {json.dumps(config)};
    function boot() {{
        var container = document.querySelector(
            '.region-caption-container[data-schema="{escaped_name}"]');
        if (!container || typeof RegionCaptionManager === 'undefined') return;
        try {{
            var manager = new RegionCaptionManager(container, config);
            container.regionCaptionManager = manager;
            manager.init();
        }} catch (error) {{
            console.error('Region captioning failed to start:', error);
            container.classList.add('error');
        }}
    }}
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', boot);
    }} else {{
        boot();
    }}
}})();
</script>
"""
    return html, []
