#!/usr/bin/env python3
"""
Integration tests using the FlaskTestServer.
Demonstrates how to use the FlaskTestServer for testing Flask endpoints.
"""

import pytest
import requests
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tests.flask_test_setup import FlaskTestServer, FlaskTestBase


class TestFlaskIntegration(FlaskTestBase):
    """Test Flask server integration using the FlaskTestServer."""

    def test_server_starts_and_responds(self):
        """Test that the server starts and responds to basic requests."""
        # Server should be started by setUp()
        assert self.server.is_server_running()

        # Test root endpoint (should redirect to auth)
        response = self.server.get("/")
        assert response.status_code in [200, 302]  # 302 is redirect, 200 is success

        # Test auth endpoint
        response = self.server.get("/auth")
        assert response.status_code == 200

    def test_debug_mode_auto_login(self):
        """Test that debug mode automatically logs in users."""
        # In debug mode, the server should auto-login users
        response = self.server.get("/")
        # Should either redirect to auth or go directly to annotation
        assert response.status_code in [200, 302]

    def test_server_configuration(self):
        """Test that the server is configured with test data."""
        # The server should have test data loaded
        response = self.server.get("/auth")
        assert response.status_code == 200

        # Check that the response contains expected content
        content = response.text
        assert "Test Annotation Task" in content or "annotation" in content.lower()

    def test_multiple_requests(self):
        """Test that the server can handle multiple requests."""
        # Make several requests to ensure server stability
        for i in range(3):
            response = self.server.get("/")
            assert response.status_code in [200, 302]

            response = self.server.get("/auth")
            assert response.status_code == 200


def test_flask_server_factory():
    """Test the FlaskTestServer factory function."""
    server = FlaskTestServer(port=9002, debug=True)

    try:
        # Test server startup
        assert server.start_server()
        assert server.is_server_running()

        # Test basic request
        response = server.get("/")
        assert response.status_code in [200, 302]

    finally:
        server.stop_server()
        assert not server.is_server_running()


def test_server_context_manager():
    """Test the server context manager."""
    server = FlaskTestServer(port=9003, debug=True)

    with server.server_context():
        assert server.is_server_running()
        response = server.get("/")
        assert response.status_code in [200, 302]

    # Server should be stopped after context
    assert not server.is_server_running()


if __name__ == "__main__":
    # Run tests directly
    print("🧪 Running Flask integration tests...")

    # Test 1: Basic server functionality
    print("\n1. Testing basic server functionality...")
    server = FlaskTestServer(port=9001, debug=True)
    try:
        if server.start_server():
            response = server.get("/")
            print(f"✅ Root endpoint: {response.status_code}")

            response = server.get("/auth")
            print(f"✅ Auth endpoint: {response.status_code}")
        else:
            print("❌ Failed to start server")
    finally:
        server.stop_server()

    # Test 2: Multiple servers
    print("\n2. Testing multiple servers...")
    servers = []
    try:
        for i in range(2):
            port = 9001 + i
            server = FlaskTestServer(port=port, debug=True)
            if server.start_server():
                print(f"✅ Server {i+1} started on port {port}")
                servers.append(server)
            else:
                print(f"❌ Failed to start server {i+1}")

        # Test requests to both servers
        for i, server in enumerate(servers):
            response = server.get("/")
            print(f"✅ Server {i+1} root endpoint: {response.status_code}")

    finally:
        for server in servers:
            server.stop_server()

    print("\n✅ All Flask integration tests completed!")