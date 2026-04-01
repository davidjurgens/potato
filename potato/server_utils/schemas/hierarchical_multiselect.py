"""
Hierarchical Multi-Label Selection Layout

Generates an expandable/collapsible tree of checkboxes for hierarchical
taxonomy labeling. Stores selections as a hidden input with comma-separated values.

Research basis:
- Silla & Freitas (2011) "A Survey of Hierarchical Classification Across Different
  Application Domains" Data Mining and Knowledge Discovery
- Vens et al. (2008) "Decision Trees for Hierarchical Multi-label Classification"
  Machine Learning
"""

import json
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


def generate_hierarchical_multiselect_layout(annotation_scheme):
    """
    Generate HTML for a hierarchical multi-label selection interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - taxonomy: Nested dict/list defining the hierarchy
            - auto_select_children: Auto-select children when parent selected (default false)
            - auto_select_parent: Auto-select parent when all children selected (default false)
            - show_search: Show search/filter box (default false)
            - max_selections: Maximum number of selections (null = unlimited)

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_hierarchical_multiselect_layout_internal)


def _build_tree_html(taxonomy, schema_name, prefix="", depth=0):
    """Recursively build tree HTML from taxonomy dict/list."""
    html = ""
    safe_schema = escape_html_content(schema_name)

    if isinstance(taxonomy, dict):
        for key, children in taxonomy.items():
            safe_key = escape_html_content(key)
            node_id = f"{prefix}{key}".replace(" ", "_")
            safe_node_id = escape_html_content(node_id)
            has_children = bool(children)
            toggle = '<span class="hier-toggle">&#9654;</span>' if has_children else '<span class="hier-toggle-placeholder"></span>'

            html += f"""
            <div class="hier-node" data-depth="{depth}" data-node-id="{safe_node_id}">
                <div class="hier-node-row">
                    {toggle}
                    <label class="hier-checkbox-label">
                        <input type="checkbox"
                               class="hier-checkbox"
                               data-hier-schema="{safe_schema}"
                               data-hier-value="{safe_key}"
                               data-hier-node="{safe_node_id}"
                               data-hier-depth="{depth}"
                               value="{safe_key}">
                        <span class="hier-label-text">{safe_key}</span>
                    </label>
                </div>
            """
            if has_children:
                html += f'<div class="hier-children" style="display:none;">'
                html += _build_tree_html(children, schema_name, prefix=f"{node_id}.", depth=depth + 1)
                html += "</div>"
            html += "</div>"

    elif isinstance(taxonomy, list):
        for item in taxonomy:
            safe_item = escape_html_content(str(item))
            node_id = f"{prefix}{item}".replace(" ", "_")
            safe_node_id = escape_html_content(node_id)

            html += f"""
            <div class="hier-node hier-leaf" data-depth="{depth}" data-node-id="{safe_node_id}">
                <div class="hier-node-row">
                    <span class="hier-toggle-placeholder"></span>
                    <label class="hier-checkbox-label">
                        <input type="checkbox"
                               class="hier-checkbox"
                               data-hier-schema="{safe_schema}"
                               data-hier-value="{safe_item}"
                               data-hier-node="{safe_node_id}"
                               data-hier-depth="{depth}"
                               value="{safe_item}">
                        <span class="hier-label-text">{safe_item}</span>
                    </label>
                </div>
            </div>
            """

    return html


def _generate_hierarchical_multiselect_layout_internal(annotation_scheme):
    schema_name = annotation_scheme["name"]
    safe_schema = escape_html_content(schema_name)
    description = annotation_scheme["description"]
    taxonomy = annotation_scheme.get("taxonomy", {})
    auto_select_children = annotation_scheme.get("auto_select_children", False)
    auto_select_parent = annotation_scheme.get("auto_select_parent", False)
    show_search = annotation_scheme.get("show_search", False)
    max_selections = annotation_scheme.get("max_selections", None)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)

    if not taxonomy:
        raise ValueError(f"hierarchical_multiselect schema '{schema_name}' requires 'taxonomy'")

    identifiers = generate_element_identifier(schema_name, "selected_labels", "hidden")

    html = f"""
    <form id="{safe_schema}" class="annotation-form hierarchical_multiselect shadcn-hierarchical-multiselect-container"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="hierarchical_multiselect"
          data-schema-name="{safe_schema}"
          {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{safe_schema}">
            <legend class="shadcn-hierarchical-title">{escape_html_content(description)}</legend>
            <input type="hidden"
                   class="annotation-input hier-selected-input"
                   id="{identifiers['id']}"
                   name="{identifiers['name']}"
                   schema="{identifiers['schema']}"
                   label_name="{identifiers['label_name']}"
                   validation="{validation}"
                   value="">
    """

    if show_search:
        html += f"""
            <div class="hier-search-box">
                <input type="text" class="hier-search-input"
                       id="hier-search-{safe_schema}"
                       placeholder="Search labels..."
                       autocomplete="off">
            </div>
        """

    html += f"""
            <div class="hier-selected-tags" id="hier-tags-{safe_schema}"></div>
            <div class="hier-tree" id="hier-tree-{safe_schema}"
                 data-auto-children="{str(auto_select_children).lower()}"
                 data-auto-parent="{str(auto_select_parent).lower()}"
                 data-max-selections="{max_selections if max_selections else ''}">
    """

    html += _build_tree_html(taxonomy, schema_name)

    html += f"""
            </div>
        </fieldset>
    </form>
    <script>
    (function() {{
        const schema = "{safe_schema}";
        const tree = document.getElementById('hier-tree-' + schema);
        const hiddenInput = tree.parentElement.querySelector('.hier-selected-input');
        const tagsContainer = document.getElementById('hier-tags-' + schema);
        const autoChildren = tree.getAttribute('data-auto-children') === 'true';
        const autoParent = tree.getAttribute('data-auto-parent') === 'true';
        const maxSel = tree.getAttribute('data-max-selections');
        const maxSelections = maxSel ? parseInt(maxSel) : null;

        // Toggle expand/collapse
        tree.addEventListener('click', function(e) {{
            const toggle = e.target.closest('.hier-toggle');
            if (toggle) {{
                const node = toggle.closest('.hier-node');
                const children = node.querySelector('.hier-children');
                if (children) {{
                    const isOpen = children.style.display !== 'none';
                    children.style.display = isOpen ? 'none' : 'block';
                    toggle.innerHTML = isOpen ? '&#9654;' : '&#9660;';
                }}
                return;
            }}
        }});

        function getSelected() {{
            const checked = tree.querySelectorAll('.hier-checkbox:checked');
            return Array.from(checked).map(cb => cb.value);
        }}

        function updateHidden() {{
            const selected = getSelected();
            hiddenInput.value = selected.join(',');
            hiddenInput.setAttribute('data-modified', 'true');
            hiddenInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            updateTags(selected);
        }}

        function updateTags(selected) {{
            if (!tagsContainer) return;
            tagsContainer.innerHTML = selected.map(s =>
                '<span class="hier-tag">' + s + '</span>'
            ).join('');
        }}

        // Checkbox change handling
        tree.addEventListener('change', function(e) {{
            const cb = e.target.closest('.hier-checkbox');
            if (!cb) return;

            // Max selections enforcement
            if (maxSelections && cb.checked) {{
                const currentCount = getSelected().length;
                if (currentCount > maxSelections) {{
                    cb.checked = false;
                    return;
                }}
            }}

            // Auto-select children when parent is checked (only if config enabled)
            if (autoChildren && cb.checked) {{
                const node = cb.closest('.hier-node');
                const childCbs = node.querySelectorAll('.hier-children .hier-checkbox');
                childCbs.forEach(child => {{ child.checked = true; }});
            }}

            // Always deselect children when parent is unchecked
            if (!cb.checked) {{
                const node = cb.closest('.hier-node');
                const childCbs = node.querySelectorAll('.hier-children .hier-checkbox');
                childCbs.forEach(child => {{ child.checked = false; }});
            }}

            // Always select ancestor chain when a node is checked
            if (cb.checked) {{
                let parentChildren = cb.closest('.hier-children');
                while (parentChildren) {{
                    const parentNode = parentChildren.closest('.hier-node');
                    if (!parentNode) break;
                    const parentCb = parentNode.querySelector(':scope > .hier-node-row .hier-checkbox');
                    if (parentCb) parentCb.checked = true;
                    parentChildren = parentNode.parentElement.closest('.hier-children');
                }}
            }}

            // When unchecking, also uncheck parent if autoParent mode and no siblings remain
            if (autoParent && !cb.checked) {{
                const parentChildren = cb.closest('.hier-children');
                if (parentChildren) {{
                    const parentNode = parentChildren.closest('.hier-node');
                    const parentCb = parentNode.querySelector(':scope > .hier-node-row .hier-checkbox');
                    const siblings = parentChildren.querySelectorAll(':scope > .hier-node > .hier-node-row .hier-checkbox');
                    const anyChecked = Array.from(siblings).some(s => s.checked);
                    if (parentCb && !anyChecked) parentCb.checked = false;
                }}
            }}

            updateHidden();
        }});

        // Search
        const searchInput = document.getElementById('hier-search-' + schema);
        if (searchInput) {{
            searchInput.addEventListener('input', function() {{
                const query = this.value.toLowerCase();
                const nodes = tree.querySelectorAll('.hier-node');
                nodes.forEach(node => {{
                    const label = node.querySelector('.hier-label-text');
                    if (label) {{
                        const matches = label.textContent.toLowerCase().includes(query);
                        node.style.display = (query === '' || matches) ? '' : 'none';
                        // Expand parents if match found
                        if (matches && query) {{
                            let parent = node.parentElement;
                            while (parent && parent !== tree) {{
                                if (parent.classList.contains('hier-children')) {{
                                    parent.style.display = 'block';
                                    const parentToggle = parent.previousElementSibling;
                                    if (parentToggle) {{
                                        const toggle = parentToggle.querySelector('.hier-toggle');
                                        if (toggle) toggle.innerHTML = '&#9660;';
                                    }}
                                }}
                                parent = parent.parentElement;
                            }}
                        }}
                    }}
                }});
            }});
        }}

        // On init: if hidden input has a server-restored value, check matching boxes
        var serverVal = hiddenInput.getAttribute('value') || hiddenInput.value;
        if (serverVal && serverVal.trim()) {{
            var labels = serverVal.split(',').map(function(s) {{ return s.trim(); }}).filter(Boolean);
            tree.querySelectorAll('.hier-checkbox').forEach(function(cb) {{
                cb.checked = labels.indexOf(cb.value) >= 0;
            }});
            // Expand parents of checked nodes
            tree.querySelectorAll('.hier-checkbox:checked').forEach(function(cb) {{
                var parent = cb.closest('.hier-children');
                while (parent) {{
                    parent.style.display = 'block';
                    var parentNode = parent.closest('.hier-node');
                    if (parentNode) {{
                        var tog = parentNode.querySelector(':scope > .hier-node-row .hier-toggle');
                        if (tog) tog.innerHTML = '&#9660;';
                    }}
                    var grandparent = parentNode ? parentNode.parentElement : null;
                    parent = grandparent ? grandparent.closest('.hier-children') : null;
                }}
            }});
            updateTags(labels);
        }} else {{
            updateHidden();
        }}
    }})();
    </script>
    """

    key_bindings = []
    logger.info(f"Generated hierarchical_multiselect layout for {schema_name}")
    return html, key_bindings
