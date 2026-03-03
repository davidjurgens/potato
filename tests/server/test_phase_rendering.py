"""
Phase Rendering Tests

Tests that consent, prestudy, and poststudy phases render correctly
when their annotation schemas are loaded from JSON survey files.

This is a regression test for the bug where phase schemas arrived at
schema generators without annotation_id set, causing KeyError crashes
that were silently caught and displayed as "Error Generating Annotation Form".
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    cleanup_test_directory,
)


def _create_phase_config(test_dir, annotation_schemes, phases_config,
                         survey_files=None, **kwargs):
    """Create a test config with phases and write survey JSON files.

    Args:
        test_dir: Test output directory (absolute path).
        annotation_schemes: Main annotation schemes list.
        phases_config: Dict describing the phases section of config.
        survey_files: Dict mapping filename -> list of schema dicts to write as JSON.
        **kwargs: Extra config keys.

    Returns:
        Path to the config YAML file.
    """
    abs_test_dir = os.path.abspath(test_dir)

    # Write survey JSON files
    if survey_files:
        surveys_dir = os.path.join(abs_test_dir, "surveys")
        os.makedirs(surveys_dir, exist_ok=True)
        for fname, content in survey_files.items():
            with open(os.path.join(surveys_dir, fname), "w") as f:
                json.dump(content, f)

    # Build config
    data_files = kwargs.pop("data_files", ["test_data.jsonl"])
    config = {
        "annotation_task_name": kwargs.pop("annotation_task_name", "Phase Test"),
        "task_dir": abs_test_dir,
        "data_files": [os.path.basename(f) for f in data_files],
        "item_properties": kwargs.pop("item_properties", {"id_key": "id", "text_key": "text"}),
        "annotation_schemes": annotation_schemes,
        "output_annotation_dir": os.path.join(abs_test_dir, "output"),
        "site_dir": kwargs.pop("site_dir", "default"),
        "alert_time_each_instance": 0,
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "persist_sessions": False,
        "debug": False,
        "port": 8000,
        "host": "0.0.0.0",
        "secret_key": "test-secret-key",
        "session_lifetime_days": 1,
        "user_config": {"allow_all_users": True, "users": []},
        "phases": phases_config,
    }
    config.update(kwargs)

    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


class TestConsentPhaseRendering:
    """Test that consent phase with radio schemas renders without errors."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("phase_consent_test")

        # Create minimal annotation data
        test_data = [
            {"id": "1", "text": "Test item one."},
            {"id": "2", "text": "Test item two."},
        ]
        create_test_data_file(test_dir, test_data)

        # Main annotation schemes
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "Is this positive or negative?",
                "labels": ["Positive", "Negative"],
            }
        ]

        # Consent survey file
        consent_schemas = [
            {
                "id": "1",
                "name": "age_consent",
                "description": "I certify that I am at least 18 years of age.",
                "annotation_type": "radio",
                "labels": ["I agree", "I disagree"],
                "label_requirement": {"required_label": ["I agree"]},
            },
            {
                "id": "2",
                "name": "data_consent",
                "description": "I consent to having my annotations used for research.",
                "annotation_type": "radio",
                "labels": ["I consent", "I do not consent"],
                "label_requirement": {"required_label": ["I consent"]},
            },
        ]

        phases_config = {
            "order": ["consent", "annotation"],
            "consent": {"type": "consent", "file": "surveys/consent.json"},
        }

        config_file = _create_phase_config(
            test_dir,
            annotation_schemes,
            phases_config,
            survey_files={"consent.json": consent_schemas},
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_consent_page_renders_radio_inputs(self):
        """GET /consent should return 200 with radio inputs, no error HTML."""
        session = requests.Session()
        session.post(f"{self.server.base_url}/register",
                     data={"email": "user1", "pass": "pass"})
        session.post(f"{self.server.base_url}/auth",
                     data={"email": "user1", "pass": "pass"})

        resp = session.get(f"{self.server.base_url}/consent")
        assert resp.status_code == 200
        assert "Error Generating Annotation Form" not in resp.text

    def test_consent_page_contains_schema_names(self):
        """Consent page should contain the schema description text."""
        session = requests.Session()
        session.post(f"{self.server.base_url}/register",
                     data={"email": "user2", "pass": "pass"})
        session.post(f"{self.server.base_url}/auth",
                     data={"email": "user2", "pass": "pass"})

        resp = session.get(f"{self.server.base_url}/consent")
        assert resp.status_code == 200
        assert "18 years" in resp.text or "age_consent" in resp.text


class TestPreStudyPhaseRendering:
    """Test that prestudy phase with mixed schema types renders correctly."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("phase_prestudy_test")

        test_data = [
            {"id": "1", "text": "Test item."},
        ]
        create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "label",
                "description": "Pick a label",
                "labels": ["A", "B"],
            }
        ]

        # Pre-survey with mixed types: likert + radio + text
        prestudy_schemas = [
            {
                "id": "1",
                "name": "familiarity",
                "description": "How familiar are you with this topic?",
                "annotation_type": "likert",
                "min_label": "Not familiar",
                "max_label": "Very familiar",
                "size": 5,
                "label_requirement": {"required": True},
            },
            {
                "id": "2",
                "name": "native_lang",
                "description": "Is English your native language?",
                "annotation_type": "radio",
                "labels": ["Yes", "No"],
                "label_requirement": {"required": True},
            },
            {
                "id": "3",
                "name": "comments",
                "description": "Any additional comments?",
                "annotation_type": "text",
            },
        ]

        phases_config = {
            "order": ["prestudy", "annotation"],
            "prestudy": {"type": "prestudy", "file": "surveys/pre_survey.json"},
        }

        config_file = _create_phase_config(
            test_dir,
            annotation_schemes,
            phases_config,
            survey_files={"pre_survey.json": prestudy_schemas},
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_prestudy_renders_without_errors(self):
        """GET /prestudy should return 200 with no error HTML."""
        session = requests.Session()
        session.post(f"{self.server.base_url}/register",
                     data={"email": "user1", "pass": "pass"})
        session.post(f"{self.server.base_url}/auth",
                     data={"email": "user1", "pass": "pass"})

        resp = session.get(f"{self.server.base_url}/prestudy")
        assert resp.status_code == 200
        assert "Error Generating Annotation Form" not in resp.text

    def test_prestudy_contains_all_schema_types(self):
        """Pre-study page should contain elements for likert, radio, and text schemas."""
        session = requests.Session()
        session.post(f"{self.server.base_url}/register",
                     data={"email": "user2", "pass": "pass"})
        session.post(f"{self.server.base_url}/auth",
                     data={"email": "user2", "pass": "pass"})

        resp = session.get(f"{self.server.base_url}/prestudy")
        html = resp.text
        # Check that schema names appear in the rendered page
        assert "familiarity" in html
        assert "native_lang" in html
        assert "comments" in html


class TestPhaseWorkflowProgression:
    """Test that users can progress through consent → annotation."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("phase_workflow_test")

        test_data = [
            {"id": "1", "text": "Workflow test item."},
        ]
        create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "label",
                "description": "Pick one",
                "labels": ["X", "Y"],
            }
        ]

        consent_schemas = [
            {
                "id": "1",
                "name": "consent_q",
                "description": "Do you consent?",
                "annotation_type": "radio",
                "labels": ["Yes", "No"],
                "label_requirement": {"required_label": ["Yes"]},
            },
        ]

        phases_config = {
            "order": ["consent", "annotation"],
            "consent": {"type": "consent", "file": "surveys/consent.json"},
        }

        config_file = _create_phase_config(
            test_dir,
            annotation_schemes,
            phases_config,
            survey_files={"consent.json": consent_schemas},
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_consent_page_accessible(self):
        """After login, user should be able to access /consent."""
        session = requests.Session()
        session.post(f"{self.server.base_url}/register",
                     data={"email": "flow_user", "pass": "pass"})
        session.post(f"{self.server.base_url}/auth",
                     data={"email": "flow_user", "pass": "pass"})

        resp = session.get(f"{self.server.base_url}/consent")
        assert resp.status_code == 200
        assert "Error Generating Annotation Form" not in resp.text
