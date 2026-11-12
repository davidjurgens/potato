"""
Card Sorting / Grouping Layout

Drag items (text snippets, labels, concepts) into predefined or user-created groups.
Open card sorting lets annotators create their own categories; closed card sorting
provides predefined ones.

Research: Spencer (2009) "Card Sorting: Designing Usable Categories"; Nielsen Norman Group.
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


def generate_card_sort_layout(annotation_scheme):
    """
    Generate HTML for a Card Sorting interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - mode: "closed" (predefined groups) or "open" (user-created groups)
            - groups: List of group names (for closed mode)
            - items_field: Field in data containing items to sort
            - allow_empty_groups: Whether empty groups are OK
            - allow_multiple: Whether an item can appear in multiple groups

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_card_sort_layout_internal)


def _generate_card_sort_layout_internal(annotation_scheme):
    schema_name = annotation_scheme['name']
    description = annotation_scheme['description']
    mode = annotation_scheme.get('mode', 'closed')
    groups = annotation_scheme.get('groups', [])
    items_field = annotation_scheme.get('items_field', 'items')
    allow_empty_groups = annotation_scheme.get('allow_empty_groups', True)
    allow_multiple = annotation_scheme.get('allow_multiple', False)

    if mode == 'closed' and not groups:
        raise ValueError(f"card_sort schema '{schema_name}' in closed mode requires 'groups'")

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    config_json = json.dumps({
        'mode': mode,
        'groups': groups,
        'items_field': items_field,
        'allow_empty_groups': allow_empty_groups,
        'allow_multiple': allow_multiple,
    })

    # Build group containers
    # NOTE: group-items div must be self-closing (no whitespace) so CSS :empty works
    groups_html = ""
    for group in groups:
        group_id = escape_html_content(group.replace(' ', '-').lower())
        esc_group = escape_html_content(group)
        esc_schema = escape_html_content(schema_name)
        groups_html += (
            f'<div class="card-sort-group" data-group="{esc_group}" id="{schema_name}-group-{group_id}">'
            f'<div class="card-sort-group-header">'
            f'<span class="card-sort-group-name">{esc_group}</span>'
            f'<span class="card-sort-group-count">0</span>'
            f'</div>'
            f'<div class="card-sort-group-items" tabindex="0" role="group"'
            f' aria-label="{esc_group} group. Press Enter to move the picked-up card here."'
            f' data-drop-group="{esc_group}"'
            f' ondragover="event.preventDefault(); this.classList.add(\'card-sort-drag-over\')"'
            f' ondragleave="this.classList.remove(\'card-sort-drag-over\')"'
            f' ondrop="cardSortDrop(event, \'{esc_schema}\', \'{esc_group}\')"></div>'
            f'</div>'
        )

    new_group_html = ""
    if mode == 'open':
        new_group_html = f"""
            <div class="card-sort-new-group">
                <input type="text" class="card-sort-new-group-input" id="{schema_name}-new-group-input"
                       placeholder="New group name..." onkeydown="if(event.key==='Enter')cardSortAddGroup('{escape_html_content(schema_name)}')">
                <button type="button" class="card-sort-new-group-btn"
                        onclick="cardSortAddGroup('{escape_html_content(schema_name)}')">+ Add Group</button>
            </div>
        """

    html = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form shadcn-card-sort-container"
          action="javascript:void(0)"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="card_sort"
          data-schema-name="{escape_html_content(schema_name)}"
          data-items-field="{escape_html_content(items_field)}"
          {layout_attrs}>
        <fieldset schema_name="{escape_html_content(schema_name)}">
            <legend class="shadcn-card-sort-title">{escape_html_content(description)}</legend>

            <div class="card-sort-layout">
                <div class="card-sort-source" id="{schema_name}-source">
                    <div class="card-sort-source-header">Drag items into groups</div>
                    <p class="card-sort-kbd-hint" id="{schema_name}-kbd-hint">
                        Or use the keyboard: Tab to a card, press Enter to pick it
                        up, then Tab to a group and press Enter to drop it. Press a
                        number key to send a picked-up card straight to that group,
                        or Escape to put it back down.
                    </p>
                    <div class="card-sort-source-items" id="{schema_name}-source-items"
                         tabindex="0" role="group" data-drop-group="__source__"
                         aria-label="Unsorted items. Press Enter to move the picked-up card back here."
                         ondragover="event.preventDefault(); this.classList.add('card-sort-drag-over')"
                         ondragleave="this.classList.remove('card-sort-drag-over')"
                         ondrop="cardSortDrop(event, '{escape_html_content(schema_name)}', '__source__')">
                    </div>
                </div>

                <div class="card-sort-groups" id="{schema_name}-groups">
                    {groups_html}
                </div>
            </div>

            {new_group_html}

            <p class="card-sort-live" id="{schema_name}-live"
               role="status" aria-live="polite"></p>

            <input type="hidden"
                   class="annotation-input card-sort-data-input"
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
        var cardSortConfig = {config_json};

        window.cardSortDrop = function(event, schemaName, groupName) {{
            event.preventDefault();
            event.currentTarget.classList.remove('card-sort-drag-over');

            var cardText = event.dataTransfer.getData('text/plain');
            var sourceGroup = event.dataTransfer.getData('application/x-source-group');
            if (!cardText) return;

            // Remove from source
            if (sourceGroup) {{
                var sourceContainer;
                if (sourceGroup === '__source__') {{
                    sourceContainer = document.getElementById(schemaName + '-source-items');
                }} else {{
                    var groups = document.querySelectorAll('#' + schemaName + '-groups .card-sort-group');
                    groups.forEach(function(g) {{
                        if (g.dataset.group === sourceGroup) sourceContainer = g.querySelector('.card-sort-group-items');
                    }});
                }}
                if (sourceContainer) {{
                    var cards = sourceContainer.querySelectorAll('.card-sort-card');
                    cards.forEach(function(c) {{ if (c.textContent.trim() === cardText) c.remove(); }});
                }}
            }}

            // Add to target
            var targetContainer;
            if (groupName === '__source__') {{
                targetContainer = document.getElementById(schemaName + '-source-items');
            }} else {{
                var groups = document.querySelectorAll('#' + schemaName + '-groups .card-sort-group');
                groups.forEach(function(g) {{
                    if (g.dataset.group === groupName) targetContainer = g.querySelector('.card-sort-group-items');
                }});
            }}

            if (targetContainer) {{
                var card = createCard(cardText, schemaName, groupName);
                targetContainer.appendChild(card);
            }}

            updateGroupCounts(schemaName);
            cardSortSaveData(schemaName);
        }};

        window.cardSortAddGroup = function(schemaName) {{
            var input = document.getElementById(schemaName + '-new-group-input');
            var name = input.value.trim();
            if (!name) return;

            var groupsContainer = document.getElementById(schemaName + '-groups');

            // Check duplicate
            var existing = groupsContainer.querySelectorAll('.card-sort-group');
            for (var i = 0; i < existing.length; i++) {{
                if (existing[i].dataset.group === name) return;
            }}

            var groupDiv = document.createElement('div');
            groupDiv.className = 'card-sort-group';
            groupDiv.dataset.group = name;
            groupDiv.innerHTML = '<div class="card-sort-group-header">' +
                '<span class="card-sort-group-name">' + escapeHtml(name) + '</span>' +
                '<span class="card-sort-group-count">0</span>' +
                '<button type="button" class="card-sort-remove-group" onclick="cardSortRemoveGroup(\\\'' + schemaName + '\\\',this)">&times;</button>' +
                '</div>' +
                '<div class="card-sort-group-items" tabindex="0" role="group" ' + 'data-drop-group="' + escapeHtml(name) + '" ' + 'aria-label="' + escapeHtml(name) + ' group. Press Enter to move the picked-up card here." ' + 'ondragover="event.preventDefault();this.classList.add(\\\'card-sort-drag-over\\\')" ' +
                'ondragleave="this.classList.remove(\\\'card-sort-drag-over\\\')" ' +
                'ondrop="cardSortDrop(event,\\\'' + schemaName + '\\\',\\\'' + name.replace(/'/g, "\\\\'") + '\\\')">' +
                '</div>';
            groupsContainer.appendChild(groupDiv);
            input.value = '';
            // A group added at runtime is a drop target like any other.
            if (typeof window._cardSortBindZones === 'function') {{
                window._cardSortBindZones(schemaName);
            }}
            cardSortSaveData(schemaName);
        }};

        window.cardSortRemoveGroup = function(schemaName, btn) {{
            var group = btn.closest('.card-sort-group');
            // Move cards back to source
            var cards = group.querySelectorAll('.card-sort-card');
            var source = document.getElementById(schemaName + '-source-items');
            cards.forEach(function(c) {{
                c.setAttribute('draggable', 'true');
                source.appendChild(c);
            }});
            group.remove();
            updateGroupCounts(schemaName);
            cardSortSaveData(schemaName);
        }};

        function createCard(text, schemaName, groupName) {{
            var card = document.createElement('div');
            card.className = 'card-sort-card';
            card.textContent = text;
            card.setAttribute('draggable', 'true');

            // HTML5 drag was the only way to do this task: no tabindex, no
            // role, no click-to-assign. A keyboard-only or screen-reader
            // annotator could not sort a single card, and drag-and-drop does
            // not work on touch either. ranking.py is the precedent -- it ships
            // a keyboard equivalent alongside the same drag gesture.
            card.setAttribute('tabindex', '0');
            card.setAttribute('role', 'button');
            card.setAttribute('aria-pressed', 'false');
            card.dataset.cardText = text;
            card.dataset.cardGroup = groupName;
            setCardLabel(card);

            card.addEventListener('dragstart', function(e) {{
                e.dataTransfer.setData('text/plain', text);
                e.dataTransfer.setData('application/x-source-group', groupName);
                card.classList.add('card-sort-dragging');
            }});
            card.addEventListener('dragend', function() {{
                card.classList.remove('card-sort-dragging');
            }});

            // Tap or click picks a card up, which is also the touch path.
            // `detail === 0` marks a click that no pointer produced -- what a
            // screen reader dispatches when it activates a role="button". The
            // keydown handler below already covers that, and letting both run
            // would toggle the card twice.
            card.addEventListener('click', function(e) {{
                if (e.detail === 0) return;
                togglePickUp(schemaName, card);
            }});
            card.addEventListener('keydown', function(e) {{
                if (e.key === 'Enter' || e.key === ' ') {{
                    e.preventDefault();
                    togglePickUp(schemaName, card);
                }} else if (e.key === 'Escape') {{
                    dropPickUp(schemaName);
                }} else if (/^[1-9]$/.test(e.key)) {{
                    var zones = dropZones(schemaName);
                    var zone = zones[parseInt(e.key, 10)];  // 0 is the source list
                    if (zone) {{
                        e.preventDefault();
                        pickUp(schemaName, card);
                        moveTo(schemaName, zone);
                    }}
                }}
            }});
            return card;
        }}

        /* ---------- keyboard / tap sorting ---------------------------------- */

        function groupLabel(name) {{
            return name === '__source__' ? 'the unsorted list' : name;
        }}

        function setCardLabel(card) {{
            var where = groupLabel(card.dataset.cardGroup || '__source__');
            var held = card.getAttribute('aria-pressed') === 'true';
            card.setAttribute('aria-label', card.dataset.cardText + '. In ' + where +
                '. ' + (held ? 'Picked up. Choose a group, or press Escape to put it back.'
                             : 'Press Enter to pick it up.'));
        }}

        /** The source list first, then each group, in the order they appear. */
        function dropZones(schemaName) {{
            var form = document.getElementById(schemaName);
            if (!form) return [];
            return Array.prototype.slice.call(
                form.querySelectorAll('[data-drop-group]'));
        }}

        function announce(schemaName, message) {{
            var live = document.getElementById(schemaName + '-live');
            if (live) live.textContent = message;
        }}

        function heldCard(schemaName) {{
            var form = document.getElementById(schemaName);
            return form ? form.querySelector('.card-sort-card.card-sort-held') : null;
        }}

        function pickUp(schemaName, card) {{
            dropPickUp(schemaName, true);
            card.classList.add('card-sort-held');
            card.setAttribute('aria-pressed', 'true');
            setCardLabel(card);
            var form = document.getElementById(schemaName);
            if (form) form.classList.add('card-sort-holding');
            announce(schemaName, 'Picked up ' + card.dataset.cardText +
                '. Choose a group to move it to.');
        }}

        function dropPickUp(schemaName, quiet) {{
            var held = heldCard(schemaName);
            if (held) {{
                held.classList.remove('card-sort-held');
                held.setAttribute('aria-pressed', 'false');
                setCardLabel(held);
            }}
            var form = document.getElementById(schemaName);
            if (form) form.classList.remove('card-sort-holding');
            if (held && !quiet) announce(schemaName, 'Put ' + held.dataset.cardText + ' back down.');
        }}

        function togglePickUp(schemaName, card) {{
            if (card.classList.contains('card-sort-held')) dropPickUp(schemaName);
            else pickUp(schemaName, card);
        }}

        /** Move the picked-up card into `zone`, keeping focus with the card. */
        function moveTo(schemaName, zone) {{
            var card = heldCard(schemaName);
            if (!card || !zone) return false;
            var target = zone.getAttribute('data-drop-group');
            if (card.dataset.cardGroup === target) {{
                dropPickUp(schemaName);
                return false;
            }}

            var moved = createCard(card.dataset.cardText, schemaName, target);
            card.remove();
            zone.appendChild(moved);
            // Nothing is in the air any more. Without this the dashed "drop it
            // here" borders stayed on every zone for the rest of the item, which
            // makes the one signal that means "choose a target" mean nothing.
            var form = document.getElementById(schemaName);
            if (form) form.classList.remove('card-sort-holding');
            updateGroupCounts(schemaName);
            cardSortSaveData(schemaName);
            moved.focus();
            announce(schemaName, 'Moved ' + moved.dataset.cardText + ' to ' +
                groupLabel(target) + '.');
            return true;
        }}

        /** Enter on a drop zone drops whatever is held into it. */
        window._cardSortBindZones = function(schemaName) {{
            dropZones(schemaName).forEach(function(zone) {{
                if (zone.dataset.cardSortBound) return;
                zone.dataset.cardSortBound = '1';
                zone.addEventListener('keydown', function(e) {{
                    if (e.key !== 'Enter' && e.key !== ' ') return;
                    // Only when the zone itself is focused. A card sits inside a
                    // zone, so the Enter that picks the card up bubbles straight
                    // to its own container -- which then "dropped" it back where
                    // it already was, and the keyboard path did nothing at all.
                    if (e.target !== zone) return;
                    if (!heldCard(schemaName)) return;
                    e.preventDefault();
                    moveTo(schemaName, zone);
                }});
                zone.addEventListener('click', function(e) {{
                    // Only the empty area of the zone; a click on a card is
                    // that card's own pick-up. `detail === 0` is the synthetic
                    // click that follows Enter, already handled by keydown.
                    if (e.detail === 0 || e.target !== zone) return;
                    if (heldCard(schemaName)) moveTo(schemaName, zone);
                }});
            }});
        }};

        function updateGroupCounts(schemaName) {{
            var groups = document.querySelectorAll('#' + schemaName + '-groups .card-sort-group');
            groups.forEach(function(g) {{
                var count = g.querySelectorAll('.card-sort-group-items .card-sort-card').length;
                g.querySelector('.card-sort-group-count').textContent = count;
            }});
        }}

        function cardSortSaveData(schemaName) {{
            var result = {{}};
            var groups = document.querySelectorAll('#' + schemaName + '-groups .card-sort-group');
            groups.forEach(function(g) {{
                var groupName = g.dataset.group;
                var cards = g.querySelectorAll('.card-sort-group-items .card-sort-card');
                result[groupName] = Array.from(cards).map(function(c) {{ return c.textContent.trim(); }});
            }});

            var input = document.getElementById(schemaName).querySelector('.card-sort-data-input');
            input.value = JSON.stringify(result);
            input.setAttribute('data-modified', 'true');
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}

        function escapeHtml(str) {{
            var div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }}

        // Expose for populate/clear
        window._cardSortCreateCard = createCard;
        window._cardSortUpdateCounts = updateGroupCounts;
        window._cardSortSaveData = cardSortSaveData;
    }})();
    </script>
    """

    logger.info(f"Generated card sort layout for {schema_name}")
    return html, []
