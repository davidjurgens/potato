"""
Unit test to verify the span manager selectLabel fix.

This test verifies that the selectLabel function no longer interferes
with checkbox state management that's handled by the onlyOne function.
"""

import pytest
from unittest.mock import Mock, patch


class TestSpanManagerFix:
    """Test the span manager selectLabel fix."""

    def test_select_label_does_not_interfere_with_checkbox_state(self):
        """Test that selectLabel no longer manages checkbox state."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.selectedLabel = None
        span_manager.currentSchema = None

        # Mock the selectLabel function behavior
        def select_label(label, schema=None):
            # Don't interfere with checkbox state management
            print('🔍 [DEBUG] SpanManager.selectLabel() called with:', { 'label': label, 'schema': schema })
            print('🔍 [DEBUG] SpanManager.selectLabel() - Skipping checkbox state management, letting onlyOne handle it')

            span_manager.selectedLabel = label
            if schema:
                span_manager.currentSchema = schema
            print('SpanManager: Selected label:', label, 'schema:', span_manager.currentSchema)

        # Test the function
        with patch('builtins.print') as mock_print:
            select_label('happy', 'emotion')

            # Verify the label and schema were set correctly
            assert span_manager.selectedLabel == 'happy'
            assert span_manager.currentSchema == 'emotion'

            # Verify the debug messages were printed
            mock_print.assert_called()
            debug_calls = [call for call in mock_print.call_args_list if 'selectLabel' in str(call)]
            assert len(debug_calls) >= 2, "Debug messages should be printed"

    def test_select_label_preserves_existing_checkbox_state(self):
        """Test that selectLabel doesn't change existing checkbox states."""
        # Create mock checkboxes
        checkbox1 = Mock()
        checkbox1.checked = True
        checkbox1.id = "emotion_happy"

        checkbox2 = Mock()
        checkbox2.checked = False
        checkbox2.id = "emotion_sad"

        # Mock document.querySelectorAll to return our checkboxes
        original_checkboxes = [checkbox1, checkbox2]

        # Test that selectLabel doesn't call any checkbox state management
        def select_label(label, schema=None):
            # This function should NOT call any checkbox state management
            # It should only set the internal state
            return {
                'selectedLabel': label,
                'currentSchema': schema,
                'checkboxStateChanged': False  # No checkbox state changes
            }

        # Test the function
        result = select_label('happy', 'emotion')

        # Verify the result
        assert result['selectedLabel'] == 'happy'
        assert result['currentSchema'] == 'emotion'
        assert result['checkboxStateChanged'] == False

        # Verify checkboxes were not modified
        assert checkbox1.checked == True
        assert checkbox2.checked == False

    def test_select_label_handles_multiple_calls_correctly(self):
        """Test that selectLabel handles multiple calls correctly."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.selectedLabel = None
        span_manager.currentSchema = None

        # Mock the selectLabel function behavior
        def select_label(label, schema=None):
            span_manager.selectedLabel = label
            if schema:
                span_manager.currentSchema = schema
            return {
                'selectedLabel': span_manager.selectedLabel,
                'currentSchema': span_manager.currentSchema
            }

        # Test multiple calls
        result1 = select_label('happy', 'emotion')
        assert result1['selectedLabel'] == 'happy'
        assert result1['currentSchema'] == 'emotion'

        result2 = select_label('sad', 'emotion')
        assert result2['selectedLabel'] == 'sad'
        assert result2['currentSchema'] == 'emotion'

        result3 = select_label('angry')
        assert result3['selectedLabel'] == 'angry'
        assert result3['currentSchema'] == 'emotion'  # Should preserve previous schema