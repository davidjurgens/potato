"""
Tests for tree annotation schema.
"""

import pytest


class TestTreeAnnotationRegistration:
    def test_registered_in_schema_registry(self):
        from potato.server_utils.schemas.registry import schema_registry
        assert schema_registry.is_registered("tree_annotation")

    def test_schema_metadata(self):
        from potato.server_utils.schemas.registry import schema_registry
        schema = schema_registry.get("tree_annotation")
        assert schema is not None
        assert "name" in schema.required_fields
        assert "description" in schema.required_fields
        assert schema.supports_keybindings is False


class TestTreeAnnotationLayout:
    def test_basic_generation(self):
        from potato.server_utils.schemas.tree_annotation import generate_tree_annotation_layout
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "tree_eval",
            "description": "Evaluate responses in the tree",
        }
        html, keybindings = generate_tree_annotation_layout(scheme)
        assert "tree-ann-container" in html
        assert "tree_eval" in html
        assert keybindings == []

    def test_with_path_selection(self):
        from potato.server_utils.schemas.tree_annotation import generate_tree_annotation_layout
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "tree_eval",
            "description": "Evaluate",
            "path_selection": {
                "enabled": True,
                "description": "Select the best response path",
            }
        }
        html, _ = generate_tree_annotation_layout(scheme)
        assert "tree-ann-path-selection" in html
        assert "Select the best response path" in html
        assert "tree_eval_clear_path" in html

    def test_without_path_selection(self):
        from potato.server_utils.schemas.tree_annotation import generate_tree_annotation_layout
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "tree_eval",
            "description": "Evaluate",
        }
        html, _ = generate_tree_annotation_layout(scheme)
        assert "tree-ann-path-selection" not in html

    def test_with_node_scheme(self):
        from potato.server_utils.schemas.tree_annotation import generate_tree_annotation_layout
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "tree_eval",
            "description": "Rate each node",
            "node_scheme": {
                "annotation_type": "likert",
                "size": 5,
                "min_label": "Poor",
                "max_label": "Excellent",
            }
        }
        html, _ = generate_tree_annotation_layout(scheme)
        assert "likert" in html
        assert "tree-ann-node-mode" in html

    def test_hidden_inputs(self):
        from potato.server_utils.schemas.tree_annotation import generate_tree_annotation_layout
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "tree_eval",
            "description": "Evaluate",
        }
        html, _ = generate_tree_annotation_layout(scheme)
        assert 'name="tree_eval:::node_annotations"' in html
        assert 'name="tree_eval:::selected_path"' in html

    def test_generate_via_registry(self):
        from potato.server_utils.schemas.registry import schema_registry
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "tree_eval",
            "description": "Evaluate tree",
        }
        html, _ = schema_registry.generate(scheme)
        assert "tree-ann-container" in html

    def test_node_panel_present(self):
        from potato.server_utils.schemas.tree_annotation import generate_tree_annotation_layout
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "tree_eval",
            "description": "Evaluate",
        }
        html, _ = generate_tree_annotation_layout(scheme)
        assert "tree-ann-node-panel" in html
        assert "tree_eval_node_panel" in html
