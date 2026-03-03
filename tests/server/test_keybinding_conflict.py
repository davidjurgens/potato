"""
Server integration test for keybinding conflict resolution.

Starts a server with multi-schema config (radio + multiselect, both with
sequential_key_binding: true) and verifies the generated HTML has
non-overlapping data-key values across schemas.
"""

import pytest
import requests
import re
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestKeybindingConflict:
    """
    Verify that the keybinding allocator prevents key conflicts between
    radio and multiselect schemas when both use sequential_key_binding.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "Select sentiment",
                "labels": ["positive", "negative", "neutral", "mixed"],
                "sequential_key_binding": True,
            },
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "description": "Select topics",
                "labels": ["quality", "price", "service", "design", "durability"],
                "sequential_key_binding": True,
            },
        ]
        with TestConfigManager("keybinding_conflict", annotation_schemes) as test_config:
            server = FlaskTestServer(port=9087, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start Flask server")
            yield server
            server.stop()

    def _login(self, flask_server):
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register", data={"email": "testuser", "pass": "testpass"})
        session.post(f"{flask_server.base_url}/auth", data={"email": "testuser", "pass": "testpass"})
        return session

    def test_non_overlapping_keys_in_html(self, flask_server):
        """Radio and multiselect should have non-overlapping data-key values."""
        session = self._login(flask_server)
        response = session.get(f"{flask_server.base_url}/annotate")
        assert response.status_code == 200
        html = response.text

        # Extract all data-key values from radio inputs (multi-line attributes)
        radio_keys = set(re.findall(
            r'<input[^>]*?type="radio"[^>]*?data-key="([^"]*)"',
            html, re.DOTALL
        ))
        # Also try reversed attribute order
        radio_keys.update(re.findall(
            r'<input[^>]*?data-key="([^"]*)"[^>]*?type="radio"',
            html, re.DOTALL
        ))

        # Extract all data-key values from checkbox inputs
        checkbox_keys = set(re.findall(
            r'<input[^>]*?type="checkbox"[^>]*?data-key="([^"]*)"',
            html, re.DOTALL
        ))
        checkbox_keys.update(re.findall(
            r'<input[^>]*?data-key="([^"]*)"[^>]*?type="checkbox"',
            html, re.DOTALL
        ))

        # Verify keys were assigned
        assert len(radio_keys) > 0, "Radio should have data-key attributes"
        assert len(checkbox_keys) > 0, "Checkboxes should have data-key attributes"

        # Verify no overlap
        overlap = radio_keys & checkbox_keys
        assert overlap == set(), f"Keys overlap between radio and checkbox: {overlap}"

    def test_radio_gets_number_keys(self, flask_server):
        """First schema (radio) should get number keys."""
        session = self._login(flask_server)
        response = session.get(f"{flask_server.base_url}/annotate")
        html = response.text

        radio_keys = set(re.findall(
            r'data-key="([^"]*)"', html
        ))
        # Filter to only keys from radio inputs by finding them in radio context
        # Use a simpler approach: find all data-key values near type="radio"
        radio_keys = set()
        for m in re.finditer(r'<input\b([\s\S]*?)>', html):
            attrs = m.group(1)
            if 'type="radio"' in attrs:
                dk = re.search(r'data-key="([^"]*)"', attrs)
                if dk:
                    radio_keys.add(dk.group(1))

        # Radio (first schema) should get number pool
        assert radio_keys.issubset({"1", "2", "3", "4", "5", "6", "7", "8", "9", "0"})

    def test_multiselect_gets_letter_keys(self, flask_server):
        """Second schema (multiselect) should get letter keys."""
        session = self._login(flask_server)
        response = session.get(f"{flask_server.base_url}/annotate")
        html = response.text

        checkbox_keys = set()
        for m in re.finditer(r'<input\b([\s\S]*?)>', html):
            attrs = m.group(1)
            if 'type="checkbox"' in attrs:
                dk = re.search(r'data-key="([^"]*)"', attrs)
                if dk:
                    checkbox_keys.add(dk.group(1))

        # Multiselect (second schema) should get QWERTY top row
        qwerty_top = {"q", "w", "e", "r", "t", "y", "u", "i", "o", "p"}
        assert checkbox_keys.issubset(qwerty_top)

    def test_checkbox_value_is_label_name(self, flask_server):
        """Checkbox value attributes should be label names, not key numbers."""
        session = self._login(flask_server)
        response = session.get(f"{flask_server.base_url}/annotate")
        html = response.text

        # Find checkbox values in the topics schema
        checkbox_values = []
        for m in re.finditer(r'<input\b([\s\S]*?)>', html):
            attrs = m.group(1)
            if 'type="checkbox"' in attrs and 'schema="topics"' in attrs:
                val = re.search(r'value="([^"]*)"', attrs)
                if val:
                    checkbox_values.append(val.group(1))

        # Values should be label names, not numbers
        for val in checkbox_values:
            assert not val.isdigit(), f"Checkbox value should be label name, got number: {val}"

    def test_keybinding_badges_present(self, flask_server):
        """Both schemas should have keybinding-badge class elements."""
        session = self._login(flask_server)
        response = session.get(f"{flask_server.base_url}/annotate")
        html = response.text

        assert "keybinding-badge" in html, "Should have keybinding-badge class in HTML"
