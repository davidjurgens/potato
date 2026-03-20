"""
Multi-Phase Workflow Tests

This module contains tests for complete multi-phase annotation workflows,
including consent, instructions, annotation, and post-study phases.
"""

import json
from pathlib import Path

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)


def _write_phase_scheme_file(test_dir: str, filename: str, schemes: list[dict]) -> str:
    """
    Write a phase annotation scheme file into the test directory.

    Returns the filename relative to test_dir, which is what the config expects.
    """
    path = Path(test_dir) / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schemes, f, indent=2)
    return filename


class TestMultiPhaseWorkflow:
    """Test complete multi-phase annotation workflows."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with multi-phase test data."""
        test_dir = create_test_directory("multi_phase_workflow_test")

        # Create test data for the real annotation phase
        test_data = [
            {"id": "phase_item_1", "text": "This is the first item for phase testing."},
            {"id": "phase_item_2", "text": "This is the second item for phase testing."},
            {"id": "phase_item_3", "text": "This is the third item for phase testing."},
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Top-level annotation schemes are used only for the actual annotation phase
        annotation_schemes = [
            {
                "name": "phase_rating",
                "annotation_type": "radio",
                "labels": ["1", "2", "3", "4", "5"],
                "description": "Rate the quality of this text.",
            }
        ]

        # Phase-specific scheme files, used to avoid mixing top-level
        # annotation_schemes with phase-level annotation_schemes in config.
        consent_file = _write_phase_scheme_file(
            test_dir,
            "consent_phase.json",
            [
                {
                    "name": "age_consent",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Are you at least 18 years old?",
                },
                {
                    "name": "info_consent",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Do you agree to participate?",
                },
            ],
        )

        prestudy_file = _write_phase_scheme_file(
            test_dir,
            "prestudy_phase.json",
            [
                {
                    "name": "internet_familiarity",
                    "annotation_type": "likert",
                    "description": "How familiar are you with the internet?",
                    "min_label": "1",
                    "max_label": "5",
                    "size": 5,
                }
            ],
        )

        instructions_file = _write_phase_scheme_file(
            test_dir,
            "instructions_phase.json",
            [
                {
                    "name": "read_instructions",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Have you read the instructions?",
                }
            ],
        )

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Multi-Phase Test Task",
            require_password=False,
            max_annotations_per_user=10,
            phases={
                "order": ["consent", "prestudy", "instructions", "annotation"],
                "consent": {
                    "type": "consent",
                    "file": consent_file,
                },
                "prestudy": {
                    "type": "prestudy",
                    "file": prestudy_file,
                },
                "instructions": {
                    "type": "instructions",
                    "file": instructions_file,
                },
            },
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_annotation_phase(self):
        """Test the annotation phase endpoint is reachable for an authenticated user."""
        session = requests.Session()
        user_data = {"email": "phase_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

    def test_multi_item_workflow(self):
        """Test annotation submission across multiple assigned items."""
        session = requests.Session()
        user_data = {"email": "multi_item_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "phase_item_1",
            "type": "radio",
            "schema": "phase_rating",
            "state": [{"name": "3", "value": "3"}],
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_first_non_annotation_phase_renders_hidden_instance_text_placeholders(self):
        """
        Regression test for the shared base template on the first non-annotation phase.

        Non-annotation phases still load shared frontend JS that expects
        #instance-text and #text-content to exist. The page should therefore
        render hidden placeholders, but should not render the visible annotation
        block with the 'Text to Annotate:' heading.
        """
        session = requests.Session()
        username = "consent_placeholder_test_user"
        user_data = {"email": username, "pass": "test_password"}

        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # New users should land on the first configured phase, consent
        response = session.get(f"{self.server.base_url}/")
        assert response.status_code == 200

        html = response.text

        # Shared JS contract: these placeholders must exist even off annotation pages
        assert 'id="instance-text"' in html
        assert 'id="text-content"' in html

        # The visible annotation heading should not appear on consent page
        assert "Text to Annotate:" not in html

        # The visible annotation styling block should also not appear
        assert 'class="p-3 border rounded instance-text-container"' not in html

        # The phase-specific form content should appear instead
        assert "Are you at least 18 years old?" in html
        assert "Do you agree to participate?" in html

        # The annotation forms container still exists because the shared base template is used
        assert 'id="annotation-forms"' in html

    def test_annotation_phase_renders_visible_instance_text_container(self):
        """
        Regression test for the actual annotation page.

        The annotation phase should render the visible text block, including:
        - the heading 'Text to Annotate:'
        - a visible #instance-text container
        - a #text-content element
        - the current instance text itself
        """
        session = requests.Session()
        username = "annotation_phase_render_test_user"
        user_data = {"email": username, "pass": "test_password"}

        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Step through configured pre-annotation phases so we reach the real annotation page
        for expected_text in [
            "Are you at least 18 years old?",
            "How familiar are you with the internet?",
            "Have you read the instructions?",
        ]:
            response = session.get(f"{self.server.base_url}/")
            assert response.status_code == 200
            assert expected_text in response.text

            # Advance phase by submitting a minimal response
            if "Are you at least 18 years old?" in response.text:
                phase_payload = {
                    "age_consent:::Yes": "true",
                    "info_consent:::Yes": "true",
                }
            elif "How familiar are you with the internet?" in response.text:
                phase_payload = {
                    "internet_familiarity:::slider": "3",
                }
            else:
                phase_payload = {
                    "read_instructions:::Yes": "true",
                }

            submit_response = session.post(
                f"{self.server.base_url}/annotate",
                data=phase_payload,
                allow_redirects=True,
            )
            assert submit_response.status_code == 200

        # Now request the annotation page directly
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        html = response.text

        # Visible annotation block should be present
        assert "Text to Annotate:" in html

        # Required DOM hooks for annotation frontend
        assert 'id="instance-text"' in html
        assert 'id="text-content"' in html
        assert 'id="span-overlays"' in html

        # The annotation-phase container should be the visible styled block
        assert 'class="p-3 border rounded instance-text-container"' in html

        # Hidden input for current instance id should exist
        assert 'id="instance_id"' in html

        # Actual annotation-phase question should be present
        assert "Rate the quality of this text." in html

        # The current instance text should be rendered on the page
        assert "This is the first item for phase testing." in html