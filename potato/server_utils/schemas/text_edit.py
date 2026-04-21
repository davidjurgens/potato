"""
Inline Text Editing / Post-Edit Layout

Annotators directly edit displayed text, with the system tracking insertions,
deletions, and substitutions as a structured diff. Used for MT post-editing,
grammar correction, text simplification, and paraphrase generation.

Research: WMT post-editing shared tasks; MQM-APE (COLING 2025).
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


def generate_text_edit_layout(annotation_scheme):
    """
    Generate HTML for an Inline Text Editing interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - source_field: Field in data containing text to edit
            - show_diff: Whether to show real-time diff highlighting
            - show_edit_distance: Whether to show edit distance counter
            - allow_reset: Whether to show "Reset to original" button

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_text_edit_layout_internal)


def _generate_text_edit_layout_internal(annotation_scheme):
    schema_name = annotation_scheme['name']
    description = annotation_scheme['description']
    source_field = annotation_scheme.get('source_field', '')
    show_diff = annotation_scheme.get('show_diff', True)
    show_edit_distance = annotation_scheme.get('show_edit_distance', True)
    allow_reset = annotation_scheme.get('allow_reset', True)

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    reset_btn = ""
    if allow_reset:
        reset_btn = f"""
            <button type="button" class="text-edit-reset-btn"
                    onclick="textEditReset('{escape_html_content(schema_name)}')">
                Reset to Original
            </button>
        """

    diff_display = ""
    if show_diff:
        diff_display = f"""
            <div class="text-edit-diff-display" id="{schema_name}-diff">
                <div class="text-edit-diff-label">Changes:</div>
                <div class="text-edit-diff-content" id="{schema_name}-diff-content"></div>
            </div>
        """

    edit_distance_display = ""
    if show_edit_distance:
        edit_distance_display = f"""
            <div class="text-edit-stats" id="{schema_name}-stats">
                <span class="text-edit-stat">Words changed: <strong id="{schema_name}-word-dist">0</strong></span>
                <span class="text-edit-stat">Chars changed: <strong id="{schema_name}-char-dist">0</strong></span>
            </div>
        """

    html = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form shadcn-text-edit-container"
          action="javascript:void(0)"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="text_edit"
          data-schema-name="{escape_html_content(schema_name)}"
          data-source-field="{escape_html_content(source_field)}"
          {layout_attrs}>
        <fieldset schema_name="{escape_html_content(schema_name)}">
            <legend class="shadcn-text-edit-title">{escape_html_content(description)}</legend>

            <div class="text-edit-source-block" id="{schema_name}-source">
                <div class="text-edit-source-label">Original:</div>
                <div class="text-edit-source-text" id="{schema_name}-source-text"></div>
            </div>

            <div class="text-edit-editor-block">
                <div class="text-edit-editor-label">Edit below:</div>
                <textarea class="text-edit-textarea annotation-input"
                          id="{schema_name}-editor"
                          name="{identifiers['name']}"
                          schema="{identifiers['schema']}"
                          label_name="{identifiers['label_name']}"
                          validation="{validation}"
                          rows="5"
                          oninput="textEditOnInput('{escape_html_content(schema_name)}')"></textarea>
            </div>

            {edit_distance_display}
            {diff_display}

            <div class="text-edit-controls">
                {reset_btn}
            </div>

            <input type="hidden"
                   class="annotation-input text-edit-data-input"
                   id="{identifiers['id']}"
                   name="{identifiers['name']}-data"
                   schema="{identifiers['schema']}"
                   label_name="{identifiers['label_name']}"
                   validation="{validation}"
                   value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        window.textEditOnInput = function(schemaName) {{
            var editor = document.getElementById(schemaName + '-editor');
            var sourceText = document.getElementById(schemaName + '-source-text').textContent || '';
            var editedText = editor.value;

            // Compute word-level edit distance
            var srcWords = sourceText.trim().split(/\\s+/).filter(function(w) {{ return w; }});
            var editWords = editedText.trim().split(/\\s+/).filter(function(w) {{ return w; }});
            var wordDist = levenshtein(srcWords, editWords);
            var charDist = levenshteinStr(sourceText, editedText);

            // Update stats
            var wordEl = document.getElementById(schemaName + '-word-dist');
            var charEl = document.getElementById(schemaName + '-char-dist');
            if (wordEl) wordEl.textContent = wordDist;
            if (charEl) charEl.textContent = charDist;

            // Update diff display
            var diffContent = document.getElementById(schemaName + '-diff-content');
            if (diffContent) {{
                diffContent.innerHTML = computeWordDiff(srcWords, editWords);
            }}

            // Store result in hidden input
            var data = JSON.stringify({{
                edited_text: editedText,
                original_text: sourceText,
                edit_distance_chars: charDist,
                edit_distance_words: wordDist
            }});
            var hiddenInput = document.getElementById(schemaName).querySelector('.text-edit-data-input');
            hiddenInput.value = data;
            hiddenInput.setAttribute('data-modified', 'true');
            hiddenInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }};

        window.textEditReset = function(schemaName) {{
            var sourceText = document.getElementById(schemaName + '-source-text').textContent || '';
            document.getElementById(schemaName + '-editor').value = sourceText;
            textEditOnInput(schemaName);
        }};

        function levenshtein(a, b) {{
            var m = a.length, n = b.length;
            var dp = Array.from({{length: m + 1}}, function() {{ return new Array(n + 1).fill(0); }});
            for (var i = 0; i <= m; i++) dp[i][0] = i;
            for (var j = 0; j <= n; j++) dp[0][j] = j;
            for (var i = 1; i <= m; i++)
                for (var j = 1; j <= n; j++)
                    dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] :
                        1 + Math.min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]);
            return dp[m][n];
        }}

        function levenshteinStr(a, b) {{
            // Character-level Levenshtein with optimization for long strings
            var m = a.length, n = b.length;
            if (m === 0) return n;
            if (n === 0) return m;
            // Use two-row optimization
            var prev = new Array(n + 1);
            var curr = new Array(n + 1);
            for (var j = 0; j <= n; j++) prev[j] = j;
            for (var i = 1; i <= m; i++) {{
                curr[0] = i;
                for (var j = 1; j <= n; j++)
                    curr[j] = a[i-1] === b[j-1] ? prev[j-1] :
                        1 + Math.min(prev[j], curr[j-1], prev[j-1]);
                var tmp = prev; prev = curr; curr = tmp;
            }}
            return prev[n];
        }}

        function computeWordDiff(srcWords, editWords) {{
            // Simple word diff visualization
            var html = '';
            var si = 0, ei = 0;
            // Use LCS-based approach
            var lcs = lcsWords(srcWords, editWords);
            var li = 0;
            si = 0; ei = 0;

            while (si < srcWords.length || ei < editWords.length) {{
                if (li < lcs.length && si < srcWords.length && ei < editWords.length &&
                    srcWords[si] === lcs[li] && editWords[ei] === lcs[li]) {{
                    html += '<span class="text-edit-diff-same">' + escapeHtml(lcs[li]) + '</span> ';
                    si++; ei++; li++;
                }} else if (li < lcs.length && ei < editWords.length && editWords[ei] === lcs[li]) {{
                    html += '<span class="text-edit-diff-del">' + escapeHtml(srcWords[si]) + '</span> ';
                    si++;
                }} else if (li < lcs.length && si < srcWords.length && srcWords[si] === lcs[li]) {{
                    html += '<span class="text-edit-diff-ins">' + escapeHtml(editWords[ei]) + '</span> ';
                    ei++;
                }} else {{
                    if (si < srcWords.length) {{
                        html += '<span class="text-edit-diff-del">' + escapeHtml(srcWords[si]) + '</span> ';
                        si++;
                    }}
                    if (ei < editWords.length) {{
                        html += '<span class="text-edit-diff-ins">' + escapeHtml(editWords[ei]) + '</span> ';
                        ei++;
                    }}
                }}
            }}
            return html;
        }}

        function lcsWords(a, b) {{
            var m = a.length, n = b.length;
            var dp = Array.from({{length: m + 1}}, function() {{ return new Array(n + 1).fill(0); }});
            for (var i = 1; i <= m; i++)
                for (var j = 1; j <= n; j++)
                    dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
            // Backtrack
            var result = [];
            var i = m, j = n;
            while (i > 0 && j > 0) {{
                if (a[i-1] === b[j-1]) {{ result.unshift(a[i-1]); i--; j--; }}
                else if (dp[i-1][j] > dp[i][j-1]) i--;
                else j--;
            }}
            return result;
        }}

        function escapeHtml(str) {{
            var div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }}
    }})();
    </script>
    """

    logger.info(f"Generated text edit layout for {schema_name}")
    return html, []
