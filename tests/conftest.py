import pytest
import sys
import os
import tempfile
import yaml
import json

# Import test setup for Flask app, config, managers, and routes
import tests.helpers.flask_test_setup
from potato.flask_server import app as flask_app
from potato.server_utils.config_module import config

@pytest.fixture(scope="session")
def app():
    # Set up test configuration
    TEST_CONFIG = {
        "secret_key": "potato-annotation-platform-test-key",
        "session_lifetime_days": 1,
        "debug": True,
        "persist_sessions": False,  # Default to non-persistent sessions for tests
        "task_dir": tempfile.mkdtemp(),
        "output_annotation_dir": tempfile.mkdtemp(),
        "data_files": [],
        "item_properties": {
            "id_key": "id",
            "text_key": "text"
        },
        "user_config": {
            "allow_all_users": True,
            "users": []
        },
        "annotation_schemes": [
            {
                "name": "test_scheme",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["option_1", "option_2", "option_3"],
                "description": "Choose one option."
            }
        ],
        "annotation_task_name": "Test Annotation Task",
        "site_file": "base_template.html",
        "html_layout": "base_template.html",
        "base_html_template": "base_template.html",
        "header_file": "base_template.html",
        "site_dir": os.path.join(os.path.dirname(__file__), '../potato/templates'),
        "customjs": None,
        "customjs_hostname": None,
        "alert_time_each_instance": 10000000
    }

    # Update global config
    config.update(TEST_CONFIG)

    # Initialize managers for testing
    from potato.user_state_management import init_user_state_manager
    from potato.item_state_management import init_item_state_manager
    init_user_state_manager(TEST_CONFIG)
    init_item_state_manager(TEST_CONFIG)

    # Configure Flask app
    flask_app.config["TESTING"] = True
    flask_app.config["debug"] = False

    # Register routes
    from potato.routes import configure_routes
    configure_routes(flask_app, TEST_CONFIG)

    yield flask_app

@pytest.fixture(scope="function")
def client(app):
    return app.test_client()