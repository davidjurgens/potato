"""Tests for header_logo support in front_end.py."""

import base64
import os
import tempfile

import pytest

from potato.server_utils.front_end import (
    resolve_header_logo_src,
    SUPPORTED_HEADER_LOGO_EXTENSIONS,
)


@pytest.fixture
def logo_config(tmp_path):
    """Create a config dict with a small PNG logo file."""
    # Minimal valid 1x1 PNG
    png_data = (
        b'\x89PNG\r\n\x1a\n'
        b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx'
        b'\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00'
        b'\x00\x00\x00IEND\xaeB`\x82'
    )
    logo_file = tmp_path / "logo.png"
    logo_file.write_bytes(png_data)
    config_file = tmp_path / "config.yaml"
    config_file.write_text("annotation_task_name: test")
    return {
        "__config_file__": str(config_file),
        "header_logo": str(logo_file),
    }, png_data


class TestResolveHeaderLogoSrc:
    def test_png_returns_data_url(self, logo_config):
        config, png_data = logo_config
        result = resolve_header_logo_src(config)
        assert result.startswith("data:image/png;base64,")
        # Verify the base64 payload round-trips
        encoded_part = result.split(",", 1)[1]
        assert base64.b64decode(encoded_part) == png_data

    def test_http_url_passes_through(self):
        config = {"header_logo": "https://example.com/logo.png"}
        result = resolve_header_logo_src(config)
        assert result == "https://example.com/logo.png"

    def test_not_configured_returns_empty(self):
        config = {}
        result = resolve_header_logo_src(config)
        assert result == ""

    def test_unsupported_extension_returns_empty(self, tmp_path):
        bad_file = tmp_path / "logo.exe"
        bad_file.write_bytes(b"\x00")
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        config = {
            "__config_file__": str(config_file),
            "header_logo": str(bad_file),
        }
        result = resolve_header_logo_src(config)
        assert result == ""

    def test_missing_file_returns_empty(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        config = {
            "__config_file__": str(config_file),
            "header_logo": "/nonexistent/logo.png",
        }
        result = resolve_header_logo_src(config)
        assert result == ""

    def test_jpeg_extension(self, tmp_path):
        jpg_file = tmp_path / "logo.jpg"
        jpg_file.write_bytes(b"\xff\xd8\xff")
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        config = {
            "__config_file__": str(config_file),
            "header_logo": str(jpg_file),
        }
        result = resolve_header_logo_src(config)
        assert result.startswith("data:image/jpeg;base64,")

    def test_svg_extension(self, tmp_path):
        svg_file = tmp_path / "logo.svg"
        svg_file.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        config = {
            "__config_file__": str(config_file),
            "header_logo": str(svg_file),
        }
        result = resolve_header_logo_src(config)
        assert result.startswith("data:image/svg+xml;base64,")
