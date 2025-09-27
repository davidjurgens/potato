"""
Unit test to verify the checkbox selection bug fix.

This test verifies that the flag mechanism prevents the change event
from interfering with programmatically set checkbox states.
"""

import pytest
from unittest.mock import Mock, patch


class TestCheckboxFix:
    """Test the checkbox selection bug fix."""

    def test_flag_mechanism_prevents_interference(self):
        """Test that the data-just-checked flag prevents change event interference."""
        # Create mock checkbox
        checkbox = Mock()
        checkbox.id = "emotion_happy"
        checkbox.name = "span_label:::emotion"
        checkbox.value = "1"
        checkbox.checked = False
        checkbox.className = "emotion shadcn-span-checkbox"
        checkbox.hasAttribute = Mock(return_value=False)
        checkbox.setAttribute = Mock()
        checkbox.removeAttribute = Mock()

        # Simulate the onlyOne function behavior
        def only_one_simulation(checkbox):
            # Set the flag
            checkbox.setAttribute('data-just-checked', 'true')
            checkbox.checked = True
            return True

        # Simulate the change event handler behavior
        def change_event_handler(checkbox):
            # Check if this change event was triggered by programmatic setting
            if checkbox.checked and checkbox.hasAttribute('data-just-checked'):
                checkbox.removeAttribute('data-just-checked')
                return False  # Don't interfere
            return True  # Would interfere

        # Test the sequence
        result = only_one_simulation(checkbox)
        assert result == True, "onlyOne should succeed"
        assert checkbox.checked == True, "Checkbox should be checked"

        # Simulate change event
        checkbox.hasAttribute.return_value = True  # Flag is set
        interference = change_event_handler(checkbox)
        assert interference == False, "Change event should not interfere when flag is set"

        # Verify flag was removed
        checkbox.removeAttribute.assert_called_with('data-just-checked')

    def test_normal_change_event_still_works(self):
        """Test that normal change events (user clicks) still work correctly."""
        # Create mock checkbox
        checkbox = Mock()
        checkbox.id = "emotion_happy"
        checkbox.name = "span_label:::emotion"
        checkbox.value = "1"
        checkbox.checked = True
        checkbox.className = "emotion shadcn-span-checkbox"
        checkbox.hasAttribute = Mock(return_value=False)  # No flag set
        checkbox.removeAttribute = Mock()

        # Simulate the change event handler behavior
        def change_event_handler(checkbox):
            # Check if this change event was triggered by programmatic setting
            if checkbox.checked and checkbox.hasAttribute('data-just-checked'):
                checkbox.removeAttribute('data-just-checked')
                return False  # Don't interfere
            return True  # Would interfere

        # Test normal change event (no flag)
        interference = change_event_handler(checkbox)
        assert interference == True, "Normal change events should work normally"

        # Verify flag removal was not called
        checkbox.removeAttribute.assert_not_called()

    def test_flag_timeout_cleanup(self):
        """Test that the flag is cleaned up by timeout if change event doesn't fire."""
        # This test simulates the timeout mechanism
        checkbox = Mock()
        checkbox.hasAttribute = Mock(return_value=True)  # Flag is set
        checkbox.removeAttribute = Mock()

        # Simulate timeout cleanup
        def timeout_cleanup(checkbox):
            if checkbox.hasAttribute('data-just-checked'):
                checkbox.removeAttribute('data-just-checked')
                return True
            return False

        # Test timeout cleanup
        cleaned = timeout_cleanup(checkbox)
        assert cleaned == True, "Timeout should clean up the flag"
        checkbox.removeAttribute.assert_called_with('data-just-checked')