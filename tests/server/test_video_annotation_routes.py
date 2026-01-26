#!/usr/bin/env python3
"""
Server tests for video annotation API routes.

Tests the video metadata and waveform generation endpoints.
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestVideoAnnotationRoutes:
    """Tests for video annotation API routes."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up test server with video annotation config."""
        test_dir = create_test_directory("video_annotation_routes_test")

        # Create sample data file with video URLs
        test_data = [
            {
                "id": "video_001",
                "video_url": "https://www.w3schools.com/html/mov_bbb.mp4",
                "title": "Test Video"
            }
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create video annotation scheme
        annotation_schemes = [
            {
                "annotation_type": "video_annotation",
                "name": "video_segments",
                "description": "Test video annotation",
                "mode": "segment",
                "labels": [
                    {"name": "intro", "color": "#4ECDC4", "key_value": "1"},
                    {"name": "content", "color": "#FF6B6B", "key_value": "2"}
                ]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Video Annotation Test",
            require_password=False,
            item_properties={"id_key": "id", "text_key": "video_url"}
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_video_annotation_page_loads(self):
        """Test that video annotation page loads successfully."""
        session = requests.Session()
        user_data = {"email": "video_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

    def test_video_annotation_submit(self):
        """Test submitting a video annotation."""
        session = requests.Session()
        user_data = {"email": "video_annotator", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Submit a video annotation
        annotation_data = {
            "instance_id": "video_001",
            "type": "video_annotation",
            "schema": "video_segments",
            "state": [
                {"name": "intro", "start": 0, "end": 5}
            ]
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=annotation_data
        )
        assert response.status_code == 200
