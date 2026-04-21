"""
Code Review Schema

GitHub PR review-style annotation with inline diff commenting,
file-level ratings, and overall verdict.

Features:
- Click on diff lines in CodingTraceDisplay to add comments
- Per-comment category (bug, style, suggestion, security, question)
- File-level correctness and quality ratings
- Overall verdict (approve, request_changes, comment_only)
"""

import json
import logging
from typing import Dict, Any, Tuple, List

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
)

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = ["bug", "style", "suggestion", "security", "question"]
DEFAULT_VERDICTS = ["approve", "request_changes", "comment_only"]
DEFAULT_RATING_DIMS = ["correctness", "quality"]


def generate_code_review_layout(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    """Generate HTML for a code review annotation interface.

    Args:
        annotation_scheme: Configuration dict.  Required keys: ``name``,
            ``description``.  Optional: ``comment_categories``,
            ``verdict_options``, ``file_rating_dimensions``.

    Returns:
        ``(html, keybindings)`` tuple.
    """
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]

    categories = annotation_scheme.get("comment_categories", DEFAULT_CATEGORIES)
    verdicts = annotation_scheme.get("verdict_options", DEFAULT_VERDICTS)
    rating_dims = annotation_scheme.get("file_rating_dimensions", DEFAULT_RATING_DIMS)

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    esc_schema = escape_html_content(schema_name)

    config_json = json.dumps({
        "categories": categories,
        "verdicts": verdicts,
        "rating_dims": rating_dims,
    })

    # Build verdict radios
    verdict_html = ""
    for v in verdicts:
        label = v.replace("_", " ").title()
        css = f"cr-verdict-{v}"
        verdict_html += (
            f'<label class="cr-verdict-option {css}">'
            f'<input type="radio" name="cr-verdict-{esc_schema}" value="{escape_html_content(v)}">'
            f' {escape_html_content(label)}'
            f'</label>'
        )

    # Build category options
    cat_options = "".join(
        f'<option value="{escape_html_content(c)}">{escape_html_content(c.title())}</option>'
        for c in categories
    )

    html = f"""
    <form id="{esc_schema}" class="annotation-form code-review-container"
          action="javascript:void(0)"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="code_review"
          data-schema-name="{esc_schema}"
          {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="cr-title">{escape_html_content(description)}</legend>

            <!-- Verdict section -->
            <div class="cr-section">
                <div class="cr-section-label">Verdict</div>
                <div class="cr-verdict-group" id="{esc_schema}-verdicts">
                    {verdict_html}
                </div>
            </div>

            <!-- Comments section -->
            <div class="cr-section">
                <div class="cr-section-label">
                    Comments
                    <button type="button" class="cr-add-comment-btn" id="{esc_schema}-add-comment">+ Add Comment</button>
                </div>
                <div class="cr-comments-list" id="{esc_schema}-comments"></div>
            </div>

            <!-- Comment template (hidden, cloned by JS) -->
            <template id="{esc_schema}-comment-template">
                <div class="cr-comment-card">
                    <div class="cr-comment-header">
                        <select class="cr-comment-category">
                            {cat_options}
                        </select>
                        <input type="text" class="cr-comment-file" placeholder="File path (optional)">
                        <input type="number" class="cr-comment-line" placeholder="Line" min="1" style="width:60px">
                        <button type="button" class="cr-comment-delete" title="Remove">&times;</button>
                    </div>
                    <textarea class="cr-comment-text" rows="2" placeholder="Describe the issue..."></textarea>
                </div>
            </template>

            <!-- File ratings section -->
            <div class="cr-section" id="{esc_schema}-ratings-section" style="display:none">
                <div class="cr-section-label">File Ratings</div>
                <div class="cr-ratings-list" id="{esc_schema}-ratings"></div>
            </div>

            <input type="hidden"
                   class="annotation-input code-review-data-input"
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
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var _state = {{ verdict: '', comments: [], file_ratings: {{}} }};

        function init() {{
            // Check for existing value (persistence)
            var input = document.getElementById(SCHEMA).querySelector('.code-review-data-input');
            if (input && input.value) {{
                try {{
                    _state = JSON.parse(input.value);
                    if (!_state.comments) _state.comments = [];
                    if (!_state.file_ratings) _state.file_ratings = {{}};
                }} catch(e) {{}}
            }}

            restoreState();
            attachHandlers();
            detectFiles();
        }}

        function restoreState() {{
            // Restore verdict
            if (_state.verdict) {{
                var radio = document.querySelector(
                    '#' + SCHEMA + '-verdicts input[value="' + _state.verdict + '"]'
                );
                if (radio) radio.checked = true;
            }}

            // Restore comments
            var commentsContainer = document.getElementById(SCHEMA + '-comments');
            if (commentsContainer) {{
                commentsContainer.innerHTML = '';
                _state.comments.forEach(function(c) {{
                    addCommentCard(c);
                }});
            }}
        }}

        function attachHandlers() {{
            // Verdict radios (with :has() fallback via .cr-checked class)
            document.querySelectorAll('#' + SCHEMA + '-verdicts input[type="radio"]').forEach(function(r) {{
                r.addEventListener('change', function() {{
                    _state.verdict = r.value;
                    // Fallback for browsers without :has() support
                    document.querySelectorAll('#' + SCHEMA + '-verdicts .cr-verdict-option').forEach(function(opt) {{
                        opt.classList.toggle('cr-checked', opt.querySelector('input:checked') !== null);
                    }});
                    saveState();
                }});
            }});

            // Add comment button
            var addBtn = document.getElementById(SCHEMA + '-add-comment');
            if (addBtn) {{
                addBtn.addEventListener('click', function() {{
                    var comment = {{ category: CONFIG.categories[0], file: '', line: null, text: '' }};
                    _state.comments.push(comment);
                    addCommentCard(comment);
                    saveState();
                }});
            }}

            // Listen for diff line clicks from CodingTraceDisplay
            document.addEventListener('click', function(e) {{
                var line = e.target.closest('.ct-diff-line, .ct-code-line');
                if (!line) return;
                var toolCall = line.closest('.ct-tool-call');
                if (!toolCall) return;
                var fileEl = toolCall.querySelector('.ct-file-path');
                var file = fileEl ? fileEl.textContent : '';
                var lineNum = '';
                var numEl = line.querySelector('.ct-line-num');
                if (numEl) lineNum = numEl.textContent;

                var comment = {{ category: CONFIG.categories[0], file: file, line: lineNum ? parseInt(lineNum) : null, text: '' }};
                _state.comments.push(comment);
                addCommentCard(comment);
                saveState();

                // Focus the new comment text
                var cards = document.getElementById(SCHEMA + '-comments').querySelectorAll('.cr-comment-card');
                var lastCard = cards[cards.length - 1];
                if (lastCard) {{
                    var textarea = lastCard.querySelector('.cr-comment-text');
                    if (textarea) textarea.focus();
                }}
            }});
        }}

        function addCommentCard(commentData) {{
            var template = document.getElementById(SCHEMA + '-comment-template');
            var commentsContainer = document.getElementById(SCHEMA + '-comments');
            if (!template || !commentsContainer) return;

            var clone = template.content.cloneNode(true);
            var card = clone.querySelector('.cr-comment-card');
            var idx = commentsContainer.querySelectorAll('.cr-comment-card').length;
            card.setAttribute('data-comment-index', idx);

            // Set values
            var catSel = card.querySelector('.cr-comment-category');
            if (catSel && commentData.category) catSel.value = commentData.category;

            var fileInput = card.querySelector('.cr-comment-file');
            if (fileInput && commentData.file) fileInput.value = commentData.file;

            var lineInput = card.querySelector('.cr-comment-line');
            if (lineInput && commentData.line) lineInput.value = commentData.line;

            var textArea = card.querySelector('.cr-comment-text');
            if (textArea && commentData.text) textArea.value = commentData.text;

            // Attach handlers
            catSel.addEventListener('change', function() {{
                var i = getCardIndex(card);
                if (_state.comments[i]) _state.comments[i].category = catSel.value;
                saveState();
            }});
            fileInput.addEventListener('input', function() {{
                var i = getCardIndex(card);
                if (_state.comments[i]) _state.comments[i].file = fileInput.value;
                saveState();
            }});
            lineInput.addEventListener('input', function() {{
                var i = getCardIndex(card);
                if (_state.comments[i]) _state.comments[i].line = lineInput.value ? parseInt(lineInput.value) : null;
                saveState();
            }});
            textArea.addEventListener('input', function() {{
                var i = getCardIndex(card);
                if (_state.comments[i]) _state.comments[i].text = textArea.value;
                saveState();
            }});

            var deleteBtn = card.querySelector('.cr-comment-delete');
            deleteBtn.addEventListener('click', function() {{
                var i = getCardIndex(card);
                _state.comments.splice(i, 1);
                card.remove();
                reindexCards();
                saveState();
            }});

            commentsContainer.appendChild(clone);
        }}

        function getCardIndex(card) {{
            return parseInt(card.getAttribute('data-comment-index'), 10);
        }}

        function reindexCards() {{
            var container = document.getElementById(SCHEMA + '-comments');
            if (!container) return;
            container.querySelectorAll('.cr-comment-card').forEach(function(card, i) {{
                card.setAttribute('data-comment-index', i);
            }});
        }}

        function detectFiles() {{
            // Auto-detect files from CodingTraceDisplay
            var files = new Set();
            document.querySelectorAll('.ct-file-path').forEach(function(el) {{
                if (el.textContent) files.add(el.textContent.trim());
            }});
            if (files.size === 0) return;

            var ratingsSection = document.getElementById(SCHEMA + '-ratings-section');
            var ratingsContainer = document.getElementById(SCHEMA + '-ratings');
            if (!ratingsSection || !ratingsContainer) return;

            ratingsSection.style.display = 'block';
            ratingsContainer.innerHTML = '';

            files.forEach(function(file) {{
                var row = document.createElement('div');
                row.className = 'cr-rating-row';
                var dims = '';
                CONFIG.rating_dims.forEach(function(dim) {{
                    var existing = (_state.file_ratings[file] || {{}})[dim] || 0;
                    dims += '<div class="cr-rating-dim">' +
                        '<span class="cr-dim-label">' + dim + ':</span>';
                    for (var i = 1; i <= 5; i++) {{
                        var sel = (existing === i) ? ' selected' : '';
                        dims += '<button type="button" class="cr-star' + sel + '" data-file="' +
                            escapeAttr(file) + '" data-dim="' + dim + '" data-val="' + i + '">' + i + '</button>';
                    }}
                    dims += '</div>';
                }});
                row.innerHTML = '<div class="cr-rating-file">' + escapeHtml(file) + '</div>' + dims;
                ratingsContainer.appendChild(row);
            }});

            ratingsContainer.querySelectorAll('.cr-star').forEach(function(btn) {{
                btn.addEventListener('click', function() {{
                    var file = btn.getAttribute('data-file');
                    var dim = btn.getAttribute('data-dim');
                    var val = parseInt(btn.getAttribute('data-val'), 10);
                    if (!_state.file_ratings[file]) _state.file_ratings[file] = {{}};
                    _state.file_ratings[file][dim] = val;

                    // Update visual
                    var siblings = ratingsContainer.querySelectorAll(
                        '.cr-star[data-file="' + escapeAttr(file) + '"][data-dim="' + dim + '"]'
                    );
                    siblings.forEach(function(s) {{
                        var sv = parseInt(s.getAttribute('data-val'), 10);
                        if (sv <= val) s.classList.add('selected');
                        else s.classList.remove('selected');
                    }});
                    saveState();
                }});
            }});
        }}

        function saveState() {{
            var data = JSON.stringify(_state);
            var input = document.getElementById(SCHEMA).querySelector('.code-review-data-input');
            if (input) {{
                input.value = data;
                input.setAttribute('data-modified', 'true');
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function escapeHtml(t) {{ var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }}
        function escapeAttr(t) {{ return t.replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }}

        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', init);
        }} else {{
            init();
        }}
        document.addEventListener('instanceChanged', init);
    }})();
    </script>

    <style>
    .code-review-container {{ font-family: inherit; }}
    .cr-title {{ font-weight: 600; font-size: 1em; margin-bottom: 4px; }}
    .cr-section {{ margin-bottom: 12px; }}
    .cr-section-label {{
        font-size: 0.85em; font-weight: 600; color: var(--muted-foreground, #71717a);
        margin-bottom: 6px; display: flex; align-items: center; gap: 8px;
    }}
    .cr-verdict-group {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .cr-verdict-option {{
        padding: 6px 12px; border: 1px solid var(--border, #e4e4e7);
        border-radius: var(--radius, 0.5rem);
        cursor: pointer; font-size: 0.9em; transition: all 0.15s;
    }}
    .cr-verdict-option:hover {{ border-color: #999; }}
    .cr-verdict-option input {{ margin-right: 4px; }}
    /* :has() with JS fallback class .cr-checked */
    .cr-verdict-option:has(input:checked),
    .cr-verdict-option.cr-checked {{
        border-color: var(--primary, #6e56cf); background: color-mix(in srgb, var(--primary, #6e56cf) 8%, transparent);
    }}
    .cr-verdict-approve:has(input:checked),
    .cr-verdict-approve.cr-checked {{
        border-color: #388e3c; background: #e8f5e9;
    }}
    .cr-verdict-request_changes:has(input:checked),
    .cr-verdict-request_changes.cr-checked {{
        border-color: #d32f2f; background: #ffebee;
    }}
    .cr-verdict-option:focus-within {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 2px; }}
    .cr-add-comment-btn {{
        padding: 2px 8px; font-size: 0.85em; border: 1px solid var(--border, #e4e4e7);
        border-radius: 4px; background: var(--card, #fff); cursor: pointer;
        color: var(--primary, #6e56cf);
    }}
    .cr-add-comment-btn:hover {{ background: var(--secondary, #f4f4f5); }}
    .cr-add-comment-btn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 2px; }}
    .cr-comments-list {{ display: flex; flex-direction: column; gap: 6px; }}
    .cr-comment-card {{
        border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem); padding: 8px;
        background: var(--card, #fff);
    }}
    .cr-comment-header {{
        display: flex; gap: 6px; align-items: center; margin-bottom: 4px;
    }}
    .cr-comment-category {{
        padding: 2px 6px; border: 1px solid var(--border, #e4e4e7); border-radius: 4px;
        font-size: 0.85em;
    }}
    .cr-comment-file {{
        flex: 1; padding: 2px 6px; border: 1px solid var(--border, #e4e4e7); border-radius: 4px;
        font-size: 0.85em; font-family: var(--font-mono, monospace);
    }}
    .cr-comment-line {{
        padding: 2px 6px; border: 1px solid var(--border, #e4e4e7); border-radius: 4px;
        font-size: 0.85em;
    }}
    .cr-comment-delete {{
        background: none; border: none; cursor: pointer; color: var(--muted-foreground, #71717a);
        font-size: 1.2em; padding: 0 4px; line-height: 1;
    }}
    .cr-comment-delete:hover {{ color: var(--destructive, #ef4444); }}
    .cr-comment-text {{
        width: 100%; padding: 4px 6px; border: 1px solid var(--border, #e4e4e7);
        border-radius: 4px; font-size: 0.85em; resize: vertical;
        box-sizing: border-box;
    }}
    .cr-comment-text:focus, .cr-comment-file:focus, .cr-comment-line:focus, .cr-comment-category:focus {{
        outline: 2px solid var(--ring, #6e56cf); outline-offset: -1px;
    }}
    .cr-rating-row {{
        padding: 6px 0; border-bottom: 1px solid var(--secondary, #f4f4f5);
    }}
    .cr-rating-file {{
        font-family: var(--font-mono, monospace); font-size: 0.85em;
        color: var(--muted-foreground, #71717a); margin-bottom: 4px;
    }}
    .cr-rating-dim {{
        display: inline-flex; align-items: center; gap: 2px; margin-right: 12px;
    }}
    .cr-dim-label {{ font-size: 0.8em; color: var(--muted-foreground, #71717a); margin-right: 4px; }}
    .cr-star {{
        width: 24px; height: 24px; border: 1px solid var(--border, #e4e4e7); border-radius: 4px;
        background: var(--card, #fff); cursor: pointer; font-size: 0.8em; padding: 0;
        transition: all 0.1s;
    }}
    .cr-star:hover {{ border-color: #ffa726; }}
    .cr-star:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 2px; }}
    .cr-star.selected {{ background: #ffa726; color: #fff; border-color: #ffa726; }}
    </style>
    """

    logger.info(
        f"Successfully generated code_review layout for {schema_name} "
        f"({len(categories)} categories, {len(verdicts)} verdicts)"
    )
    return html, []  # No keybindings
