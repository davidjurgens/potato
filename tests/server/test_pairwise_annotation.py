"""
Server integration tests for pairwise annotation schema.

These tests verify that the pairwise annotation type works correctly
in a running Flask server environment, including:
- HTML generation in annotation pages
- Annotation submission and storage
- Keyboard shortcut integration
- Binary and scale mode functionality
"""

import json
import pytest
import requests
from bs4 import BeautifulSoup

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory
)


class TestPairwiseBinaryMode:
    """Test pairwise annotation in binary mode (clickable tiles)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with pairwise binary annotation."""
        print("Setting up pairwise binary mode test server...")

        # Create test directory
        test_dir = create_test_directory("pairwise_binary_test")

        # Create test data with pairwise items
        test_data = [
            {"id": "pair_1", "text": ["Option A text for comparison", "Option B text for comparison"]},
            {"id": "pair_2", "text": ["First choice here", "Second choice here"]},
            {"id": "pair_3", "text": ["Left item content", "Right item content"]},
        ]

        data_file = create_test_data_file(test_dir, test_data, "pairwise_data.jsonl")

        # Create pairwise binary annotation scheme
        annotation_schemes = [{
            "name": "preference",
            "annotation_type": "pairwise",
            "description": "Which option is better?",
            "mode": "binary",
            "items_key": "text",
            "labels": ["Option A", "Option B"],
            "allow_tie": True,
            "tie_label": "No preference",
            "sequential_key_binding": True,
            "label_requirement": {"required": True}
        }]

        config_file = create_test_config(
            test_dir,
            annotation_schemes=annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Pairwise Binary Test",
            admin_api_key="test_admin_key",
        )

        # Start server
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        # Store test_dir for cleanup
        request.cls.test_dir = test_dir

        yield server

        # Cleanup
        server.stop()
        cleanup_test_directory(test_dir)

    def test_pairwise_binary_html_rendered(self, flask_server):
        """Test that pairwise binary annotation HTML is rendered on annotation page."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "pairwise_test_user_1", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Get annotation page
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Check for pairwise elements
        pairwise_form = soup.find('form', class_='pairwise')
        assert pairwise_form is not None, "Pairwise form not found"

        # Check for binary mode class
        assert 'pairwise-binary' in pairwise_form.get('class', [])

        # Check for tiles
        tiles = pairwise_form.find_all(class_='pairwise-tile')
        assert len(tiles) == 2, f"Expected 2 tiles, found {len(tiles)}"

        # Check for tie button (allow_tie: true)
        tie_btn = pairwise_form.find(class_='pairwise-tie-btn')
        assert tie_btn is not None, "Tie button not found"

    def test_pairwise_binary_annotation_submission(self, flask_server):
        """Test submitting a pairwise binary annotation."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "pairwise_test_user_2", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Submit annotation selecting option A
        annotation_data = {
            "instance_id": "pair_1",
            "type": "label",
            "schema": "preference",
            "state": [
                {"name": "preference:::selection", "value": "A"}
            ]
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data,
            timeout=5
        )
        assert response.status_code == 200

    def test_pairwise_binary_tie_submission(self, flask_server):
        """Test submitting a tie/no-preference annotation."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "pairwise_test_user_3", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Submit annotation selecting tie
        annotation_data = {
            "instance_id": "pair_2",
            "type": "label",
            "schema": "preference",
            "state": [
                {"name": "preference:::selection", "value": "tie"}
            ]
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data,
            timeout=5
        )
        assert response.status_code == 200

    def test_pairwise_binary_keybindings_in_html(self, flask_server):
        """Test that keyboard shortcuts are included in the HTML."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "pairwise_test_user_4", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Get annotation page
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Check for keybinding indicators
        assert '[1]' in response.text or 'data-key="1"' in response.text
        assert '[2]' in response.text or 'data-key="2"' in response.text


class TestPairwiseScaleMode:
    """Test pairwise annotation in scale mode (slider)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with pairwise scale annotation."""
        print("Setting up pairwise scale mode test server...")

        # Create test directory
        test_dir = create_test_directory("pairwise_scale_test")

        # Create test data with pairwise items
        test_data = [
            {"id": "scale_1", "text": ["Response A for rating", "Response B for rating"]},
            {"id": "scale_2", "text": ["First answer", "Second answer"]},
        ]

        data_file = create_test_data_file(test_dir, test_data, "scale_data.jsonl")

        # Create pairwise scale annotation scheme
        annotation_schemes = [{
            "name": "preference_scale",
            "annotation_type": "pairwise",
            "description": "Rate how much better A is than B",
            "mode": "scale",
            "items_key": "text",
            "labels": ["Response A", "Response B"],
            "scale": {
                "min": -3,
                "max": 3,
                "step": 1,
                "default": 0,
                "labels": {
                    "min": "A is much better",
                    "max": "B is much better",
                    "center": "Equal"
                }
            },
            "label_requirement": {"required": True}
        }]

        config_file = create_test_config(
            test_dir,
            annotation_schemes=annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Pairwise Scale Test",
            admin_api_key="test_admin_key",
        )

        # Start server
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        # Store test_dir for cleanup
        request.cls.test_dir = test_dir

        yield server

        # Cleanup
        server.stop()
        cleanup_test_directory(test_dir)

    def test_pairwise_scale_html_rendered(self, flask_server):
        """Test that pairwise scale annotation HTML is rendered."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "scale_test_user_1", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Get annotation page
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Check for pairwise scale elements
        pairwise_form = soup.find('form', class_='pairwise')
        assert pairwise_form is not None, "Pairwise form not found"

        # Check for scale mode class
        assert 'pairwise-scale' in pairwise_form.get('class', [])

        # Check for slider
        slider = pairwise_form.find('input', {'type': 'range'})
        assert slider is not None, "Slider input not found"

        # Check slider attributes
        assert slider.get('min') == '-3'
        assert slider.get('max') == '3'

    def test_pairwise_scale_annotation_submission(self, flask_server):
        """Test submitting a pairwise scale annotation."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "scale_test_user_2", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Submit annotation with scale value
        annotation_data = {
            "instance_id": "scale_1",
            "type": "label",
            "schema": "preference_scale",
            "state": [
                {"name": "preference_scale:::scale_value", "value": "-2"}
            ]
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data,
            timeout=5
        )
        assert response.status_code == 200

    def test_pairwise_scale_labels_in_html(self, flask_server):
        """Test that scale endpoint labels are in the HTML."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "scale_test_user_3", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Get annotation page
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Check for scale labels
        assert "A is much better" in response.text
        assert "B is much better" in response.text
        assert "Equal" in response.text


class TestPairwiseWithoutTie:
    """Test pairwise annotation without tie option."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with pairwise annotation without tie."""
        print("Setting up pairwise no-tie test server...")

        # Create test directory
        test_dir = create_test_directory("pairwise_no_tie_test")

        # Create test data
        test_data = [
            {"id": "notie_1", "text": ["Choice A", "Choice B"]},
        ]

        data_file = create_test_data_file(test_dir, test_data, "notie_data.jsonl")

        # Create pairwise annotation scheme without tie
        annotation_schemes = [{
            "name": "forced_choice",
            "annotation_type": "pairwise",
            "description": "Choose one (forced choice)",
            "mode": "binary",
            "items_key": "text",
            "allow_tie": False,  # No tie option
            "sequential_key_binding": True,
        }]

        config_file = create_test_config(
            test_dir,
            annotation_schemes=annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Pairwise No Tie Test",
        )

        # Start server
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        # Store test_dir for cleanup
        request.cls.test_dir = test_dir

        yield server

        # Cleanup
        server.stop()
        cleanup_test_directory(test_dir)

    def test_no_tie_button_rendered(self, flask_server):
        """Test that tie button is NOT rendered when allow_tie is false."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "notie_test_user", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Get annotation page
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Check that tie button is NOT present
        tie_btn = soup.find(class_='pairwise-tie-btn')
        assert tie_btn is None, "Tie button should not be present when allow_tie is false"

        # But tiles should still be present
        tiles = soup.find_all(class_='pairwise-tile')
        assert len(tiles) == 2


class TestPairwiseMultipleSchemas:
    """Test multiple pairwise annotation schemas on same page."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with multiple pairwise schemas."""
        print("Setting up multiple pairwise schemas test server...")

        # Create test directory
        test_dir = create_test_directory("pairwise_multi_test")

        # Create test data
        test_data = [
            {"id": "multi_1", "text": ["Response A", "Response B"]},
        ]

        data_file = create_test_data_file(test_dir, test_data, "multi_data.jsonl")

        # Create multiple pairwise annotation schemes
        annotation_schemes = [
            {
                "name": "fluency",
                "annotation_type": "pairwise",
                "description": "Which is more fluent?",
                "mode": "binary",
                "items_key": "text",
                "labels": ["A", "B"],
                "allow_tie": True,
            },
            {
                "name": "relevance",
                "annotation_type": "pairwise",
                "description": "Which is more relevant?",
                "mode": "binary",
                "items_key": "text",
                "labels": ["A", "B"],
                "allow_tie": True,
            },
            {
                "name": "overall_scale",
                "annotation_type": "pairwise",
                "description": "Overall preference",
                "mode": "scale",
                "items_key": "text",
                "scale": {"min": -2, "max": 2, "step": 1},
            },
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes=annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Pairwise Multi Test",
        )

        # Start server
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        # Store test_dir for cleanup
        request.cls.test_dir = test_dir

        yield server

        # Cleanup
        server.stop()
        cleanup_test_directory(test_dir)

    def test_multiple_pairwise_forms_rendered(self, flask_server):
        """Test that multiple pairwise forms are rendered."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "multi_test_user", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Get annotation page
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Check for multiple pairwise forms
        pairwise_forms = soup.find_all('form', class_='pairwise')
        assert len(pairwise_forms) == 3, f"Expected 3 pairwise forms, found {len(pairwise_forms)}"

        # Check for both binary and scale modes
        binary_forms = soup.find_all('form', class_='pairwise-binary')
        scale_forms = soup.find_all('form', class_='pairwise-scale')
        assert len(binary_forms) == 2
        assert len(scale_forms) == 1

    def test_multiple_annotations_submission(self, flask_server):
        """Test submitting annotations for multiple pairwise schemas."""
        session = requests.Session()

        # Register and login
        user_data = {"email": "multi_test_user_2", "pass": "test_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user_data, timeout=5)

        # Submit annotations for all schemas
        annotations = [
            {"schema": "fluency", "name": "fluency:::selection", "value": "A"},
            {"schema": "relevance", "name": "relevance:::selection", "value": "B"},
            {"schema": "overall_scale", "name": "overall_scale:::scale_value", "value": "1"},
        ]

        for ann in annotations:
            annotation_data = {
                "instance_id": "multi_1",
                "type": "label",
                "schema": ann["schema"],
                "state": [{"name": ann["name"], "value": ann["value"]}]
            }

            response = session.post(
                f"{flask_server.base_url}/updateinstance",
                json=annotation_data,
                timeout=5
            )
            assert response.status_code == 200, f"Failed to submit {ann['schema']} annotation"
