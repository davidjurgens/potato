"""
Ranking / Drag-and-Drop Layout

Generates a draggable list of items that annotators can reorder.
Uses a hidden input to store the rank order.

Research basis:
- Kiritchenko & Mohammad (2017) "Best-Worst Scaling More Reliable than Rating
  Scales" ACL
- Thurstone (1927) "A Law of Comparative Judgment"
"""

import logging

from potato.ai.ai_help_wrapper import get_ai_wrapper
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
    generate_tooltip_html,
)

logger = logging.getLogger(__name__)


def generate_ranking_layout(annotation_scheme):
    """
    Generate HTML for a ranking / drag-and-drop annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - labels: List of items to rank
            - allow_ties: Whether ties are allowed (default false)

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_ranking_layout_internal)


def _generate_ranking_layout_internal(annotation_scheme):
    schema_name = annotation_scheme["name"]
    safe_schema = escape_html_content(schema_name)
    description = annotation_scheme["description"]
    labels = annotation_scheme.get("labels", [])
    allow_ties = annotation_scheme.get("allow_ties", False)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)

    if not labels:
        raise ValueError(f"ranking schema '{schema_name}' requires 'labels'")

    # Normalize labels
    label_names = []
    for lbl in labels:
        if isinstance(lbl, str):
            label_names.append(lbl)
        elif isinstance(lbl, dict) and "name" in lbl:
            label_names.append(lbl["name"])
        else:
            raise ValueError(f"Invalid label format: {lbl}")

    identifiers = generate_element_identifier(schema_name, "rank_order", "hidden")
    initial_order = ",".join(label_names)

    html = f"""
    <form id="{safe_schema}" class="annotation-form ranking shadcn-ranking-container"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="ranking"
          data-schema-name="{safe_schema}"
          {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{safe_schema}">
            <legend class="shadcn-ranking-title">{escape_html_content(description)}</legend>
            <p class="schema-help-text">Drag to reorder, or use the arrow buttons</p>
            <input type="hidden"
                   class="annotation-input ranking-order-input"
                   id="{identifiers['id']}"
                   name="{identifiers['name']}"
                   schema="{identifiers['schema']}"
                   label_name="{identifiers['label_name']}"
                   validation="{validation}"
                   value="{escape_html_content(initial_order)}"
                   data-modified="true">
            <div class="ranking-list" id="ranking-list-{safe_schema}" data-schema="{safe_schema}">
    """

    for i, lbl in enumerate(label_names):
        safe_lbl = escape_html_content(lbl)
        tooltip_html = ""
        if isinstance(labels[i], dict):
            tooltip_html = generate_tooltip_html(labels[i])

        html += f"""
                <div class="ranking-item" draggable="true" data-value="{safe_lbl}" {tooltip_html}>
                    <span class="ranking-handle">&#9776;</span>
                    <span class="ranking-rank">{i + 1}</span>
                    <span class="ranking-label">{safe_lbl}</span>
                    <div class="ranking-buttons">
                        <button type="button" class="ranking-up" title="Move up" aria-label="Move up">&#9650;</button>
                        <button type="button" class="ranking-down" title="Move down" aria-label="Move down">&#9660;</button>
                    </div>
                </div>
        """

    html += f"""
            </div>
        </fieldset>
    </form>
    <script>
    (function() {{
        const schema = "{safe_schema}";
        const list = document.getElementById('ranking-list-' + schema);
        const hiddenInput = list.parentElement.querySelector('.ranking-order-input');

        function updateOrder() {{
            const items = list.querySelectorAll('.ranking-item');
            const order = [];
            items.forEach((item, idx) => {{
                item.querySelector('.ranking-rank').textContent = idx + 1;
                order.push(item.getAttribute('data-value'));
            }});
            hiddenInput.value = order.join(',');
            hiddenInput.setAttribute('data-modified', 'true');
            hiddenInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}

        // Drag and drop
        let draggedItem = null;
        list.addEventListener('dragstart', function(e) {{
            draggedItem = e.target.closest('.ranking-item');
            if (draggedItem) {{
                draggedItem.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            }}
        }});

        list.addEventListener('dragend', function(e) {{
            if (draggedItem) {{
                draggedItem.classList.remove('dragging');
                draggedItem = null;
            }}
            list.querySelectorAll('.ranking-item').forEach(item => {{
                item.classList.remove('drag-over');
            }});
        }});

        list.addEventListener('dragover', function(e) {{
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            const target = e.target.closest('.ranking-item');
            if (target && target !== draggedItem) {{
                const rect = target.getBoundingClientRect();
                const midY = rect.top + rect.height / 2;
                list.querySelectorAll('.ranking-item').forEach(item => item.classList.remove('drag-over'));
                target.classList.add('drag-over');
                if (e.clientY < midY) {{
                    list.insertBefore(draggedItem, target);
                }} else {{
                    list.insertBefore(draggedItem, target.nextSibling);
                }}
            }}
        }});

        list.addEventListener('drop', function(e) {{
            e.preventDefault();
            updateOrder();
        }});

        // Button controls
        list.addEventListener('click', function(e) {{
            const btn = e.target.closest('.ranking-up, .ranking-down');
            if (!btn) return;
            e.preventDefault();
            const item = btn.closest('.ranking-item');
            if (btn.classList.contains('ranking-up') && item.previousElementSibling) {{
                list.insertBefore(item, item.previousElementSibling);
                updateOrder();
            }} else if (btn.classList.contains('ranking-down') && item.nextElementSibling) {{
                list.insertBefore(item.nextElementSibling, item);
                updateOrder();
            }}
        }});

        // Keyboard controls
        list.addEventListener('keydown', function(e) {{
            if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
            const item = document.activeElement.closest('.ranking-item');
            if (!item) return;
            e.preventDefault();
            if (e.key === 'ArrowUp' && item.previousElementSibling) {{
                list.insertBefore(item, item.previousElementSibling);
                updateOrder();
                item.focus();
            }} else if (e.key === 'ArrowDown' && item.nextElementSibling) {{
                list.insertBefore(item.nextElementSibling, item);
                updateOrder();
                item.focus();
            }}
        }});

        updateOrder();
    }})();
    </script>
    """

    key_bindings = []
    logger.info(f"Generated ranking layout for {schema_name} with {len(label_names)} items")
    return html, key_bindings
