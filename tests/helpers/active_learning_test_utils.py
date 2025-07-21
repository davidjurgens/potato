"""
Shared utilities for active learning tests in Potato.
Provides helpers for test data/config creation, user setup, annotation workflows, and server management.
"""

import os
import tempfile
import json
import yaml
from typing import List, Dict, Any, Optional
import requests
from tests.helpers.flask_test_setup import FlaskTestServer


def create_temp_test_data(items: List[dict], dir_path: str) -> str:
    """
    Create a temporary JSONL test data file in the given directory.
    Returns the file path.
    """
    os.makedirs(dir_path, exist_ok=True)
    data_file = os.path.join(dir_path, 'test_data.jsonl')
    with open(data_file, 'w') as f:
        for item in items:
            f.write(json.dumps(item) + '\n')
    return data_file


def create_temp_config(config: dict, dir_path: str) -> str:
    """
    Create a temporary YAML config file in the given directory.
    Returns the file path.
    """
    os.makedirs(dir_path, exist_ok=True)
    config_file = os.path.join(dir_path, 'test_config.yaml')
    with open(config_file, 'w') as f:
        yaml.dump(config, f)
    return config_file


def register_and_login_user(server: FlaskTestServer, email: str, password: str) -> requests.Session:
    """
    Register and log in a user, returning a requests.Session with authentication.
    """
    session = requests.Session()
    reg_resp = session.post(f"{server.base_url}/register", data={"email": email, "pass": password})
    assert reg_resp.status_code in [200, 302]
    login_resp = session.post(f"{server.base_url}/auth", data={"email": email, "pass": password})
    assert login_resp.status_code in [200, 302]
    return session


def submit_annotation(session: requests.Session, server: FlaskTestServer, instance_id: str, annotation_type: str, schema: str, state: list) -> requests.Response:
    """
    Submit an annotation for a given instance.
    """
    annotation_data = {
        "instance_id": instance_id,
        "type": annotation_type,
        "schema": schema,
        "state": state
    }
    resp = session.post(f"{server.base_url}/updateinstance", json=annotation_data)
    assert resp.status_code == 200
    return resp


def get_current_annotations(session: requests.Session, server: FlaskTestServer) -> dict:
    """
    Get current instance's annotations for the logged-in user.
    """
    resp = session.get(f"{server.base_url}/api/current_instance")
    assert resp.status_code == 200
    data = resp.json()
    return data.get('annotations', {})


def get_current_instance_id(session: requests.Session, server: FlaskTestServer) -> Optional[str]:
    """
    Get the current instance ID for the logged-in user.
    """
    resp = session.get(f"{server.base_url}/api/current_instance")
    assert resp.status_code == 200
    data = resp.json()
    return data.get('instance_id')


def simulate_annotation_workflow(server: FlaskTestServer, user_data: dict, annotation_data: List[dict]):
    """
    Simulate a user annotating a sequence of instances.
    user_data: {"email": ..., "pass": ...}
    annotation_data: list of {"instance_id", "type", "schema", "state"}
    """
    session = register_and_login_user(server, user_data["email"], user_data["pass"])
    for ann in annotation_data:
        submit_annotation(session, server, ann["instance_id"], ann["type"], ann["schema"], ann["state"])
    return session


def start_flask_server_with_config(config: dict, items: List[dict], port: int = 9009) -> FlaskTestServer:
    """
    Start a FlaskTestServer with the given config and data items.
    Returns the server instance.
    """
    temp_dir = tempfile.mkdtemp()
    data_file = create_temp_test_data(items, temp_dir)
    config["data_files"] = [os.path.basename(data_file)]
    config["task_dir"] = temp_dir
    config["output_annotation_dir"] = os.path.join(temp_dir, "output")
    config_file = create_temp_config(config, temp_dir)
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    started = server.start()
    assert started, "Failed to start Flask test server"
    return server

# Selenium-specific helpers can be added here as needed, e.g.:
# def submit_annotation_ui(self, value, schema_name): ...
# def navigate_to_next(self): ...