"""
Tests for dependency tree annotation functionality.

Dependency tree annotation uses the span_link schema with:
- Directed links between tokens
- Arc labels showing dependency types
- Constraint validation for source/target labels
"""

import pytest
from unittest.mock import MagicMock, patch


class TestDependencyTreeSchema:
    """Test the span_link schema for dependency tree annotation."""

    def test_span_link_generates_html_with_show_labels(self):
        """Test that span_link schema includes show_labels config in HTML."""
        from potato.server_utils.schemas.span_link import generate_span_link_layout

        annotation_scheme = {
            "name": "dependencies",
            "description": "Annotate dependencies",
            "annotation_id": "dep_1",
            "span_schema": "tokens",
            "link_types": [
                {"name": "nsubj", "directed": True, "color": "#dc2626"},
                {"name": "obj", "directed": True, "color": "#22c55e"},
            ],
            "visual_display": {
                "enabled": True,
                "arc_position": "above",
                "show_labels": True,
            },
        }

        html, keybindings = generate_span_link_layout(annotation_scheme)

        # Check that show_labels is included in the data attributes
        assert 'data-show-labels="true"' in html
        assert 'data-arc-position="above"' in html
        assert 'data-show-arcs="true"' in html

    def test_span_link_multi_line_mode_single_line(self):
        """Test that span_link schema includes multi_line_mode for single_line."""
        from potato.server_utils.schemas.span_link import generate_span_link_layout

        annotation_scheme = {
            "name": "dependencies",
            "description": "Annotate dependencies",
            "annotation_id": "dep_1",
            "span_schema": "tokens",
            "link_types": [
                {"name": "nsubj", "directed": True},
            ],
            "visual_display": {
                "enabled": True,
                "multi_line_mode": "single_line",
            },
        }

        html, keybindings = generate_span_link_layout(annotation_scheme)
        assert 'data-multi-line-mode="single_line"' in html

    def test_span_link_multi_line_mode_bracket(self):
        """Test that span_link schema includes multi_line_mode for bracket."""
        from potato.server_utils.schemas.span_link import generate_span_link_layout

        annotation_scheme = {
            "name": "dependencies",
            "description": "Annotate dependencies",
            "annotation_id": "dep_1",
            "span_schema": "tokens",
            "link_types": [
                {"name": "nsubj", "directed": True},
            ],
            "visual_display": {
                "enabled": True,
                "multi_line_mode": "bracket",
            },
        }

        html, keybindings = generate_span_link_layout(annotation_scheme)
        assert 'data-multi-line-mode="bracket"' in html

    def test_span_link_multi_line_mode_default(self):
        """Test that span_link defaults to bracket mode when not specified."""
        from potato.server_utils.schemas.span_link import generate_span_link_layout

        annotation_scheme = {
            "name": "dependencies",
            "description": "Annotate dependencies",
            "annotation_id": "dep_1",
            "span_schema": "tokens",
            "link_types": [
                {"name": "nsubj", "directed": True},
            ],
            "visual_display": {
                "enabled": True,
            },
        }

        html, keybindings = generate_span_link_layout(annotation_scheme)
        assert 'data-multi-line-mode="bracket"' in html

    def test_span_link_generates_directed_link_types(self):
        """Test that directed link types are properly marked."""
        from potato.server_utils.schemas.span_link import generate_span_link_layout

        annotation_scheme = {
            "name": "deps",
            "description": "Dependencies",
            "annotation_id": "dep_1",
            "span_schema": "tokens",
            "link_types": [
                {"name": "nsubj", "directed": True},
                {"name": "conj", "directed": False},
            ],
        }

        html, _ = generate_span_link_layout(annotation_scheme)

        # Check directed attribute is set correctly
        assert 'data-directed="true"' in html
        assert 'data-directed="false"' in html
        # Check direction icons
        assert "→" in html  # Directed arrow
        assert "↔" in html  # Undirected arrow

    def test_span_link_includes_label_constraints(self):
        """Test that source/target label constraints are included."""
        from potato.server_utils.schemas.span_link import generate_span_link_layout

        annotation_scheme = {
            "name": "deps",
            "description": "Dependencies",
            "annotation_id": "dep_1",
            "span_schema": "tokens",
            "link_types": [
                {
                    "name": "det",
                    "directed": True,
                    "allowed_source_labels": ["DET"],
                    "allowed_target_labels": ["NOUN"],
                },
            ],
        }

        html, _ = generate_span_link_layout(annotation_scheme)

        # Check constraint attributes are present
        assert 'data-source-labels="DET"' in html
        assert 'data-target-labels="NOUN"' in html

    def test_span_link_generates_link_type_colors(self):
        """Test that link type colors are properly assigned."""
        from potato.server_utils.schemas.span_link import generate_span_link_layout

        annotation_scheme = {
            "name": "deps",
            "description": "Dependencies",
            "annotation_id": "dep_1",
            "span_schema": "tokens",
            "link_types": [
                {"name": "nsubj", "directed": True, "color": "#dc2626"},
                {"name": "obj", "directed": True, "color": "#22c55e"},
            ],
        }

        html, _ = generate_span_link_layout(annotation_scheme)

        # Check colors are present
        assert "#dc2626" in html
        assert "#22c55e" in html

    def test_span_link_uses_default_colors_when_not_specified(self):
        """Test that default colors are used when not specified."""
        from potato.server_utils.schemas.span_link import (
            generate_span_link_layout,
            LINK_COLOR_PALETTE,
        )

        annotation_scheme = {
            "name": "deps",
            "description": "Dependencies",
            "annotation_id": "dep_1",
            "span_schema": "tokens",
            "link_types": [
                {"name": "nsubj", "directed": True},  # No color specified
                {"name": "obj", "directed": True},
            ],
        }

        html, _ = generate_span_link_layout(annotation_scheme)

        # Check that default palette colors are used
        assert LINK_COLOR_PALETTE[0] in html
        assert LINK_COLOR_PALETTE[1] in html


class TestDependencyTreeArcRendering:
    """Test the arc rendering for dependency trees."""

    def test_render_link_arcs_creates_directed_paths(self):
        """Test that directed links include arrow markers."""
        from potato.server_utils.schemas.span_link import render_link_arcs

        # Create mock link object
        mock_link = MagicMock()
        mock_link.get_span_ids.return_value = ["span_1", "span_2"]
        mock_link.get_properties.return_value = {"color": "#dc2626"}
        mock_link.is_directed.return_value = True
        mock_link.get_id.return_value = "link_1"

        span_positions = {
            "span_1": {"x": 0, "y": 50, "width": 40, "height": 20},
            "span_2": {"x": 100, "y": 50, "width": 40, "height": 20},
        }

        svg = render_link_arcs([mock_link], span_positions)

        # Check that arrow marker is included
        assert 'marker-end="url(#arrowhead)"' in svg
        assert '<marker id="arrowhead"' in svg

    def test_render_link_arcs_creates_quadratic_curves(self):
        """Test that arcs use quadratic Bezier curves."""
        from potato.server_utils.schemas.span_link import render_link_arcs

        mock_link = MagicMock()
        mock_link.get_span_ids.return_value = ["span_1", "span_2"]
        mock_link.get_properties.return_value = {"color": "#dc2626"}
        mock_link.is_directed.return_value = True
        mock_link.get_id.return_value = "link_1"

        span_positions = {
            "span_1": {"x": 0, "y": 50, "width": 40, "height": 20},
            "span_2": {"x": 100, "y": 50, "width": 40, "height": 20},
        }

        svg = render_link_arcs([mock_link], span_positions)

        # Check that quadratic curve (Q command) is used
        assert " Q " in svg

    def test_render_link_arcs_handles_missing_spans(self):
        """Test that rendering handles missing span positions gracefully."""
        from potato.server_utils.schemas.span_link import render_link_arcs

        mock_link = MagicMock()
        mock_link.get_span_ids.return_value = ["span_1", "span_missing"]
        mock_link.get_properties.return_value = {"color": "#dc2626"}
        mock_link.is_directed.return_value = True
        mock_link.get_id.return_value = "link_1"

        span_positions = {
            "span_1": {"x": 0, "y": 50, "width": 40, "height": 20},
            # span_missing is not in positions
        }

        # Should not raise an error
        svg = render_link_arcs([mock_link], span_positions)

        # The path should not be created since one span is missing
        assert 'data-link-id="link_1"' not in svg or "<path" not in svg

    def test_render_link_arcs_empty_links(self):
        """Test that empty links list returns empty SVG."""
        from potato.server_utils.schemas.span_link import render_link_arcs

        svg = render_link_arcs([], {})
        assert svg == ""


class TestDependencyTreeConfig:
    """Test dependency tree configuration loading."""

    def test_config_loads_dependency_tree_example(self):
        """Test that the dependency tree example config loads correctly."""
        import yaml
        import os

        config_path = os.path.join(
            os.path.dirname(__file__),
            "../../examples/span/dependency-tree/config.yaml",
        )

        if not os.path.exists(config_path):
            pytest.skip("Dependency tree example not found")

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        # Verify structure
        assert config["annotation_task_name"] == "Dependency Tree Annotation"
        assert len(config["annotation_schemes"]) == 2

        # Check token schema
        token_schema = config["annotation_schemes"][0]
        assert token_schema["annotation_type"] == "span"
        assert token_schema["name"] == "tokens"
        assert len(token_schema["labels"]) > 0

        # Check dependency schema
        dep_schema = config["annotation_schemes"][1]
        assert dep_schema["annotation_type"] == "span_link"
        assert dep_schema["name"] == "dependencies"
        assert dep_schema["span_schema"] == "tokens"
        assert len(dep_schema["link_types"]) > 0

        # Check visual display settings
        visual = dep_schema["visual_display"]
        assert visual["enabled"] is True
        assert visual["show_labels"] is True
        assert visual["arc_position"] == "above"

    def test_dependency_link_types_have_required_fields(self):
        """Test that dependency link types have required fields."""
        import yaml
        import os

        config_path = os.path.join(
            os.path.dirname(__file__),
            "../../examples/span/dependency-tree/config.yaml",
        )

        if not os.path.exists(config_path):
            pytest.skip("Dependency tree example not found")

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        dep_schema = config["annotation_schemes"][1]
        link_types = dep_schema["link_types"]

        for lt in link_types:
            assert "name" in lt, f"Link type missing name: {lt}"
            assert "directed" in lt, f"Link type missing directed: {lt}"
            # All dependency relations should be directed
            assert lt["directed"] is True, f"Dependency should be directed: {lt['name']}"
