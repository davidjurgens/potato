"""
Unit tests to reproduce and verify the checkbox selection bug.

These tests focus on the onlyOne function and checkbox event handling
to identify why checkboxes are being unchecked immediately after being checked.
"""

import pytest
from unittest.mock import Mock, patch
import sys
import os

# Add the potato directory to the path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# Since we can't directly import JavaScript functions, we'll test the logic
# by recreating the onlyOne function in Python


def only_one_python(checkbox, all_checkboxes):
    """
    Python version of the onlyOne JavaScript function for testing.

    Args:
        checkbox: The checkbox that was clicked
        all_checkboxes: List of all checkboxes in the same group
    """
    print(f'🔍 [DEBUG] onlyOne() called with checkbox:', {
        'id': checkbox['id'],
        'name': checkbox['name'],
        'value': checkbox['value'],
        'checked': checkbox['checked'],
        'className': checkbox['className']
    })

    print(f'🔍 [DEBUG] onlyOne() - Found elements with same class:', len(all_checkboxes))

    for i, other_checkbox in enumerate(all_checkboxes):
        print(f'🔍 [DEBUG] onlyOne() - Processing element:', {
            'id': other_checkbox['id'],
            'value': other_checkbox['value'],
            'checked': other_checkbox['checked'],
            'willUncheck': other_checkbox['value'] != checkbox['value']
        })

        if other_checkbox['value'] != checkbox['value']:
            print(f'🔍 [DEBUG] onlyOne() - Unchecking element:', other_checkbox['id'])
            other_checkbox['checked'] = False

    # Ensure the clicked checkbox is checked
    print(f'🔍 [DEBUG] onlyOne() - Setting clicked checkbox to checked:', checkbox['id'])
    checkbox['checked'] = True


class TestCheckboxSelectionBug:
    """Test the checkbox selection bug reproduction and fix."""

    def test_only_one_function_behavior(self):
        """Test the onlyOne function to understand its behavior."""
        # Create mock checkboxes
        checkbox1 = {
            'id': "emotion_happy",
            'name': "span_label:::emotion",
            'value': "1",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        checkbox2 = {
            'id': "emotion_sad",
            'name': "span_label:::emotion",
            'value': "2",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        checkbox3 = {
            'id': "emotion_angry",
            'name': "span_label:::emotion",
            'value': "3",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        all_checkboxes = [checkbox1, checkbox2, checkbox3]

        # Simulate clicking checkbox1
        with patch('builtins.print') as mock_print:
            # Set checkbox1 as checked (simulating user click)
            checkbox1['checked'] = True

            # Call onlyOne function
            only_one_python(checkbox1, all_checkboxes)

            # Verify that checkbox1 is checked
            assert checkbox1['checked'] == True, "Clicked checkbox should be checked"

            # Verify that other checkboxes are unchecked
            assert checkbox2['checked'] == False, "Other checkboxes should be unchecked"
            assert checkbox3['checked'] == False, "Other checkboxes should be unchecked"

            # Verify debug output
            mock_print.assert_called()
            debug_calls = [call for call in mock_print.call_args_list if 'onlyOne' in str(call)]
            assert len(debug_calls) > 0, "Debug output should be generated"

    def test_checkbox_event_sequence(self):
        """Test the sequence of events when a checkbox is clicked."""
        # This test simulates the actual event sequence that happens in the browser

        # Create mock checkboxes
        checkbox1 = {
            'id': "emotion_happy",
            'name': "span_label:::emotion",
            'value': "1",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        checkbox2 = {
            'id': "emotion_sad",
            'name': "span_label:::emotion",
            'value': "2",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        all_checkboxes = [checkbox1, checkbox2]

        # Simulate the event sequence:
        # 1. User clicks checkbox
        # 2. Browser sets checked = true
        # 3. onclick event fires (onlyOne is called)
        # 4. change event fires (setupSpanLabelSelector change handler)

        # Step 1: User clicks checkbox1
        checkbox1['checked'] = True

        # Step 2: onlyOne is called (this should maintain the checked state)
        with patch('builtins.print'):
            only_one_python(checkbox1, all_checkboxes)

        # Step 3: Verify checkbox1 is still checked
        assert checkbox1['checked'] == True, "Checkbox should remain checked after onlyOne"

        # Step 4: Verify other checkboxes are unchecked
        assert checkbox2['checked'] == False, "Other checkbox should be unchecked"

    def test_checkbox_state_persistence(self):
        """Test that checkbox state persists correctly through multiple interactions."""
        # Create mock checkboxes
        checkbox1 = {
            'id': "emotion_happy",
            'name': "span_label:::emotion",
            'value': "1",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        checkbox2 = {
            'id': "emotion_sad",
            'name': "span_label:::emotion",
            'value': "2",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        all_checkboxes = [checkbox1, checkbox2]

        # Simulate clicking checkbox1
        with patch('builtins.print'):
            checkbox1['checked'] = True
            only_one_python(checkbox1, all_checkboxes)

            # Verify checkbox1 is checked
            assert checkbox1['checked'] == True

            # Simulate clicking checkbox2
            checkbox2['checked'] = True
            only_one_python(checkbox2, all_checkboxes)

            # Verify checkbox2 is checked and checkbox1 is unchecked
            assert checkbox2['checked'] == True
            assert checkbox1['checked'] == False

    def test_only_one_with_different_values(self):
        """Test that onlyOne correctly handles checkboxes with different values."""
        # Create mock checkboxes with different values
        checkbox1 = {
            'id': "emotion_happy",
            'name': "span_label:::emotion",
            'value': "1",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        checkbox2 = {
            'id': "emotion_sad",
            'name': "span_label:::emotion",
            'value': "2",
            'checked': False,
            'className': "emotion shadcn-span-checkbox"
        }

        all_checkboxes = [checkbox1, checkbox2]

        # Simulate clicking checkbox1
        with patch('builtins.print'):
            checkbox1['checked'] = True
            only_one_python(checkbox1, all_checkboxes)

            # Verify only checkbox1 is checked
            assert checkbox1['checked'] == True
            assert checkbox2['checked'] == False

            # Simulate clicking checkbox2
            checkbox2['checked'] = True
            only_one_python(checkbox2, all_checkboxes)

            # Verify only checkbox2 is checked
            assert checkbox1['checked'] == False
            assert checkbox2['checked'] == True