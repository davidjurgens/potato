import os
import sys
import logging
from potato.flask_server import app
from potato.server_utils.config_module import config

# Use a minimal config for testing with real template files
cur_program_dir = os.path.dirname(os.path.abspath(__file__))
templates_dir = os.path.join(os.path.dirname(__file__), '../potato/templates')

# Pick a real template file for all template config fields
real_template = 'base_template.html'

# Set up test config
TEST_CONFIG = {
    "secret_key": "potato-annotation-platform-test-key",
    "session_lifetime_days": 1,
    "debug": True,
    "task_dir": "/tmp/test_output/",
    "output_annotation_dir": "/tmp/test_output/",
    "data_files": [],
    "item_properties": {
        "id_key": "id",
        "text_key": "text"
    },
    "user_config": {
        "allow_all_users": True,
        "users": []
    },
    "site_file": real_template,
    "html_layout": real_template,
    "base_html_template": real_template,
    "header_file": real_template,
    "site_dir": templates_dir,
    "customjs": None,
    "customjs_hostname": None,
    "alert_time_each_instance": 10000000
}

config.update(TEST_CONFIG)

# Initialize managers for testing
from potato.user_state_management import init_user_state_manager
from potato.item_state_management import init_item_state_manager
init_user_state_manager(TEST_CONFIG)
init_item_state_manager(TEST_CONFIG)

# Register routes
from potato.routes import configure_routes
configure_routes(app, TEST_CONFIG)