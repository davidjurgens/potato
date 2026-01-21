#!/usr/bin/env python3
"""
Server tests for video annotation API routes.

Tests the video metadata and waveform generation endpoints.
"""

import pytest
import json
import os
import tempfile
import requests

# Skip these tests for fast CI execution - they require spinning up full server
pytestmark = pytest.mark.skip(reason="Server integration tests skipped for fast CI execution")

from tests.helpers.flask_test_setup import FlaskTestServer


class TestVideoAnnotationRoutes:
    """Tests for video annotation API routes."""

    @pytest.fixture(autouse=True)
    def setup_server(self, request):
        """Set up test server with video annotation config."""
        # Create a temporary config for video annotation
        self.temp_dir = tempfile.mkdtemp()

        # Create sample data file
        data_file = os.path.join(self.temp_dir, "video_data.json")
        with open(data_file, "w") as f:
            json.dump([
                {
                    "id": "video_001",
                    "video_url": "https://www.w3schools.com/html/mov_bbb.mp4",
                    "title": "Test Video"
                }
            ], f)

        # Create config file
        config_file = os.path.join(self.temp_dir, "video_config.yaml")
        config_content = f"""
port: 0
server_name: test_video_annotation
annotation_task_name: Video Annotation Test
task_dir: {self.temp_dir}
output_annotation_dir: {os.path.join(self.temp_dir, 'output')}
output_annotation_format: json

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: video_url

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: video_annotation
    name: video_segments
    description: "Test video annotation"
    mode: segment
    labels:
      - name: intro
        color: "#4ECDC4"
        key_value: "1"
      - name: content
        color: "#FF6B6B"
        key_value: "2"
    min_segments: 0
    timeline_height: 70
    playback_rate_control: true
    frame_stepping: true
    show_timecode: true
    video_fps: 30

site_dir: default
"""
        with open(config_file, "w") as f:
            f.write(config_content)

        self.server = FlaskTestServer(config_file=config_file, port=0)
        self.server.start()
        self.base_url = self.server.base_url
        self.session = requests.Session()

        # Login
        self.session.post(f"{self.base_url}/login", data={"username": "test_user"})

        yield

        self.server.stop()
        # Clean up temp files
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_video_metadata_endpoint_exists(self):
        """Test that the video metadata endpoint exists and responds."""
        response = self.session.post(
            f"{self.base_url}/api/video/metadata",
            json={"video_url": "https://example.com/video.mp4"},
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"
        assert "use_client_detection" in data

    def test_video_metadata_missing_url(self):
        """Test that missing video_url returns error."""
        response = self.session.post(
            f"{self.base_url}/api/video/metadata",
            json={},
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_video_waveform_endpoint_exists(self):
        """Test that the video waveform endpoint exists and responds."""
        response = self.session.post(
            f"{self.base_url}/api/video/waveform/generate",
            json={"video_url": "https://example.com/video.mp4"},
            headers={"Content-Type": "application/json"}
        )

        # Should return a status (may be unavailable if audiowaveform not installed)
        assert response.status_code == 200
        data = response.json()
        assert "status" in data or "use_client_fallback" in data

    def test_video_waveform_missing_url(self):
        """Test that missing video_url returns error."""
        response = self.session.post(
            f"{self.base_url}/api/video/waveform/generate",
            json={},
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_video_annotation_form_renders(self):
        """Test that the video annotation form is rendered in the page."""
        response = self.session.get(f"{self.base_url}/")

        assert response.status_code == 200
        html = response.text

        # Check that video annotation elements are present
        assert 'video-annotation' in html
        assert 'video_segments' in html  # Schema name
        assert 'data-mode="segment"' in html

    def test_video_annotation_includes_labels(self):
        """Test that video annotation includes configured labels."""
        response = self.session.get(f"{self.base_url}/")

        assert response.status_code == 200
        html = response.text

        # Check that labels are present
        assert 'intro' in html
        assert 'content' in html
        assert '#4ECDC4' in html  # intro color
        assert '#FF6B6B' in html  # content color

    def test_video_annotation_includes_controls(self):
        """Test that video annotation includes expected controls."""
        response = self.session.get(f"{self.base_url}/")

        assert response.status_code == 200
        html = response.text

        # Check that controls are present
        assert 'playback-rate-select' in html  # playback rate control
        assert 'data-action="frame-back"' in html  # frame stepping
        assert 'data-action="frame-forward"' in html
        assert 'data-action="set-start"' in html  # segment controls
        assert 'data-action="set-end"' in html
        assert 'data-action="create-segment"' in html


class TestVideoAnnotationSubmission:
    """Tests for video annotation data submission."""

    @pytest.fixture(autouse=True)
    def setup_server(self, request):
        """Set up test server with video annotation config."""
        self.temp_dir = tempfile.mkdtemp()

        # Create sample data file
        data_file = os.path.join(self.temp_dir, "video_data.json")
        with open(data_file, "w") as f:
            json.dump([
                {
                    "id": "video_001",
                    "video_url": "https://www.w3schools.com/html/mov_bbb.mp4",
                    "title": "Test Video"
                }
            ], f)

        # Create config file
        config_file = os.path.join(self.temp_dir, "video_config.yaml")
        config_content = f"""
port: 0
server_name: test_video_submission
annotation_task_name: Video Submission Test
task_dir: {self.temp_dir}
output_annotation_dir: {os.path.join(self.temp_dir, 'output')}
output_annotation_format: json

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: video_url

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: video_annotation
    name: video_test
    description: "Test video annotation"
    mode: segment
    labels:
      - name: intro
        color: "#4ECDC4"
      - name: content
        color: "#FF6B6B"
    min_segments: 0

site_dir: default
"""
        with open(config_file, "w") as f:
            f.write(config_content)

        self.server = FlaskTestServer(config_file=config_file, port=0)
        self.server.start()
        self.base_url = self.server.base_url
        self.session = requests.Session()

        # Login
        self.session.post(f"{self.base_url}/login", data={"username": "test_user"})

        yield

        self.server.stop()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_submit_video_annotation(self):
        """Test that video annotation data can be submitted."""
        # First, get the page to ensure session is set up
        response = self.session.get(f"{self.base_url}/")
        assert response.status_code == 200

        # Submit annotation data
        annotation_data = {
            "video_metadata": {
                "duration": 10.0,
                "fps": 30,
                "width": 640,
                "height": 360
            },
            "segments": [
                {
                    "id": "segment_1",
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "start_frame": 0,
                    "end_frame": 150,
                    "label": "intro"
                }
            ],
            "frame_annotations": {},
            "keyframes": [],
            "tracking": {}
        }

        # Submit using the annotate_all endpoint
        response = self.session.post(
            f"{self.base_url}/annotate_all",
            data={
                "video_test": json.dumps(annotation_data)
            }
        )

        # Should succeed (either 200 or redirect 302)
        assert response.status_code in [200, 302]

    def test_empty_annotation_allowed_with_min_segments_zero(self):
        """Test that empty annotation is allowed when min_segments is 0."""
        response = self.session.get(f"{self.base_url}/")
        assert response.status_code == 200

        # Submit empty annotation
        annotation_data = {
            "video_metadata": {},
            "segments": [],
            "frame_annotations": {},
            "keyframes": [],
            "tracking": {}
        }

        response = self.session.post(
            f"{self.base_url}/annotate_all",
            data={
                "video_test": json.dumps(annotation_data)
            }
        )

        # Should succeed
        assert response.status_code in [200, 302]
