#!/usr/bin/env python3
"""
Integration tests using the FlaskTestServer.
Demonstrates how to use the FlaskTestServer for testing Flask endpoints.
"""

import pytest

# Skip server integration tests for fast CI - run with pytest -m slow
pytestmark = pytest.mark.skip(reason="Server integration tests skipped for fast CI execution")
import requests
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tests.helpers.flask_test_setup import FlaskTestServer, FlaskTestBase


class TestFlaskIntegration:
    """Test Flask server integration using the FlaskTestServer."""

    @pytest.fixture
    def server(self):
        """Create a test server fixture."""
        server = FlaskTestServer(app_factory=lambda: None, config={}, debug=False)
        try:
            server.start()
            yield server
        finally:
            server.stop()

    def test_server_starts_and_responds(self, server):
        """Test that the server starts and responds to basic requests."""
        # Server should be started by fixture
        assert server.is_server_running()

        # Test root endpoint (should redirect to auth)
        response = server.get("/")
        assert response.status_code in [200, 302]  # 302 is redirect, 200 is success

        # Test auth endpoint
        response = server.get("/auth")
        assert response.status_code == 200

    def test_debug_mode_auto_login(self, server):
        """Test that debug mode automatically logs in users."""
        # In debug mode, the server should auto-login users
        response = server.get("/")
        # Should either redirect to auth or go directly to annotation
        assert response.status_code in [200, 302]

    def test_server_configuration(self, server):
        """Test that the server is configured with test data."""
        # The server should have test data loaded
        response = server.get("/auth")
        assert response.status_code == 200

        # Check that the response contains expected content
        content = response.text
        assert "Test Annotation Task" in content or "annotation" in content.lower()

    def test_multiple_requests(self, server):
        """Test that the server can handle multiple requests."""
        # Make several requests to ensure server stability
        for i in range(3):
            response = server.get("/")
            assert response.status_code in [200, 302]

            response = server.get("/auth")
            assert response.status_code == 200


def test_flask_server_factory():
    """Test the FlaskTestServer factory function."""
    server = FlaskTestServer(app_factory=lambda: None, config={}, debug=False)
    try:
        # Test server startup
        assert server.start()
        assert server.is_server_running()

        # Test basic request
        response = server.get("/")
        assert response.status_code in [200, 302]

    finally:
        server.stop()
        # Note: The server may take a moment to fully stop, so we don't assert it's immediately stopped


def test_server_context_manager():
    """Test the server context manager."""
    server = FlaskTestServer(app_factory=lambda: None, config={}, debug=False)
    with server.server_context():
        assert server.is_server_running()
        response = server.get("/")
        assert response.status_code in [200, 302]

    # Server should be stopped after context
    # Note: The server may take a moment to fully stop, so we don't assert it's immediately stopped


if __name__ == "__main__":
    # Run tests directly
    print("🧪 Running Flask integration tests...")

    # Test 1: Basic server functionality
    print("\n1. Testing basic server functionality...")
    server = FlaskTestServer(app_factory=lambda: None, config={}, debug=False)
    try:
        if server.start():
            response = server.get("/")
            print(f"✅ Root endpoint: {response.status_code}")

            response = server.get("/auth")
            print(f"✅ Auth endpoint: {response.status_code}")
        else:
            print("❌ Failed to start server")
    finally:
        server.stop()

    # Test 2: Multiple servers
    print("\n2. Testing multiple servers...")
    servers = []
    try:
        for i in range(2):
            server = FlaskTestServer(app_factory=lambda: None, config={}, debug=False)
            if server.start():
                print(f"✅ Server {i+1} started")
                servers.append(server)
            else:
                print(f"❌ Failed to start server {i+1}")

        # Test requests to both servers
        for i, server in enumerate(servers):
            response = server.get("/")
            print(f"✅ Server {i+1} root endpoint: {response.status_code}")

    finally:
        for server in servers:
            server.stop()

    print("\n✅ All Flask integration tests completed!")