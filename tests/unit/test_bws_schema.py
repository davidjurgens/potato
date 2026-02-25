"""Unit tests for BWS schema HTML generator."""

import pytest
from potato.server_utils.schemas.bws import generate_bws_layout


def make_bws_scheme(**overrides):
    """Create a basic BWS annotation scheme dict."""
    scheme = {
        "annotation_type": "bws",
        "name": "test_bws",
        "description": "Test BWS Schema",
        "best_description": "Which is BEST?",
        "worst_description": "Which is WORST?",
        "tuple_size": 4,
        "sequential_key_binding": True,
    }
    scheme.update(overrides)
    return scheme


class TestBwsSchema:
    """Tests for BWS schema HTML generation."""

    def test_generates_html(self):
        """Produces valid HTML string."""
        scheme = make_bws_scheme()
        html, keybindings = generate_bws_layout(scheme)
        assert isinstance(html, str)
        assert len(html) > 0
        assert "<form" in html
        assert "bws" in html

    def test_has_best_and_worst_hidden_inputs(self):
        """Two annotation-input elements with label_name best and worst."""
        scheme = make_bws_scheme()
        html, _ = generate_bws_layout(scheme)
        assert 'label_name="best"' in html
        assert 'label_name="worst"' in html
        assert html.count('class="bws-value annotation-input"') == 2

    def test_schema_attribute(self):
        """Inputs have correct schema attribute."""
        scheme = make_bws_scheme(name="my_schema")
        html, _ = generate_bws_layout(scheme)
        assert 'schema="my_schema"' in html

    def test_tiles_match_tuple_size(self):
        """Generates correct number of tiles for given tuple_size."""
        scheme = make_bws_scheme(tuple_size=3)
        html, _ = generate_bws_layout(scheme)
        # 3 best tiles + 3 worst tiles = 6 total
        assert html.count("bws-best-tile") == 3
        assert html.count("bws-worst-tile") == 3

        scheme = make_bws_scheme(tuple_size=5)
        html, _ = generate_bws_layout(scheme)
        assert html.count("bws-best-tile") == 5
        assert html.count("bws-worst-tile") == 5

    def test_keyboard_shortcuts(self):
        """Keybindings list has entries for best (numbers) and worst (letters)."""
        scheme = make_bws_scheme(tuple_size=4)
        _, keybindings = generate_bws_layout(scheme)

        keys = [kb[0] for kb in keybindings]
        # 4 best keys (1-4) + 4 worst keys (a-d) = 8 total
        assert len(keybindings) == 8
        assert "1" in keys
        assert "2" in keys
        assert "3" in keys
        assert "4" in keys
        assert "a" in keys
        assert "b" in keys
        assert "c" in keys
        assert "d" in keys

    def test_no_keybindings_when_disabled(self):
        """No keybindings when sequential_key_binding is false."""
        scheme = make_bws_scheme(sequential_key_binding=False)
        _, keybindings = generate_bws_layout(scheme)
        assert len(keybindings) == 0

    def test_custom_descriptions(self):
        """best_description and worst_description appear in output."""
        scheme = make_bws_scheme(
            best_description="Pick the most intense",
            worst_description="Pick the least intense",
        )
        html, _ = generate_bws_layout(scheme)
        assert "Pick the most intense" in html
        assert "Pick the least intense" in html

    def test_registered_in_registry(self):
        """'bws' is in schema_registry supported types."""
        from potato.server_utils.schemas.registry import schema_registry
        assert "bws" in schema_registry.get_supported_types()

    def test_in_valid_types(self):
        """'bws' is in config_module valid_types."""
        from potato.server_utils.config_module import validate_single_annotation_scheme
        # Should not raise for a valid BWS scheme
        scheme = make_bws_scheme()
        validate_single_annotation_scheme(scheme, "test")

    def test_data_annotation_type_attribute(self):
        """Form has data-annotation-type='bws'."""
        scheme = make_bws_scheme()
        html, _ = generate_bws_layout(scheme)
        assert 'data-annotation-type="bws"' in html

    def test_items_display_placeholder(self):
        """Has BWS items display div for JS population."""
        scheme = make_bws_scheme()
        html, _ = generate_bws_layout(scheme)
        assert "bws-items-display" in html

    def test_validation_error_div(self):
        """Has validation error div."""
        scheme = make_bws_scheme()
        html, _ = generate_bws_layout(scheme)
        assert "bws-validation-error" in html
