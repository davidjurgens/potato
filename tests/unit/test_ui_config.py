"""
Unit tests for UI configuration functionality.
"""

import pytest
from unittest.mock import patch, MagicMock
from potato.flask_server import render_page_with_annotations_WEIRD


class TestUIConfig:
    """Test UI configuration functionality."""

    def test_ui_config_passed_to_template(self):
        """Test that UI configuration is properly passed to the template."""
        # Mock the necessary dependencies
        with patch('potato.flask_server.get_user_state') as mock_get_user_state, \
             patch('potato.flask_server.get_item_state_manager') as mock_get_item_state_manager, \
             patch('potato.flask_server.get_annotations_for_user_on') as mock_get_annotations, \
             patch('potato.flask_server.get_span_annotations_for_user_on') as mock_get_span_annotations, \
             patch('potato.flask_server.get_user_state_manager') as mock_get_user_state_manager, \
             patch('potato.flask_server.render_template') as mock_render_template, \
             patch('potato.flask_server.config') as mock_config:

            # Setup mock config with UI configuration
            ui_config = {
                "max_instance_height": 300,
                "spans": {
                    "span_colors": {
                        "emotion": {
                            "happy": "(255, 230, 230)"
                        }
                    }
                }
            }

            # Mock config.get to return the UI config when called with "ui"
            def mock_config_get(key, default=None):
                if key == "ui":
                    return ui_config
                return default

            mock_config.get.side_effect = mock_config_get

            # Setup mock user state
            mock_user_state = MagicMock()
            mock_user_state.get_current_phase_and_page.return_value = ("annotation", "page")
            mock_user_state.get_progress.return_value = {"completed": 5, "total": 10}
            mock_get_user_state.return_value = mock_user_state

            # Setup mock item state manager
            mock_item_state_manager = MagicMock()
            mock_get_item_state_manager.return_value = mock_item_state_manager

            # Setup mock user state manager
            mock_user_state_manager = MagicMock()
            mock_user_state_manager.get_phase_html_fname.return_value = "test_template.html"
            mock_get_user_state_manager.return_value = mock_user_state_manager

            # Setup mock annotations
            mock_get_annotations.return_value = {}
            mock_get_span_annotations.return_value = {}

            # Setup mock item
            mock_item = MagicMock()
            mock_item.get_data.return_value = {"text": "Test instance text"}
            mock_item_state_manager.get_item.return_value = mock_item

            # Call the function
            render_page_with_annotations_WEIRD("test_user")

            # Verify that render_template was called with ui_config
            mock_render_template.assert_called_once()
            call_args = mock_render_template.call_args[1]  # Get keyword arguments

            # Check that ui_config was passed
            assert 'ui_config' in call_args
            assert call_args['ui_config'] == ui_config

    def test_ui_config_empty_when_not_configured(self):
        """Test that empty UI config is passed when not configured."""
        with patch('potato.flask_server.get_user_state') as mock_get_user_state, \
             patch('potato.flask_server.get_item_state_manager') as mock_get_item_state_manager, \
             patch('potato.flask_server.get_annotations_for_user_on') as mock_get_annotations, \
             patch('potato.flask_server.get_span_annotations_for_user_on') as mock_get_span_annotations, \
             patch('potato.flask_server.get_user_state_manager') as mock_get_user_state_manager, \
             patch('potato.flask_server.render_template') as mock_render_template, \
             patch('potato.flask_server.config') as mock_config:

            # Setup mock config without UI configuration
            mock_config.get.return_value = {}

            # Setup other mocks
            mock_user_state = MagicMock()
            mock_user_state.get_current_phase_and_page.return_value = ("annotation", "page")
            mock_user_state.get_progress.return_value = {"completed": 5, "total": 10}
            mock_get_user_state.return_value = mock_user_state

            mock_item_state_manager = MagicMock()
            mock_get_item_state_manager.return_value = mock_item_state_manager

            mock_user_state_manager = MagicMock()
            mock_user_state_manager.get_phase_html_fname.return_value = "test_template.html"
            mock_get_user_state_manager.return_value = mock_user_state_manager

            mock_get_annotations.return_value = {}
            mock_get_span_annotations.return_value = {}

            mock_item = MagicMock()
            mock_item.get_data.return_value = {"text": "Test instance text"}
            mock_item_state_manager.get_item.return_value = mock_item

            # Call the function
            render_page_with_annotations_WEIRD("test_user")

            # Verify that render_template was called with empty ui_config
            mock_render_template.assert_called_once()
            call_args = mock_render_template.call_args[1]

            assert 'ui_config' in call_args
            assert call_args['ui_config'] == {}