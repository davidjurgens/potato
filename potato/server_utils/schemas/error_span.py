"""
Error Span with Typed Severity Layout

Mark error spans in text, assign each an error type from a configurable taxonomy
and a severity level. Computes an overall quality score. This is the MQM
(Multidimensional Quality Metrics) annotation workflow.

Research: Lommel et al. "Multidimensional Quality Metrics" (themqm.org); WMT 2024 ESA.
"""

import json
import logging

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)


logger = logging.getLogger(__name__)

DEFAULT_SEVERITIES = [
    {"name": "Minor", "weight": -1},
    {"name": "Major", "weight": -5},
    {"name": "Critical", "weight": -10},
]
DEFAULT_MAX_SCORE = 100


def generate_error_span_layout(annotation_scheme):
    """
    Generate HTML for an Error Span with Typed Severity interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - error_types: List of {name, subtypes?} dicts
            - severities: List of {name, weight} dicts
            - show_score: Whether to show quality score
            - max_score: Maximum quality score

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_error_span_layout_internal)


def _generate_error_span_layout_internal(annotation_scheme):
    schema_name = annotation_scheme['name']
    description = annotation_scheme['description']
    error_types = annotation_scheme.get('error_types', [])
    severities = annotation_scheme.get('severities', DEFAULT_SEVERITIES)
    show_score = annotation_scheme.get('show_score', True)
    max_score = annotation_scheme.get('max_score', DEFAULT_MAX_SCORE)

    if not error_types:
        raise ValueError(f"error_span schema '{schema_name}' requires 'error_types'")

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    # Serialize config for JS
    config_json = json.dumps({
        'error_types': error_types,
        'severities': severities,
        'max_score': max_score,
        'show_score': show_score,
    })

    # Build error type options HTML for the popup
    type_options = ""
    for et in error_types:
        subtypes = et.get('subtypes', [])
        if subtypes:
            type_options += f'<optgroup label="{escape_html_content(et["name"])}">'
            for st in subtypes:
                type_options += f'<option value="{escape_html_content(et["name"])}::{escape_html_content(st)}">{escape_html_content(st)}</option>'
            type_options += '</optgroup>'
        else:
            type_options += f'<option value="{escape_html_content(et["name"])}">{escape_html_content(et["name"])}</option>'

    # Build severity radio buttons for the popup
    severity_radios = ""
    for sev in severities:
        severity_radios += f"""
            <label class="error-span-severity-option">
                <input type="radio" name="error-span-severity-{schema_name}" value="{escape_html_content(sev['name'])}">
                <span class="error-span-severity-label">{escape_html_content(sev['name'])} ({sev['weight']:+d})</span>
            </label>
        """

    score_display = ""
    if show_score:
        score_display = f"""
            <div class="error-span-score" id="{schema_name}-score">
                Score: <strong id="{schema_name}-score-value">{max_score}</strong> / {max_score}
            </div>
        """

    html = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form shadcn-error-span-container"
          action="javascript:void(0)"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="error_span"
          data-schema-name="{escape_html_content(schema_name)}"
          {layout_attrs}>
        <fieldset schema_name="{escape_html_content(schema_name)}">
            <legend class="shadcn-error-span-title">{escape_html_content(description)}</legend>

            <div class="error-span-text-container" id="{schema_name}-text"
                 data-schema="{escape_html_content(schema_name)}"
                 onmouseup="errorSpanHandleSelection('{escape_html_content(schema_name)}')">
            </div>
            <div class="error-span-hint">Select text above to mark an error</div>

            {score_display}

            <!-- Error annotation popup (hidden by default) -->
            <div class="error-span-popup" id="{schema_name}-popup" style="display:none;">
                <div class="error-span-popup-header">Annotate Error</div>
                <div class="error-span-popup-selection" id="{schema_name}-popup-selection"></div>
                <div class="error-span-popup-field">
                    <label>Error Type:</label>
                    <select id="{schema_name}-popup-type" class="error-span-type-select">
                        {type_options}
                    </select>
                </div>
                <div class="error-span-popup-field">
                    <label>Severity:</label>
                    <div class="error-span-severity-group">
                        {severity_radios}
                    </div>
                </div>
                <div class="error-span-popup-actions">
                    <button type="button" class="error-span-popup-save"
                            onclick="errorSpanSaveAnnotation('{escape_html_content(schema_name)}')">Save</button>
                    <button type="button" class="error-span-popup-cancel"
                            onclick="errorSpanCancelPopup('{escape_html_content(schema_name)}')">Cancel</button>
                </div>
            </div>

            <!-- Error list -->
            <div class="error-span-list" id="{schema_name}-error-list">
                <div class="error-span-list-header">Marked Errors:</div>
                <div class="error-span-list-items" id="{schema_name}-error-items"></div>
            </div>

            <input type="hidden"
                   class="annotation-input error-span-data-input"
                   id="{identifiers['id']}"
                   name="{identifiers['name']}"
                   schema="{identifiers['schema']}"
                   label_name="{identifiers['label_name']}"
                   validation="{validation}"
                   value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var errorSpanState = {{}};

        function getState(schemaName) {{
            if (!errorSpanState[schemaName]) {{
                errorSpanState[schemaName] = {{
                    errors: [],
                    config: {config_json},
                    pendingSelection: null
                }};
            }}
            return errorSpanState[schemaName];
        }}

        window.errorSpanHandleSelection = function(schemaName) {{
            var container = document.getElementById(schemaName + '-text');
            var selection = window.getSelection();
            if (!selection.rangeCount || selection.isCollapsed) return;

            var range = selection.getRangeAt(0);
            if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) return;

            var text = selection.toString().trim();
            if (!text) return;

            // Calculate offsets
            var preRange = document.createRange();
            preRange.setStart(container, 0);
            preRange.setEnd(range.startContainer, range.startOffset);
            var start = preRange.toString().length;
            var end = start + text.length;

            var state = getState(schemaName);
            state.pendingSelection = {{ text: text, start: start, end: end }};

            // Temporarily highlight the selected text
            var origHTML = container.innerHTML;
            state.pendingOrigHTML = origHTML;
            var origText = container.dataset.originalText || container.textContent;
            var before = escapeHtml(origText.substring(0, start));
            var sel = escapeHtml(origText.substring(start, end));
            var after = escapeHtml(origText.substring(end));
            container.innerHTML = before + '<span class="error-span-pending">' + sel + '</span>' + after;

            // Show popup with selected text preview
            var popup = document.getElementById(schemaName + '-popup');
            popup.style.display = 'block';
            var selPreview = document.getElementById(schemaName + '-popup-selection');
            if (selPreview) selPreview.textContent = '\u201c' + text + '\u201d';

            // Reset popup form
            document.getElementById(schemaName + '-popup-type').selectedIndex = 0;
            var radios = popup.querySelectorAll('input[type="radio"]');
            radios.forEach(function(r) {{ r.checked = false; }});

            selection.removeAllRanges();
        }};

        window.errorSpanSaveAnnotation = function(schemaName) {{
            var state = getState(schemaName);
            if (!state.pendingSelection) return;

            var typeSelect = document.getElementById(schemaName + '-popup-type');
            var typeValue = typeSelect.value;
            var severityRadio = document.querySelector('input[name="error-span-severity-' + schemaName + '"]:checked');
            if (!severityRadio) {{ alert('Please select a severity level.'); return; }}

            var typeParts = typeValue.split('::');
            var errorType = typeParts[0];
            var subtype = typeParts.length > 1 ? typeParts[1] : '';

            var error = {{
                start: state.pendingSelection.start,
                end: state.pendingSelection.end,
                text: state.pendingSelection.text,
                type: errorType,
                subtype: subtype,
                severity: severityRadio.value
            }};

            state.errors.push(error);
            state.pendingSelection = null;

            document.getElementById(schemaName + '-popup').style.display = 'none';
            errorSpanUpdateDisplay(schemaName);
            errorSpanSaveData(schemaName);
        }};

        window.errorSpanCancelPopup = function(schemaName) {{
            var state = getState(schemaName);
            state.pendingSelection = null;
            document.getElementById(schemaName + '-popup').style.display = 'none';
            // Remove pending highlight — re-render with current errors
            errorSpanUpdateDisplay(schemaName);
        }};

        window.errorSpanRemoveError = function(schemaName, index) {{
            var state = getState(schemaName);
            state.errors.splice(index, 1);
            errorSpanUpdateDisplay(schemaName);
            errorSpanSaveData(schemaName);
        }};

        function errorSpanUpdateDisplay(schemaName) {{
            var state = getState(schemaName);
            var container = document.getElementById(schemaName + '-text');
            var originalText = container.dataset.originalText || container.textContent;
            if (!container.dataset.originalText) container.dataset.originalText = originalText;

            // Rebuild text with error highlights
            var segments = [];
            var sorted = state.errors.slice().sort(function(a, b) {{ return a.start - b.start; }});
            var pos = 0;

            sorted.forEach(function(err, idx) {{
                if (err.start > pos) segments.push({{ text: originalText.substring(pos, err.start), isError: false }});
                var sevClass = 'error-span-sev-' + err.severity.toLowerCase();
                segments.push({{ text: originalText.substring(err.start, err.end), isError: true, cls: sevClass, type: err.type }});
                pos = err.end;
            }});
            if (pos < originalText.length) segments.push({{ text: originalText.substring(pos), isError: false }});

            var html = '';
            segments.forEach(function(seg) {{
                if (seg.isError) {{
                    html += '<span class="error-span-marked ' + seg.cls + '" title="' + seg.type + '">' +
                            escapeHtml(seg.text) + '</span>';
                }} else {{
                    html += escapeHtml(seg.text);
                }}
            }});
            container.innerHTML = html;

            // Update error list
            var listItems = document.getElementById(schemaName + '-error-items');
            var listHtml = '';
            state.errors.forEach(function(err, idx) {{
                listHtml += '<div class="error-span-list-item">' +
                    '<span class="error-span-list-text">"' + escapeHtml(err.text.substring(0, 30)) + (err.text.length > 30 ? '...' : '') + '"</span> ' +
                    '<span class="error-span-list-type">' + escapeHtml(err.type) + (err.subtype ? '/' + escapeHtml(err.subtype) : '') + '</span> ' +
                    '<span class="error-span-list-severity error-span-sev-' + err.severity.toLowerCase() + '">' + escapeHtml(err.severity) + '</span> ' +
                    '<button type="button" class="error-span-remove-btn" onclick="errorSpanRemoveError(\\'' + schemaName + '\\',' + idx + ')">&times;</button>' +
                    '</div>';
            }});
            listItems.innerHTML = listHtml || '<div class="error-span-list-empty">No errors marked</div>';

            // Update score
            if (state.config.show_score) {{
                var totalPenalty = 0;
                state.errors.forEach(function(err) {{
                    var sev = state.config.severities.find(function(s) {{ return s.name === err.severity; }});
                    if (sev) totalPenalty += Math.abs(sev.weight);
                }});
                var score = Math.max(0, state.config.max_score - totalPenalty);
                var scoreEl = document.getElementById(schemaName + '-score-value');
                if (scoreEl) scoreEl.textContent = score;
            }}
        }}

        function errorSpanSaveData(schemaName) {{
            var state = getState(schemaName);
            var totalPenalty = 0;
            state.errors.forEach(function(err) {{
                var sev = state.config.severities.find(function(s) {{ return s.name === err.severity; }});
                if (sev) totalPenalty += Math.abs(sev.weight);
            }});
            var score = Math.max(0, state.config.max_score - totalPenalty);

            var data = JSON.stringify({{
                errors: state.errors,
                score: score
            }});
            var input = document.getElementById(schemaName).querySelector('.error-span-data-input');
            input.value = data;
            input.setAttribute('data-modified', 'true');
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}

        function escapeHtml(str) {{
            var div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }}

        // Make state accessible for populate/clear
        window._errorSpanState = errorSpanState;
        window._errorSpanGetState = getState;
        window._errorSpanUpdateDisplay = errorSpanUpdateDisplay;
        window._errorSpanSaveData = errorSpanSaveData;
    }})();
    </script>
    """

    logger.info(f"Generated error span layout for {schema_name}")
    return html, []
