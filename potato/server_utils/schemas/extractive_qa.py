"""
Extractive QA / Answer Span Layout

Display a question and a passage; annotator highlights the answer span in the passage.
A streamlined SQuAD-style workflow that combines question display with directed span selection.

Research: Rajpurkar et al. (2016) "SQuAD"; Kwiatkowski et al. (2019) "Natural Questions".
"""

import logging

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)


logger = logging.getLogger(__name__)

DEFAULT_HIGHLIGHT_COLOR = "#FFEB3B"
DEFAULT_ALLOW_UNANSWERABLE = True


def generate_extractive_qa_layout(annotation_scheme):
    """
    Generate HTML for an Extractive QA interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - question_field: Field in data containing the question
            - passage_field: Field in data containing the passage
            - allow_unanswerable: Whether to show "Unanswerable" button
            - highlight_color: Color for answer highlight

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_extractive_qa_layout_internal)


def _generate_extractive_qa_layout_internal(annotation_scheme):
    schema_name = annotation_scheme['name']
    description = annotation_scheme['description']
    question_field = annotation_scheme.get('question_field', 'question')
    passage_field = annotation_scheme.get('passage_field', '')
    allow_unanswerable = annotation_scheme.get('allow_unanswerable', DEFAULT_ALLOW_UNANSWERABLE)
    highlight_color = annotation_scheme.get('highlight_color', DEFAULT_HIGHLIGHT_COLOR)

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    unanswerable_btn = ""
    if allow_unanswerable:
        unanswerable_btn = f"""
            <button type="button" class="eqa-unanswerable-btn" id="{schema_name}-unanswerable"
                    onclick="eqaMarkUnanswerable('{escape_html_content(schema_name)}')">
                Unanswerable
            </button>
        """

    html = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form shadcn-extractive-qa-container"
          action="/action_page.php"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="extractive_qa"
          data-schema-name="{escape_html_content(schema_name)}"
          data-question-field="{escape_html_content(question_field)}"
          data-passage-field="{escape_html_content(passage_field)}"
          data-highlight-color="{escape_html_content(highlight_color)}"
          {layout_attrs}>
        <fieldset schema_name="{escape_html_content(schema_name)}">
            <legend class="shadcn-eqa-title">{escape_html_content(description)}</legend>

            <div class="eqa-question-box" id="{schema_name}-question">
                <span class="eqa-question-label">Question:</span>
                <span class="eqa-question-text" data-field="{escape_html_content(question_field)}"></span>
            </div>

            <div class="eqa-passage-container" id="{schema_name}-passage"
                 data-schema="{escape_html_content(schema_name)}"
                 data-highlight-color="{escape_html_content(highlight_color)}"
                 onmouseup="eqaHandleSelection('{escape_html_content(schema_name)}')">
            </div>

            <div class="eqa-answer-display" id="{schema_name}-answer-display">
                <span class="eqa-answer-label">Selected answer:</span>
                <span class="eqa-answer-text" id="{schema_name}-answer-text">—</span>
            </div>

            <div class="eqa-controls">
                <button type="button" class="eqa-clear-btn"
                        onclick="eqaClearSelection('{escape_html_content(schema_name)}')">
                    Clear Selection
                </button>
                {unanswerable_btn}
            </div>

            <input type="hidden"
                   class="annotation-input eqa-data-input"
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
        // Extractive QA functions
        window.eqaHandleSelection = function(schemaName) {{
            var container = document.getElementById(schemaName + '-passage');
            var selection = window.getSelection();
            if (!selection.rangeCount || selection.isCollapsed) return;

            var range = selection.getRangeAt(0);
            // Ensure selection is within the passage container
            if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) return;

            var text = selection.toString().trim();
            if (!text) return;

            // Calculate offsets relative to passage text
            var passageText = container.textContent;
            var preRange = document.createRange();
            preRange.setStart(container, 0);
            preRange.setEnd(range.startContainer, range.startOffset);
            var start = preRange.toString().length;
            var end = start + text.length;

            // Clear previous highlight
            eqaClearHighlight(schemaName);

            // Apply highlight
            try {{
                var highlightSpan = document.createElement('span');
                highlightSpan.className = 'eqa-highlight';
                highlightSpan.style.backgroundColor = container.dataset.highlightColor || '#FFEB3B';
                range.surroundContents(highlightSpan);
            }} catch(e) {{
                // If surroundContents fails (cross-element selection), use simple approach
                container.innerHTML = passageText.substring(0, start) +
                    '<span class="eqa-highlight" style="background-color:' + (container.dataset.highlightColor || '#FFEB3B') + '">' +
                    passageText.substring(start, end) + '</span>' +
                    passageText.substring(end);
            }}

            selection.removeAllRanges();

            // Update answer display
            document.getElementById(schemaName + '-answer-text').textContent = text;

            // Store in hidden input
            var data = JSON.stringify({{
                answer_text: text,
                start: start,
                end: end,
                unanswerable: false
            }});
            var input = container.closest('form').querySelector('.eqa-data-input');
            input.value = data;
            input.setAttribute('data-modified', 'true');
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));

            // Remove unanswerable state if present
            var unansBtn = document.getElementById(schemaName + '-unanswerable');
            if (unansBtn) unansBtn.classList.remove('eqa-unanswerable-active');
        }};

        window.eqaClearSelection = function(schemaName) {{
            eqaClearHighlight(schemaName);
            document.getElementById(schemaName + '-answer-text').textContent = '\\u2014';

            var form = document.getElementById(schemaName);
            var input = form.querySelector('.eqa-data-input');
            input.value = '';
            input.removeAttribute('data-modified');
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));

            var unansBtn = document.getElementById(schemaName + '-unanswerable');
            if (unansBtn) unansBtn.classList.remove('eqa-unanswerable-active');
        }};

        window.eqaMarkUnanswerable = function(schemaName) {{
            eqaClearHighlight(schemaName);
            document.getElementById(schemaName + '-answer-text').textContent = 'Unanswerable';

            var data = JSON.stringify({{
                answer_text: '',
                start: -1,
                end: -1,
                unanswerable: true
            }});
            var form = document.getElementById(schemaName);
            var input = form.querySelector('.eqa-data-input');
            input.value = data;
            input.setAttribute('data-modified', 'true');
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));

            var unansBtn = document.getElementById(schemaName + '-unanswerable');
            if (unansBtn) unansBtn.classList.add('eqa-unanswerable-active');
        }};

        function eqaClearHighlight(schemaName) {{
            var container = document.getElementById(schemaName + '-passage');
            var highlights = container.querySelectorAll('.eqa-highlight');
            highlights.forEach(function(span) {{
                var parent = span.parentNode;
                while (span.firstChild) parent.insertBefore(span.firstChild, span);
                parent.removeChild(span);
                parent.normalize();
            }});
        }}
    }})();
    </script>
    """

    logger.info(f"Generated extractive QA layout for {schema_name}")
    return html, []
