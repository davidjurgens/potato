"""
Tree Annotation Layout

Generates annotation interface for conversation tree structures.
Supports per-node annotation, path selection, and branch comparison.

Users can:
- Annotate individual nodes (e.g., rate each response)
- Select preferred paths through the tree
- Compare branches at decision points
"""

import json
import logging
from .identifier_utils import (
    safe_generate_layout,
    escape_html_content,
)

logger = logging.getLogger(__name__)


def _generate_tree_annotation_layout_internal(annotation_scheme, horizontal=False):
    """
    Internal function to generate tree annotation layout.

    Args:
        annotation_scheme: Configuration dictionary containing:
            - name: Schema identifier
            - description: Description shown to user
            - node_scheme: Annotation scheme config for per-node annotation
                (e.g., {annotation_type: "likert", size: 5, ...})
            - path_selection:
                - enabled: Whether path selection is enabled
                - description: Instruction text for path selection
            - branch_comparison:
                - enabled: Whether branch comparison is enabled

    Returns:
        tuple: (HTML string, key bindings list)
    """
    scheme_name = annotation_scheme["name"]
    description = annotation_scheme.get("description", "Annotate the conversation tree")
    node_scheme = annotation_scheme.get("node_scheme", {})
    path_selection = annotation_scheme.get("path_selection", {})
    branch_comparison = annotation_scheme.get("branch_comparison", {})

    path_enabled = path_selection.get("enabled", False)
    path_desc = path_selection.get("description", "Select the best response path")
    branch_enabled = branch_comparison.get("enabled", False)

    config_data = json.dumps({
        "schemaName": scheme_name,
        "nodeScheme": node_scheme,
        "pathSelection": {
            "enabled": path_enabled,
            "description": path_desc,
        },
        "branchComparison": {
            "enabled": branch_enabled,
        },
    })

    # Path selection section
    path_section = ""
    if path_enabled:
        path_section = f"""
        <div class="tree-ann-path-selection">
            <h5 class="tree-ann-section-title">Path Selection</h5>
            <p class="tree-ann-path-desc">{escape_html_content(path_desc)}</p>
            <div class="tree-ann-selected-path" id="{escape_html_content(scheme_name)}_selected_path">
                <span class="tree-ann-no-path">No path selected. Click on nodes in the tree to build a path.</span>
            </div>
            <button type="button" class="tree-ann-btn tree-ann-clear-path"
                    id="{escape_html_content(scheme_name)}_clear_path">Clear Path</button>
        </div>
        """

    # Node annotation mode description
    node_ann_desc = ""
    if node_scheme:
        node_type = node_scheme.get("annotation_type", "")
        node_ann_desc = f"""
        <div class="tree-ann-node-mode">
            <p class="tree-ann-hint">Click a node in the tree above to annotate it.
            Node annotation type: <strong>{escape_html_content(node_type)}</strong></p>
        </div>
        """

    schematic = f"""
    <div id="{escape_html_content(scheme_name)}" class="tree-ann-container annotation-form"
         data-annotation-type="tree_annotation"
         data-annotation-id="{annotation_scheme.get('annotation_id', scheme_name)}"
         data-tree-ann-config='{escape_html_content(config_data)}'>

        <div class="tree-ann-header">
            <h4 class="tree-ann-title">{escape_html_content(description)}</h4>
        </div>

        {node_ann_desc}

        <!-- Node Annotation Panel (shown when a node is selected) -->
        <div class="tree-ann-node-panel" id="{escape_html_content(scheme_name)}_node_panel"
             style="display:none">
            <div class="tree-ann-node-panel-header">
                <span class="tree-ann-node-panel-title">Annotating node: <strong id="{escape_html_content(scheme_name)}_active_node"></strong></span>
                <button type="button" class="tree-ann-btn tree-ann-close-panel"
                        id="{escape_html_content(scheme_name)}_close_panel">&times;</button>
            </div>
            <div class="tree-ann-node-panel-body" id="{escape_html_content(scheme_name)}_node_panel_body">
            </div>
        </div>

        {path_section}

        <!-- Hidden inputs for form submission -->
        <input type="hidden" name="{escape_html_content(scheme_name)}:::node_annotations"
               id="{escape_html_content(scheme_name)}_node_annotations" value="{{}}">
        <input type="hidden" name="{escape_html_content(scheme_name)}:::selected_path"
               id="{escape_html_content(scheme_name)}_selected_path_data" value="[]">
    </div>
    """

    key_bindings = []
    return schematic, key_bindings


def generate_tree_annotation_layout(annotation_scheme, horizontal=False):
    """
    Generate tree annotation layout HTML.

    Args:
        annotation_scheme (dict): The annotation scheme configuration
        horizontal (bool): Whether to display horizontally

    Returns:
        tuple: (HTML string, key bindings list)
    """
    return safe_generate_layout(
        annotation_scheme, _generate_tree_annotation_layout_internal, horizontal
    )
