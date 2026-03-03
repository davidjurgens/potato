"""
Tests that multiselect generates data-key attributes and preserves label names
in the value attribute (not overwriting with key numbers).
"""

import pytest
import re
from unittest.mock import patch, MagicMock


class TestMultiselectDataKey:
    """Verify multiselect HTML output has data-key and correct value."""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        mock_config = MagicMock()
        mock_config.get.return_value = []
        with patch('potato.server_utils.schemas.multiselect.get_ai_wrapper', return_value=''):
            with patch('potato.server_utils.schemas.multiselect.get_dynamic_ai_help', return_value=''):
                yield mock_config

    def _generate(self, scheme):
        from potato.server_utils.schemas.multiselect import generate_multiselect_layout
        return generate_multiselect_layout(scheme)

    def test_sequential_binding_preserves_label_in_value(self):
        """The value attribute should be the label name, not a number."""
        scheme = {
            "annotation_type": "multiselect",
            "name": "topics",
            "description": "Select topics",
            "sequential_key_binding": True,
            "labels": ["quality", "price", "service"],
        }
        html, keybindings = self._generate(scheme)

        # Value attributes should contain label names
        assert 'value="quality"' in html
        assert 'value="price"' in html
        assert 'value="service"' in html

        # Should NOT contain numeric values (the old bug)
        assert 'value="1"' not in html
        assert 'value="2"' not in html
        assert 'value="3"' not in html

    def test_sequential_binding_adds_data_key(self):
        """Checkboxes should have data-key attributes for JS matching."""
        scheme = {
            "annotation_type": "multiselect",
            "name": "topics",
            "description": "Select topics",
            "sequential_key_binding": True,
            "labels": ["quality", "price", "service"],
        }
        html, keybindings = self._generate(scheme)

        assert 'data-key="1"' in html
        assert 'data-key="2"' in html
        assert 'data-key="3"' in html

    def test_allocated_keys_used_when_present(self):
        """When _allocated_keys is set, those keys are used instead of sequential."""
        scheme = {
            "annotation_type": "multiselect",
            "name": "topics",
            "description": "Select topics",
            "sequential_key_binding": True,
            "labels": ["quality", "price", "service"],
            "_allocated_keys": [
                {"label": "quality", "key": "q"},
                {"label": "price", "key": "w"},
                {"label": "service", "key": "e"},
            ],
        }
        html, keybindings = self._generate(scheme)

        # data-key should be the allocated keys
        assert 'data-key="q"' in html
        assert 'data-key="w"' in html
        assert 'data-key="e"' in html

        # Value should still be label names
        assert 'value="quality"' in html
        assert 'value="price"' in html
        assert 'value="service"' in html

        # Keybindings list should reflect allocated keys
        kb_keys = [k for k, _ in keybindings]
        assert "q" in kb_keys
        assert "w" in kb_keys
        assert "e" in kb_keys

    def test_keybinding_badge_class(self):
        """Badge should use unified keybinding-badge class."""
        scheme = {
            "annotation_type": "multiselect",
            "name": "topics",
            "description": "Select topics",
            "sequential_key_binding": True,
            "labels": ["quality"],
        }
        html, _ = self._generate(scheme)
        assert "keybinding-badge" in html

    def test_no_keybinding_without_sequential(self):
        """Without sequential_key_binding, no data-key attributes."""
        scheme = {
            "annotation_type": "multiselect",
            "name": "topics",
            "description": "Select topics",
            "labels": ["quality", "price"],
        }
        html, keybindings = self._generate(scheme)

        assert 'data-key=' not in html
        assert keybindings == []


class TestRadioDataKey:
    """Verify radio HTML output uses keybinding-badge and data-key."""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        mock_config = MagicMock()
        mock_config.get.return_value = [
            {"annotation_type": "radio", "name": "test"}
        ]
        with patch('potato.server_utils.schemas.radio.config', mock_config):
            with patch('potato.server_utils.schemas.radio.get_ai_wrapper', return_value=''):
                with patch('potato.server_utils.schemas.radio.get_dynamic_ai_help', return_value=''):
                    yield mock_config

    def _generate(self, scheme):
        from potato.server_utils.schemas.radio import generate_radio_layout
        return generate_radio_layout(scheme)

    def test_radio_uses_keybinding_badge(self):
        """Radio should use keybinding-badge class instead of [KEY] text."""
        scheme = {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Sentiment",
            "sequential_key_binding": True,
            "labels": ["positive", "negative"],
        }
        html, _ = self._generate(scheme)

        # Should use badge
        assert "keybinding-badge" in html

        # Should NOT have old [KEY] format
        assert "[1]" not in html
        assert "[2]" not in html

    def test_radio_value_is_label_name(self):
        """Radio value should be label name, not key number."""
        scheme = {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Sentiment",
            "sequential_key_binding": True,
            "labels": ["positive", "negative"],
        }
        html, _ = self._generate(scheme)

        assert 'value="positive"' in html
        assert 'value="negative"' in html

    def test_radio_allocated_keys(self):
        """When _allocated_keys present, radio uses those keys."""
        scheme = {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Sentiment",
            "sequential_key_binding": True,
            "labels": ["positive", "negative"],
            "_allocated_keys": [
                {"label": "positive", "key": "q"},
                {"label": "negative", "key": "w"},
            ],
        }
        html, keybindings = self._generate(scheme)

        assert 'data-key="q"' in html
        assert 'data-key="w"' in html
        kb_keys = [k for k, _ in keybindings]
        assert "q" in kb_keys
        assert "w" in kb_keys
