"""
Regression tests for GitHub issue #154.

The documented "modern" `phases` config uses file-based phases whose names
are canonical phase types (consent, prestudy, instructions, annotation,
poststudy) but does not always include an explicit `type:` field. Previously
the phase loader raised "Phase <name> does not have a type", caught it, and
silently skipped the phase — so a config copied verbatim from the docs booted
but the surveyflow did not work.

These tests boot a server with the docs-style, type-less config and assert
the phase is actually active (its questions render), not skipped.
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
    path = Path(test_dir) / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schemes, f, indent=2)
    return filename


class TestPhaseTypeInference:
    """A docs-style config with type-less, canonically named phases must work."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("phase_type_inference_test")

        test_data = [
            {"id": "item_1", "text": "First item for inference testing."},
            {"id": "item_2", "text": "Second item for inference testing."},
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "phase_rating",
                "annotation_type": "radio",
                "labels": ["1", "2", "3"],
                "description": "Rate the quality of this text.",
            }
        ]

        consent_file = _write_phase_scheme_file(
            test_dir,
            "consent_phase.json",
            [
                {
                    "name": "age_consent",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "INFERENCE_CONSENT_MARKER are you at least 18?",
                }
            ],
        )

        # Note: phases intentionally OMIT `type:` — names are canonical so
        # the loader must infer the type from the phase name.
        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Phase Type Inference Test",
            require_password=False,
            phases={
                "order": ["consent", "annotation"],
                "consent": {"file": consent_file},
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

    def test_typeless_consent_phase_is_active_not_skipped(self):
        """The consent phase (no `type:`) must render, not be silently skipped."""
        session = requests.Session()
        user_data = {"email": "inference_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/")
        assert response.status_code == 200
        # If the phase were skipped (the old bug), the user would land
        # straight on the annotation task and this marker would be absent.
        assert "INFERENCE_CONSENT_MARKER" in response.text

    def test_annotation_phase_still_reachable(self):
        """Sanity: annotation phase still works alongside an inferred phase."""
        session = requests.Session()
        user_data = {"email": "inference_user_2", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200
