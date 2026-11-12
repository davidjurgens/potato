"""
Goldilocks Range / Dual-Thumb Slider Layout

Generates a dual-thumb range slider for selecting a min-max range.
Uses custom div-based handles (not native range inputs) for reliable
cross-browser rendering.

Research basis:
- Pavlick & Kwiatkowski (2019) "Inherent Disagreements in Human Textual
  Inferences" TACL
- Jurgens (2013) "Embracing Ambiguity: A Comparison of Annotation Methodologies
  for Crowdsourcing Word Sense Labels" NAACL
"""

import logging

from potato.ai.ai_help_wrapper import get_ai_wrapper
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
)

logger = logging.getLogger(__name__)

DEFAULT_MIN = 0
DEFAULT_MAX = 100
DEFAULT_STEP = 1


def generate_range_slider_layout(annotation_scheme):
    """
    Generate HTML for a dual-thumb range slider interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - min_value: Minimum value (default 0)
            - max_value: Maximum value (default 100)
            - step: Step size (default 1)
            - left_label: Label for left end
            - right_label: Label for right end
            - show_values: Show numeric values (default true)

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_range_slider_layout_internal)


def _generate_range_slider_layout_internal(annotation_scheme):
    schema_name = annotation_scheme["name"]
    safe_schema = escape_html_content(schema_name)
    description = annotation_scheme["description"]
    min_val = annotation_scheme.get("min_value", DEFAULT_MIN)
    max_val = annotation_scheme.get("max_value", DEFAULT_MAX)
    step = annotation_scheme.get("step", DEFAULT_STEP)
    left_label = annotation_scheme.get("left_label", "")
    right_label = annotation_scheme.get("right_label", "")
    show_values = annotation_scheme.get("show_values", True)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)

    id_low = generate_element_identifier(schema_name, "range_low", "range")
    id_high = generate_element_identifier(schema_name, "range_high", "range")

    html = f"""
    <form id="{safe_schema}" class="annotation-form range_slider shadcn-range-slider-container"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="range_slider"
          data-schema-name="{safe_schema}"
          {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{safe_schema}">
            <legend class="shadcn-range-slider-title">{escape_html_content(description)}</legend>
            <div class="range-slider-wrapper">
    """

    if left_label or right_label:
        html += f"""
                <div class="range-slider-labels">
                    <span class="range-slider-label-left">{escape_html_content(left_label)}</span>
                    <span class="range-slider-label-right">{escape_html_content(right_label)}</span>
                </div>
        """

    html += f"""
                <div class="range-slider-track range-slider-unset" id="range-slider-track-{safe_schema}">
                    <div class="range-slider-fill" id="range-slider-fill-{safe_schema}"></div>
                    <div class="range-slider-thumb range-slider-thumb-low"
                         id="range-slider-thumb-low-{safe_schema}"
                         tabindex="0" role="slider"
                         aria-label="Low value"
                         aria-valuemin="{min_val}" aria-valuemax="{max_val}" aria-valuenow="{min_val}"
                         aria-valuetext="No range set">
                    </div>
                    <div class="range-slider-thumb range-slider-thumb-high"
                         id="range-slider-thumb-high-{safe_schema}"
                         tabindex="0" role="slider"
                         aria-label="High value"
                         aria-valuemin="{min_val}" aria-valuemax="{max_val}" aria-valuenow="{max_val}"
                         aria-valuetext="No range set">
                    </div>
                </div>
                <!-- Hidden inputs for annotation pipeline -->
                <input type="hidden"
                       class="annotation-input range-slider-hidden-input"
                       id="{id_low['id']}"
                       name="{id_low['name']}"
                       schema="{id_low['schema']}"
                       label_name="{id_low['label_name']}"
                       validation="{validation}"
                       value=""
                       data-range-slider-role="low"
                       data-range-slider-group="{safe_schema}">
                <input type="hidden"
                       class="annotation-input range-slider-hidden-input"
                       id="{id_high['id']}"
                       name="{id_high['name']}"
                       schema="{id_high['schema']}"
                       label_name="{id_high['label_name']}"
                       validation="{validation}"
                       value=""
                       data-range-slider-role="high"
                       data-range-slider-group="{safe_schema}">
    """

    if show_values:
        html += f"""
                <div class="range-slider-values" id="range-slider-values-{safe_schema}">
                    <span class="range-slider-unset-hint">No range set</span>
                    <span class="range-slider-val-low" id="range-slider-low-val-{safe_schema}">{min_val}</span>
                    <span class="range-slider-val-sep">&ndash;</span>
                    <span class="range-slider-val-high" id="range-slider-high-val-{safe_schema}">{max_val}</span>
                </div>
        """

    html += f"""
            </div>
        </fieldset>
    </form>
    <script>
    (function() {{
        var schema = "{safe_schema}";
        var minVal = {min_val}, maxVal = {max_val}, step = {step};
        var track = document.getElementById('range-slider-track-' + schema);
        var fill = document.getElementById('range-slider-fill-' + schema);
        var thumbLow = document.getElementById('range-slider-thumb-low-' + schema);
        var thumbHigh = document.getElementById('range-slider-thumb-high-' + schema);
        var inputLow = document.querySelector('[data-range-slider-group="' + schema + '"][data-range-slider-role="low"]');
        var inputHigh = document.querySelector('[data-range-slider-group="' + schema + '"][data-range-slider-role="high"]');
        var lowValEl = document.getElementById('range-slider-low-val-' + schema);
        var highValEl = document.getElementById('range-slider-high-val-' + schema);

        var valuesEl = document.getElementById('range-slider-values-' + schema);

        // Until the annotator moves a thumb this widget has no answer, and it
        // must not look like it does. It used to open with the thumbs at the
        // 25th and 75th percentile and the band drawn between them while both
        // hidden inputs were empty, so agreeing with the range on screen
        // recorded nothing and nothing said so. Unset means: thumbs at the ends,
        // no band, no numbers, and empty inputs.
        var isSet = inputLow.value !== '' && inputHigh.value !== '';
        var lowValue = isSet ? parseInt(inputLow.value) : minVal;
        var highValue = isSet ? parseInt(inputHigh.value) : maxVal;

        function valToPercent(v) {{
            return ((v - minVal) / (maxVal - minVal)) * 100;
        }}

        function percentToVal(pct) {{
            var raw = minVal + (pct / 100) * (maxVal - minVal);
            // Snap to step
            raw = Math.round(raw / step) * step;
            return Math.max(minVal, Math.min(maxVal, raw));
        }}

        function render() {{
            var lowPct = valToPercent(lowValue);
            var highPct = valToPercent(highValue);
            thumbLow.style.left = lowPct + '%';
            thumbHigh.style.left = highPct + '%';
            fill.style.left = lowPct + '%';
            fill.style.width = (highPct - lowPct) + '%';
            if (lowValEl) lowValEl.textContent = lowValue;
            if (highValEl) highValEl.textContent = highValue;
            thumbLow.setAttribute('aria-valuenow', lowValue);
            thumbHigh.setAttribute('aria-valuenow', highValue);
            // `aria-valuenow` cannot be empty, so while unset it necessarily
            // reports the end of the scale -- which a screen reader would read
            // out as an answer of "1" or "16". aria-valuetext overrides it, so
            // the announced state matches the "No range set" on screen.
            [thumbLow, thumbHigh].forEach(function (thumb) {{
                if (isSet) thumb.removeAttribute('aria-valuetext');
                else thumb.setAttribute('aria-valuetext', 'No range set');
            }});
            inputLow.value = isSet ? lowValue : '';
            inputHigh.value = isSet ? highValue : '';
            track.classList.toggle('range-slider-unset', !isSet);
            if (valuesEl) valuesEl.classList.toggle('range-slider-unset', !isSet);
        }}

        /** The first real interaction turns the shown range into an answer. */
        function markSet() {{
            isSet = true;
            inputLow.setAttribute('data-modified', 'true');
            inputHigh.setAttribute('data-modified', 'true');
        }}

        function startDrag(thumbEl, isLow) {{
            markSet();
            function onMove(e) {{
                e.preventDefault();
                var clientX = e.touches ? e.touches[0].clientX : e.clientX;
                var rect = track.getBoundingClientRect();
                var pct = ((clientX - rect.left) / rect.width) * 100;
                pct = Math.max(0, Math.min(100, pct));
                var val = percentToVal(pct);
                if (isLow) {{
                    lowValue = Math.min(val, highValue);
                }} else {{
                    highValue = Math.max(val, lowValue);
                }}
                render();
            }}

            function onEnd() {{
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onEnd);
                document.removeEventListener('touchmove', onMove);
                document.removeEventListener('touchend', onEnd);
                markSet();
                render();
                inputLow.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onEnd);
            document.addEventListener('touchmove', onMove, {{ passive: false }});
            document.addEventListener('touchend', onEnd);
        }}

        thumbLow.addEventListener('mousedown', function(e) {{ e.preventDefault(); startDrag(thumbLow, true); }});
        thumbLow.addEventListener('touchstart', function(e) {{ e.preventDefault(); startDrag(thumbLow, true); }}, {{ passive: false }});
        thumbHigh.addEventListener('mousedown', function(e) {{ e.preventDefault(); startDrag(thumbHigh, false); }});
        thumbHigh.addEventListener('touchstart', function(e) {{ e.preventDefault(); startDrag(thumbHigh, false); }}, {{ passive: false }});

        // Click on track to move nearest thumb
        track.addEventListener('mousedown', function(e) {{
            if (e.target === thumbLow || e.target === thumbHigh) return;
            var rect = track.getBoundingClientRect();
            var pct = ((e.clientX - rect.left) / rect.width) * 100;
            var val = percentToVal(pct);
            var distLow = Math.abs(val - lowValue);
            var distHigh = Math.abs(val - highValue);
            if (distLow <= distHigh) {{
                lowValue = Math.min(val, highValue);
                startDrag(thumbLow, true);
            }} else {{
                highValue = Math.max(val, lowValue);
                startDrag(thumbHigh, false);
            }}
            render();
        }});

        // Keyboard support
        function handleKey(e, isLow) {{
            var delta = e.shiftKey ? step * 10 : step;
            if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {{
                e.preventDefault();
                markSet();
                if (isLow) lowValue = Math.max(minVal, lowValue - delta);
                else highValue = Math.max(lowValue, highValue - delta);
                render();
                inputLow.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }} else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {{
                e.preventDefault();
                markSet();
                if (isLow) lowValue = Math.min(highValue, lowValue + delta);
                else highValue = Math.min(maxVal, highValue + delta);
                render();
                inputLow.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}
        thumbLow.addEventListener('keydown', function(e) {{ handleKey(e, true); }});
        thumbHigh.addEventListener('keydown', function(e) {{ handleKey(e, false); }});

        // Expose for restoration
        window['rangeSliderRender_' + schema] = function(low, high) {{
            isSet = true;
            lowValue = low;
            highValue = high;
            render();
        }};

        render();
    }})();
    </script>
    """

    key_bindings = []
    logger.info(f"Generated range_slider layout for {schema_name}")
    return html, key_bindings
