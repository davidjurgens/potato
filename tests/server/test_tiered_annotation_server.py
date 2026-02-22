#!/usr/bin/env python3
"""
Server-side integration tests for tiered annotation.

Tests the complete server-side functionality including:
- Configuration loading and validation
- Schema generation via Flask routes
- API endpoints for tiered annotation
- Annotation persistence and retrieval
- Export functionality
"""

import pytest
import json
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)
from tests.helpers.port_manager import find_free_port


class TestTieredAnnotationServerConfig:
    """Test tiered annotation configuration on server side."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up test server with tiered annotation config."""
        test_dir = create_test_directory("tiered_annotation_server_test")

        # Create sample data with audio URLs
        test_data = [
            {
                "id": "audio_001",
                "text": "Sample audio for tiered annotation",
                "audio_url": "https://upload.wikimedia.org/wikipedia/commons/2/21/Speakertest.ogg"
            },
            {
                "id": "audio_002",
                "text": "Another audio sample",
                "audio_url": "https://upload.wikimedia.org/wikipedia/commons/2/21/Speakertest.ogg"
            }
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create tiered annotation scheme
        annotation_schemes = [
            {
                "annotation_type": "tiered_annotation",
                "name": "linguistic_tiers",
                "description": "Multi-tier linguistic annotation",
                "source_field": "audio_url",
                "media_type": "audio",
                "tiers": [
                    {
                        "name": "utterance",
                        "tier_type": "independent",
                        "description": "Speaker utterances",
                        "labels": [
                            {"name": "Speaker_A", "color": "#4ECDC4"},
                            {"name": "Speaker_B", "color": "#FF6B6B"}
                        ]
                    },
                    {
                        "name": "word",
                        "tier_type": "dependent",
                        "parent_tier": "utterance",
                        "constraint_type": "time_subdivision",
                        "description": "Word-level transcription",
                        "labels": [
                            {"name": "Content", "color": "#95E1D3"},
                            {"name": "Function", "color": "#AA96DA"}
                        ]
                    },
                    {
                        "name": "gesture",
                        "tier_type": "independent",
                        "description": "Non-verbal gestures",
                        "labels": [
                            {"name": "Nod", "color": "#DDA0DD"},
                            {"name": "Point", "color": "#87CEEB"}
                        ]
                    }
                ],
                "tier_height": 50,
                "zoom_enabled": True,
                "playback_rate_control": True
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Tiered Annotation Server Test",
            require_password=False,
            item_properties={"id_key": "id", "text_key": "text", "audio_key": "audio_url"}
        )

        port = find_free_port()
        server = FlaskTestServer(port=port, config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_tiered_annotation_page_loads(self):
        """Test that tiered annotation page loads successfully."""
        session = requests.Session()
        user_data = {"email": "tiered_user_1", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        # Verify tiered annotation HTML is present
        html = response.text
        assert 'tiered-annotation-container' in html or 'data-annotation-type="tiered_annotation"' in html

    def test_tiered_annotation_schema_in_response(self):
        """Test that tiered annotation schema markup is in the page."""
        session = requests.Session()
        user_data = {"email": "tiered_user_2", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        html = response.text

        # Check for schema-specific elements
        assert 'linguistic_tiers' in html
        assert 'tier-select' in html or 'tier-toolbar' in html

    def test_tiered_annotation_submit(self):
        """Test submitting a tiered annotation."""
        session = requests.Session()
        user_data = {"email": "tiered_annotator_1", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # First navigate to annotate page to get the instance
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        # Submit a tiered annotation
        annotation_data = {
            "annotations": {
                "utterance": [
                    {
                        "id": "ann_1",
                        "tier": "utterance",
                        "start_time": 0,
                        "end_time": 2000,
                        "label": "Speaker_A",
                        "color": "#4ECDC4"
                    }
                ],
                "word": [
                    {
                        "id": "ann_2",
                        "tier": "word",
                        "start_time": 0,
                        "end_time": 1000,
                        "label": "Content",
                        "parent_id": "ann_1",
                        "color": "#95E1D3"
                    }
                ],
                "gesture": []
            },
            "time_slots": {
                "ts1": 0,
                "ts2": 1000,
                "ts3": 2000
            }
        }

        # Submit via updateinstance endpoint
        submit_data = {
            "instance_id": "audio_001",
            "linguistic_tiers": json.dumps(annotation_data)
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            data=submit_data
        )
        assert response.status_code == 200

    def test_tiered_annotation_persistence(self):
        """Test that tiered annotations persist across page loads."""
        session = requests.Session()
        user_data = {"email": "tiered_persist_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Navigate to annotation page
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        # Submit annotation
        annotation_data = {
            "annotations": {
                "utterance": [
                    {
                        "id": "persist_ann_1",
                        "tier": "utterance",
                        "start_time": 500,
                        "end_time": 1500,
                        "label": "Speaker_B"
                    }
                ],
                "word": [],
                "gesture": []
            }
        }

        submit_data = {
            "instance_id": "audio_001",
            "linguistic_tiers": json.dumps(annotation_data)
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            data=submit_data
        )
        assert response.status_code == 200

        # Reload page and check annotation is present
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        # The hidden input should contain our annotation
        html = response.text
        # Annotation data should be somewhere in the page (either in hidden input or script)
        assert "persist_ann_1" in html or "Speaker_B" in html

    def test_multiple_tier_submissions(self):
        """Test submitting annotations across multiple tiers."""
        session = requests.Session()
        user_data = {"email": "tiered_multi_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Navigate to annotation page
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        # Submit annotations on multiple tiers
        annotation_data = {
            "annotations": {
                "utterance": [
                    {
                        "id": "utt_1",
                        "tier": "utterance",
                        "start_time": 0,
                        "end_time": 3000,
                        "label": "Speaker_A"
                    },
                    {
                        "id": "utt_2",
                        "tier": "utterance",
                        "start_time": 4000,
                        "end_time": 6000,
                        "label": "Speaker_B"
                    }
                ],
                "word": [
                    {
                        "id": "word_1",
                        "tier": "word",
                        "start_time": 0,
                        "end_time": 1000,
                        "label": "Content",
                        "parent_id": "utt_1"
                    },
                    {
                        "id": "word_2",
                        "tier": "word",
                        "start_time": 1000,
                        "end_time": 2000,
                        "label": "Function",
                        "parent_id": "utt_1"
                    }
                ],
                "gesture": [
                    {
                        "id": "gest_1",
                        "tier": "gesture",
                        "start_time": 2000,
                        "end_time": 2500,
                        "label": "Nod"
                    }
                ]
            }
        }

        submit_data = {
            "instance_id": "audio_001",
            "linguistic_tiers": json.dumps(annotation_data)
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            data=submit_data
        )
        assert response.status_code == 200


class TestTieredAnnotationConfigValidation:
    """Test tiered annotation config validation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up for each test."""
        self.test_dirs = []
        yield
        for test_dir in self.test_dirs:
            cleanup_test_directory(test_dir)

    def _create_server_with_config(self, annotation_schemes):
        """Helper to create a server with given annotation schemes."""
        test_dir = create_test_directory("tiered_config_validation")
        self.test_dirs.append(test_dir)

        test_data = [{"id": "test_1", "text": "Test", "audio_url": "http://example.com/audio.mp3"}]
        data_file = create_test_data_file(test_dir, test_data)

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            require_password=False
        )

        port = find_free_port()
        server = FlaskTestServer(port=port, config_file=config_file, debug=False)
        return server

    def test_valid_tiered_config_starts(self):
        """Test that a valid tiered annotation config starts successfully."""
        annotation_schemes = [
            {
                "annotation_type": "tiered_annotation",
                "name": "valid_tiers",
                "description": "Valid tiered annotation",
                "source_field": "audio_url",
                "tiers": [
                    {"name": "tier1", "tier_type": "independent", "labels": ["Label1"]}
                ]
            }
        ]

        server = self._create_server_with_config(annotation_schemes)
        try:
            started = server.start()
            assert started, "Server should start with valid config"

            # Verify we can access the page
            session = requests.Session()
            session.post(f"{server.base_url}/register", data={"email": "test_user"})
            session.post(f"{server.base_url}/auth", data={"email": "test_user"})
            response = session.get(f"{server.base_url}/annotate")
            assert response.status_code == 200
        finally:
            server.stop()

    def test_nested_hierarchy_config(self):
        """Test a deeply nested tier hierarchy."""
        annotation_schemes = [
            {
                "annotation_type": "tiered_annotation",
                "name": "nested_tiers",
                "description": "Nested tier annotation",
                "source_field": "audio_url",
                "tiers": [
                    {"name": "level1", "tier_type": "independent", "labels": ["L1"]},
                    {"name": "level2", "tier_type": "dependent", "parent_tier": "level1",
                     "constraint_type": "time_subdivision", "labels": ["L2"]},
                    {"name": "level3", "tier_type": "dependent", "parent_tier": "level2",
                     "constraint_type": "time_subdivision", "labels": ["L3"]}
                ]
            }
        ]

        server = self._create_server_with_config(annotation_schemes)
        try:
            started = server.start()
            assert started, "Server should start with nested hierarchy"

            session = requests.Session()
            session.post(f"{server.base_url}/register", data={"email": "nested_user"})
            session.post(f"{server.base_url}/auth", data={"email": "nested_user"})
            response = session.get(f"{server.base_url}/annotate")
            assert response.status_code == 200

            # Check all tiers are in the HTML
            html = response.text
            assert "level1" in html
            assert "level2" in html
            assert "level3" in html
        finally:
            server.stop()


class TestTieredAnnotationAPI:
    """Test tiered annotation specific API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up test server for API tests."""
        test_dir = create_test_directory("tiered_annotation_api_test")

        test_data = [
            {"id": "api_001", "text": "API test audio", "audio_url": "http://example.com/test.mp3"}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "tiered_annotation",
                "name": "api_tiers",
                "description": "API test tiers",
                "source_field": "audio_url",
                "tiers": [
                    {"name": "parent_tier", "tier_type": "independent",
                     "labels": [{"name": "P1", "color": "#FF0000"}]},
                    {"name": "child_tier", "tier_type": "dependent", "parent_tier": "parent_tier",
                     "constraint_type": "included_in",
                     "labels": [{"name": "C1", "color": "#00FF00"}]}
                ]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            require_password=False
        )

        port = find_free_port()
        server = FlaskTestServer(port=port, config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_health_endpoint(self):
        """Test that health endpoint works."""
        response = requests.get(f"{self.server.base_url}/")
        # Should redirect to login or return OK
        assert response.status_code in [200, 302]

    def test_annotation_json_format(self):
        """Test that annotations are saved in correct JSON format."""
        session = requests.Session()
        user_data = {"email": "json_format_user"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Navigate to get instance
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        # Create and submit annotation
        annotation_data = {
            "annotations": {
                "parent_tier": [
                    {
                        "id": "p_1",
                        "tier": "parent_tier",
                        "start_time": 0,
                        "end_time": 5000,
                        "label": "P1",
                        "color": "#FF0000"
                    }
                ],
                "child_tier": [
                    {
                        "id": "c_1",
                        "tier": "child_tier",
                        "start_time": 1000,
                        "end_time": 3000,
                        "label": "C1",
                        "parent_id": "p_1",
                        "color": "#00FF00"
                    }
                ]
            },
            "time_slots": {
                "ts1": 0,
                "ts2": 1000,
                "ts3": 3000,
                "ts4": 5000
            }
        }

        submit_data = {
            "instance_id": "api_001",
            "api_tiers": json.dumps(annotation_data)
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            data=submit_data
        )
        assert response.status_code == 200

        # Verify by reloading
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

    def test_empty_annotation_submission(self):
        """Test submitting empty annotations."""
        session = requests.Session()
        user_data = {"email": "empty_annotation_user"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        # Submit empty annotation
        annotation_data = {
            "annotations": {
                "parent_tier": [],
                "child_tier": []
            }
        }

        submit_data = {
            "instance_id": "api_001",
            "api_tiers": json.dumps(annotation_data)
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            data=submit_data
        )
        assert response.status_code == 200


class TestTieredAnnotationExport:
    """Test tiered annotation export functionality."""

    def test_eaf_exporter_can_handle_tiered(self):
        """Test that EAF exporter can handle tiered annotation context."""
        from potato.export.eaf_exporter import EAFExporter
        from potato.export.base import ExportContext

        exporter = EAFExporter()

        # Context with tiered_annotation schema
        context = ExportContext(
            config={},
            annotations=[],
            items={},
            schemas=[
                {"annotation_type": "tiered_annotation", "name": "test"}
            ],
            output_dir="/tmp"
        )

        can_export, reason = exporter.can_export(context)
        assert can_export is True

    def test_eaf_exporter_rejects_non_tiered(self):
        """Test that EAF exporter rejects non-tiered annotation context."""
        from potato.export.eaf_exporter import EAFExporter
        from potato.export.base import ExportContext

        exporter = EAFExporter()

        context = ExportContext(
            config={},
            annotations=[],
            items={},
            schemas=[
                {"annotation_type": "radio", "name": "test"}
            ],
            output_dir="/tmp"
        )

        can_export, reason = exporter.can_export(context)
        assert can_export is False
        assert "tiered_annotation" in reason.lower()

    def test_textgrid_exporter_can_handle_tiered(self):
        """Test that TextGrid exporter can handle tiered annotation context."""
        from potato.export.textgrid_exporter import TextGridExporter
        from potato.export.base import ExportContext

        exporter = TextGridExporter()

        context = ExportContext(
            config={},
            annotations=[],
            items={},
            schemas=[
                {"annotation_type": "tiered_annotation", "name": "test"}
            ],
            output_dir="/tmp"
        )

        can_export, reason = exporter.can_export(context)
        assert can_export is True


class TestTieredAnnotationWithOtherSchemas:
    """Test tiered annotation combined with other schema types."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up test server with mixed schemas."""
        test_dir = create_test_directory("tiered_mixed_schemas_test")

        test_data = [
            {"id": "mixed_001", "text": "Mixed schema test", "audio_url": "http://example.com/test.mp3"}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create config with tiered annotation and radio buttons
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "quality",
                "description": "Rate the audio quality",
                "labels": ["good", "bad", "unclear"]
            },
            {
                "annotation_type": "tiered_annotation",
                "name": "speech_tiers",
                "description": "Annotate speech segments",
                "source_field": "audio_url",
                "tiers": [
                    {"name": "speech", "tier_type": "independent",
                     "labels": [{"name": "Speech", "color": "#4ECDC4"}]}
                ]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            require_password=False
        )

        port = find_free_port()
        server = FlaskTestServer(port=port, config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_mixed_schemas_page_loads(self):
        """Test that page with multiple schema types loads."""
        session = requests.Session()
        user_data = {"email": "mixed_user"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        html = response.text
        # Both schemas should be present
        assert "quality" in html
        assert "speech_tiers" in html

    def test_submit_both_schema_types(self):
        """Test submitting annotations for both schema types."""
        session = requests.Session()
        user_data = {"email": "mixed_submit_user"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

        # Submit both annotation types
        tiered_data = {
            "annotations": {
                "speech": [
                    {"id": "s1", "tier": "speech", "start_time": 0, "end_time": 2000, "label": "Speech"}
                ]
            }
        }

        submit_data = {
            "instance_id": "mixed_001",
            "quality": "good",
            "speech_tiers": json.dumps(tiered_data)
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            data=submit_data
        )
        assert response.status_code == 200
