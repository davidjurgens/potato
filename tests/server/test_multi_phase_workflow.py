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

    def test_next_instance_is_blocked_until_required_annotations_are_complete(self):
        """Required annotation schemas should block instance navigation server-side."""
        test_dir = create_test_directory("required_annotation_navigation")
        try:
            test_data = [
                {"id": "item_1", "text": "First required item."},
                {"id": "item_2", "text": "Second required item."},
            ]
            data_file = create_test_data_file(test_dir, test_data)
            annotation_schemes = [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative"],
                    "description": "Sentiment",
                    "required": True,
                },
                {
                    "name": "notes",
                    "annotation_type": "text",
                    "description": "Notes",
                    "required": True,
                },
            ]

            config_file = create_test_config(
                test_dir,
                annotation_schemes,
                data_files=[data_file],
                annotation_task_name="Required Annotation Navigation",
                require_password=False,
                max_annotations_per_user=10,
                phases={"order": ["annotation"], "annotation": {"type": "annotation"}},
            )

            server = FlaskTestServer(config_file=config_file, debug=False)
            assert server.start()
            try:
                session = requests.Session()
                user_data = {"email": "required_nav_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                blocked = session.post(
                    f"{server.base_url}/annotate",
                    json={"action": "next_instance", "instance_id": "item_1"},
                )
                assert blocked.status_code == 400
                assert blocked.json()["status"] == "validation_error"

                session.post(
                    f"{server.base_url}/updateinstance",
                    json={
                        "instance_id": "item_1",
                        "annotations": {
                            "sentiment:positive": "true",
                            "notes:text_box": "filled",
                        },
                        "span_annotations": [],
                    },
                )

                allowed = session.post(
                    f"{server.base_url}/annotate",
                    json={"action": "next_instance", "instance_id": "item_1"},
                )
                assert allowed.status_code == 200
                assert "Second required item." in allowed.text
            finally:
                server.stop()
        finally:
            cleanup_test_directory(test_dir)

    def test_jump_to_unannotated_is_blocked_until_required_annotations_are_complete(self):
        """Header jump-forward navigation should honor the same required rules as Next."""
        test_dir = create_test_directory("required_jump_navigation")
        try:
            test_data = [
                {"id": "item_1", "text": "First required item."},
                {"id": "item_2", "text": "Second required item."},
                {"id": "item_3", "text": "Third required item."},
            ]
            data_file = create_test_data_file(test_dir, test_data)
            annotation_schemes = [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative"],
                    "description": "Sentiment",
                    "required": True,
                },
                {
                    "name": "notes",
                    "annotation_type": "text",
                    "description": "Notes",
                    "required": True,
                },
            ]

            config_file = create_test_config(
                test_dir,
                annotation_schemes,
                data_files=[data_file],
                annotation_task_name="Required Jump Navigation",
                require_password=False,
                max_annotations_per_user=10,
                phases={"order": ["annotation"], "annotation": {"type": "annotation"}},
            )

            server = FlaskTestServer(config_file=config_file, debug=False)
            assert server.start()
            try:
                session = requests.Session()
                user_data = {"email": "required_jump_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                blocked = session.post(
                    f"{server.base_url}/annotate",
                    json={"action": "jump_to_unannotated", "instance_id": "item_1"},
                )
                assert blocked.status_code == 400
                assert blocked.json()["status"] == "validation_error"

                session.post(
                    f"{server.base_url}/updateinstance",
                    json={
                        "instance_id": "item_1",
                        "annotations": {
                            "sentiment:positive": "true",
                            "notes:text_box": "filled",
                        },
                        "span_annotations": [],
                    },
                )

                allowed = session.post(
                    f"{server.base_url}/annotate",
                    json={"action": "jump_to_unannotated", "instance_id": "item_1"},
                )
                assert allowed.status_code == 200
                assert "Second required item." in allowed.text
            finally:
                server.stop()
        finally:
            cleanup_test_directory(test_dir)

    def test_go_to_forward_is_blocked_until_required_annotations_are_complete(self):
        """Direct header go-to should not bypass required annotation validation when moving forward."""
        test_dir = create_test_directory("required_goto_navigation")
        try:
            test_data = [
                {"id": "item_1", "text": "First required item."},
                {"id": "item_2", "text": "Second required item."},
                {"id": "item_3", "text": "Third required item."},
            ]
            data_file = create_test_data_file(test_dir, test_data)
            annotation_schemes = [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative"],
                    "description": "Sentiment",
                    "required": True,
                },
                {
                    "name": "notes",
                    "annotation_type": "text",
                    "description": "Notes",
                    "required": True,
                },
            ]

            config_file = create_test_config(
                test_dir,
                annotation_schemes,
                data_files=[data_file],
                annotation_task_name="Required Go To Navigation",
                require_password=False,
                max_annotations_per_user=10,
                phases={"order": ["annotation"], "annotation": {"type": "annotation"}},
            )

            server = FlaskTestServer(config_file=config_file, debug=False)
            assert server.start()
            try:
                session = requests.Session()
                user_data = {"email": "required_goto_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                blocked = session.post(
                    f"{server.base_url}/annotate",
                    json={"action": "go_to", "go_to": 1},
                )
                assert blocked.status_code == 400
                assert blocked.json()["status"] == "validation_error"

                session.post(
                    f"{server.base_url}/updateinstance",
                    json={
                        "instance_id": "item_1",
                        "annotations": {
                            "sentiment:positive": "true",
                            "notes:text_box": "filled",
                        },
                        "span_annotations": [],
                    },
                )

                allowed = session.post(
                    f"{server.base_url}/annotate",
                    json={"action": "go_to", "go_to": 1},
                )
                assert allowed.status_code == 200
                assert "Second required item." in allowed.text
            finally:
                server.stop()
        finally:
            cleanup_test_directory(test_dir)

    def test_last_item_partial_annotations_do_not_complete_the_phase(self):
        """A partially annotated last item should not trigger completion before navigation validation runs."""
        test_dir = create_test_directory("required_last_item_completion")
        try:
            test_data = [
                {"id": "item_1", "text": "First required item."},
                {"id": "item_2", "text": "Second required item."},
                {"id": "item_3", "text": "Third required item."},
            ]
            data_file = create_test_data_file(test_dir, test_data)
            annotation_schemes = [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative"],
                    "description": "Sentiment",
                    "required": True,
                },
                {
                    "name": "notes",
                    "annotation_type": "text",
                    "description": "Notes",
                    "required": True,
                },
            ]

            config_file = create_test_config(
                test_dir,
                annotation_schemes,
                data_files=[data_file],
                annotation_task_name="Required Last Item Completion",
                require_password=False,
                max_annotations_per_user=3,
                phases={"order": ["annotation"], "annotation": {"type": "annotation"}},
            )

            server = FlaskTestServer(config_file=config_file, debug=False)
            assert server.start()
            try:
                session = requests.Session()
                user_data = {"email": "required_last_item_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                for instance_id in ("item_1", "item_2"):
                    session.post(
                        f"{server.base_url}/updateinstance",
                        json={
                            "instance_id": instance_id,
                            "annotations": {
                                "sentiment:positive": "true",
                                "notes:text_box": f"filled-{instance_id}",
                            },
                            "span_annotations": [],
                        },
                    )
                    session.post(
                        f"{server.base_url}/annotate",
                        json={"action": "next_instance", "instance_id": instance_id},
                    )

                session.post(
                    f"{server.base_url}/updateinstance",
                    json={
                        "instance_id": "item_3",
                        "annotations": {
                            "sentiment:positive": "true",
                        },
                        "span_annotations": [],
                    },
                )

                blocked = session.post(
                    f"{server.base_url}/annotate",
                    json={"action": "next_instance", "instance_id": "item_3"},
                    allow_redirects=False,
                )
                assert blocked.status_code == 400
                assert blocked.json()["status"] == "validation_error"

                still_annotation = session.get(f"{server.base_url}/")
                assert "Third required item." in still_annotation.text
            finally:
                server.stop()
        finally:
            cleanup_test_directory(test_dir)

    def test_optional_annotation_schemas_do_not_block_next_instance(self):
        """Annotation schemas without explicit requirements should remain optional."""
        test_dir = create_test_directory("optional_annotation_navigation")
        try:
            test_data = [
                {"id": "item_1", "text": "First optional item."},
                {"id": "item_2", "text": "Second optional item."},
            ]
            data_file = create_test_data_file(test_dir, test_data)
            annotation_schemes = [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative"],
                    "description": "Sentiment",
                },
                {
                    "name": "notes",
                    "annotation_type": "text",
                    "description": "Notes",
                },
            ]

            config_file = create_test_config(
                test_dir,
                annotation_schemes,
                data_files=[data_file],
                annotation_task_name="Optional Annotation Navigation",
                require_password=False,
                max_annotations_per_user=10,
                phases={"order": ["annotation"], "annotation": {"type": "annotation"}},
            )

            server = FlaskTestServer(config_file=config_file, debug=False)
            assert server.start()
            try:
                session = requests.Session()
                user_data = {"email": "optional_nav_user", "pass": "test_password"}
                session.post(f"{server.base_url}/register", data=user_data)
                session.post(f"{server.base_url}/auth", data=user_data)

                allowed = session.post(
                    f"{server.base_url}/annotate",
                    json={"action": "next_instance", "instance_id": "item_1"},
                )
                assert allowed.status_code == 200
                assert "Second optional item." in allowed.text
            finally:
                server.stop()
        finally:
            cleanup_test_directory(test_dir)

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

    def test_previous_navigation_on_phase_page_does_not_advance_stage(self):
        """
        Regression test for phase pages using the shared annotation navigation UI.

        The Previous button on a non-annotation phase posts JSON to /annotate.
        That request must not be treated as a phase submission for the current
        page, or the workflow will incorrectly advance to the next stage.
        """
        session = requests.Session()
        username = "phase_prev_navigation_test_user"
        user_data = {"email": username, "pass": "test_password"}

        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/")
        assert response.status_code == 200
        assert "Are you at least 18 years old?" in response.text
        assert "How familiar are you with the internet?" not in response.text

        prev_response = session.post(
            f"{self.server.base_url}/annotate",
            json={"action": "prev_instance", "instance_id": "phase_item_1"},
            allow_redirects=True,
        )
        assert prev_response.status_code == 200

        # The user should still be on the consent stage, not advanced forward.
        assert "Are you at least 18 years old?" in prev_response.text
        assert "How familiar are you with the internet?" not in prev_response.text

    def test_previous_navigation_on_prestudy_returns_to_consent(self):
        """
        Previous navigation from prestudy should move to the previous workflow stage.
        """
        session = requests.Session()
        username = "phase_prev_from_prestudy_test_user"
        user_data = {"email": username, "pass": "test_password"}

        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        consent_response = session.get(f"{self.server.base_url}/")
        assert consent_response.status_code == 200
        assert "Are you at least 18 years old?" in consent_response.text

        # Advance to prestudy using the same compatibility path the tests already use.
        prestudy_response = session.post(
            f"{self.server.base_url}/annotate",
            data={
                "age_consent:::Yes": "true",
                "info_consent:::Yes": "true",
            },
            allow_redirects=True,
        )
        assert prestudy_response.status_code == 200
        assert "How familiar are you with the internet?" in prestudy_response.text

        prev_response = session.post(
            f"{self.server.base_url}/annotate",
            json={"action": "prev_instance", "instance_id": "phase_item_1"},
            allow_redirects=True,
        )
        assert prev_response.status_code == 200
        assert "Are you at least 18 years old?" in prev_response.text
        assert "How familiar are you with the internet?" not in prev_response.text

    def test_next_navigation_on_consent_advances_to_prestudy(self):
        """
        Shared navigation UI should advance non-annotation phases once required answers are saved.
        """
        session = requests.Session()
        username = "phase_next_from_consent_test_user"
        user_data = {"email": username, "pass": "test_password"}

        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        consent_response = session.get(f"{self.server.base_url}/")
        assert consent_response.status_code == 200
        assert "Are you at least 18 years old?" in consent_response.text

        save_response = session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "",
                "annotations": {
                    "age_consent:I agree": "I agree",
                    "info_consent:Yes": "Yes",
                },
                "span_annotations": [],
            },
        )
        assert save_response.status_code == 200

        next_response = session.post(
            f"{self.server.base_url}/annotate",
            json={"action": "next_instance", "instance_id": "phase_item_1"},
            allow_redirects=True,
        )
        assert next_response.status_code == 200
        assert "How familiar are you with the internet?" in next_response.text
        assert "Are you at least 18 years old?" not in next_response.text
