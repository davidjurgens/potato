"""
Annotation Type-Specific Workflow Tests

This module contains tests for different annotation types and their specific behaviors,
including validation, key bindings, and data capture.
"""

import pytest
import requests
import os
from tests.helpers.flask_test_setup import FlaskTestServer

def get_config_path(config_name):
    return os.path.abspath(os.path.join(os.path.dirname(__file__), f'../configs/{config_name}'))

class TestAnnotationTypesWorkflow:
    """Test different annotation types and their workflows."""

    def test_likert_annotation_workflow(self):
        config_file = get_config_path('likert-annotation.yaml')
        server = FlaskTestServer(lambda: create_app(), config_file, debug=True)
        server.start()
        server_url = server.base_url
        try:
            # Use the production registration endpoint
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register",
                                   data=user_data,
                                   timeout=10)
            assert response.status_code == 200

            # Create a session to maintain login state
            session = requests.Session()
            session.post(f"{server_url}/auth", data=user_data)

            response = requests.get(f"{server_url}/admin/user_state/test_user",

                                  headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()
            print(f"User state: {user_state}")

            # Get assigned items from user state
            assigned_items = user_state["assignments"]["items"]
            print(f"Assigned items: {assigned_items}")
            assert len(assigned_items) > 0, f"No items assigned to user. User state: {user_state}"

            annotation_data = {
                "instance_id": assigned_items[0]["id"],
                "type": "label",
                "schema": "likert_scale",
                "state": [
                    {"name": "likert_rating", "value": "3"}
                ]
            }
            response = session.post(f"{server_url}/updateinstance", json=annotation_data, timeout=10)
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "success"
        finally:
            server.stop()

    def test_radio_annotation_workflow(self):
        config_file = get_config_path('radio-annotation.yaml')
        server = FlaskTestServer(lambda: create_app(), config_file, debug=True)
        server.start()
        server_url = server.base_url
        try:
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register",
                                   data=user_data,

                                   headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200

            response = requests.get(f"{server_url}/admin/user_state/test_user",

                                  headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()
            assert user_state["user_id"] == "test_user"
        finally:
            server.stop()

    def test_slider_annotation_workflow(self):
        config_file = get_config_path('slider-annotation.yaml')
        server = FlaskTestServer(lambda: create_app(), config_file, debug=True)
        server.start()
        server_url = server.base_url
        try:
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register",
                                   data=user_data,

                                   headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200

            response = requests.get(f"{server_url}/admin/user_state/test_user",

                                  headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()
            assert user_state["user_id"] == "test_user"
        finally:
            server.stop()

    def test_text_annotation_workflow(self):
        config_file = get_config_path('text-annotation.yaml')
        server = FlaskTestServer(lambda: create_app(), config_file, debug=True)
        server.start()
        server_url = server.base_url
        try:
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register",
                                   data=user_data,

                                   headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200

            response = requests.get(f"{server_url}/admin/user_state/test_user",

                                  headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()
            assert user_state["user_id"] == "test_user"
        finally:
            server.stop()

    def test_span_annotation_workflow(self):
        config_file = get_config_path('span-annotation.yaml')
        server = FlaskTestServer(lambda: create_app(), config_file, debug=True)
        server.start()
        server_url = server.base_url
        try:
            user_data = {"email": "test_user", "pass": "test_password"}
            response = requests.post(f"{server_url}/register",
                                   data=user_data,

                                   headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200

            response = requests.get(f"{server_url}/admin/user_state/test_user",

                                  headers={"X-API-Key": "admin_api_key"}, timeout=10)
            assert response.status_code == 200
            user_state = response.json()
            assert user_state["user_id"] == "test_user"
        finally:
            server.stop()

def create_app():
    from potato.flask_server import create_app
    return create_app()