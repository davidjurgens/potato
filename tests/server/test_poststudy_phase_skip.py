"""
Tests for issue #115: Poststudy phase skipped due to POST request after annotation completion.

When a user finishes their last annotation via POST, the phase advances to poststudy.
Previously, the POST method leaked into the poststudy handler, which interpreted the
empty POST as a completed survey and immediately advanced to 'done', skipping the
poststudy page entirely.

The fix uses redirect(url_for("home")) instead of calling home() directly, ensuring
the poststudy handler receives a GET request and renders the form.
"""

import json
import os
import pytest
import requests
import time
import yaml
import threading

from tests.helpers.test_utils import (
    create_test_directory,
    cleanup_test_directory,
)
from tests.helpers.port_manager import find_free_port


def create_poststudy_config(test_dir: str, port: int) -> str:
    """Create a config with annotation followed by poststudy phase."""

    # Create test data — just 1 item so user completes quickly
    test_data = [
        {"id": "item_1", "text": "Single item to annotate."},
    ]
    data_file = os.path.join(test_dir, "test_data.json")
    with open(data_file, "w") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")

    # Create output directory
    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Create a poststudy survey file
    poststudy_survey = {
        "title": "Post-Study Survey",
        "description": "Please answer these questions about the study.",
        "questions": [
            {
                "question": "How was the study?",
                "type": "radio",
                "options": ["Good", "Bad"]
            }
        ]
    }
    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)
    poststudy_file = os.path.join(surveys_dir, "poststudy.json")
    with open(poststudy_file, "w") as f:
        json.dump(poststudy_survey, f)

    config = {
        "annotation_task_name": f"Poststudy Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative"],
                "description": "What is the sentiment?",
            }
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 1,
        "max_annotations_per_item": 3,
        "phases": {
            "order": ["annotation", "poststudy_survey"],
            "annotation": {"type": "annotation"},
            "poststudy_survey": {"type": "poststudy", "file": "surveys/poststudy.json"},
        },
        "site_file": "base_template.html",
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False,
        "alert_time_each_instance": 0,
        "user_config": {"allow_all_users": True, "users": []},
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


class SimpleTestServer:
    """A simple test server that runs Flask in a thread."""

    def __init__(self, config_file: str, port: int):
        self.config_file = config_file
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.server_thread = None
        self.app = None

    def start(self, timeout: int = 15) -> bool:
        from datetime import timedelta
        from flask import Flask
        from jinja2 import ChoiceLoader, FileSystemLoader

        from potato.user_state_management import clear_user_state_manager
        from potato.item_state_management import clear_item_state_manager
        clear_user_state_manager()
        clear_item_state_manager()

        def run_server():
            try:
                project_root = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "../..")
                )
                os.chdir(project_root)

                from potato.server_utils.config_module import init_config, config

                class Args:
                    pass
                args = Args()
                args.config_file = self.config_file
                args.verbose = False
                args.very_verbose = False
                args.customjs = None
                args.customjs_hostname = None
                args.debug = False
                args.persist_sessions = False
                args.require_password = False
                args.port = self.port

                init_config(args)

                real_templates_dir = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "../../potato/templates")
                )
                static_folder = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "../../potato/static")
                )
                generated_templates_dir = os.path.join(real_templates_dir, "generated")
                os.makedirs(generated_templates_dir, exist_ok=True)

                from potato.user_state_management import init_user_state_manager
                from potato.item_state_management import init_item_state_manager
                from potato.flask_server import load_all_data
                from potato.authentication import UserAuthenticator

                UserAuthenticator.init_from_config(config)
                init_user_state_manager(config)
                init_item_state_manager(config)
                load_all_data(config)

                self.app = Flask(
                    __name__,
                    template_folder=real_templates_dir,
                    static_folder=static_folder,
                )
                self.app.jinja_loader = ChoiceLoader([
                    FileSystemLoader(real_templates_dir),
                    FileSystemLoader(generated_templates_dir),
                ])

                from potato.server_utils.html_sanitizer import register_jinja_filters
                register_jinja_filters(self.app)

                import secrets
                self.app.secret_key = secrets.token_hex(32)
                self.app.permanent_session_lifetime = timedelta(days=2)

                from potato.routes import configure_routes
                configure_routes(self.app, config)

                self.app.run(
                    host="127.0.0.1", port=self.port,
                    debug=False, use_reloader=False, threaded=True,
                )
            except Exception as e:
                print(f"Server error: {e}")
                import traceback
                traceback.print_exc()

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.base_url}/", timeout=1)
                if response.status_code in [200, 302]:
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(0.5)
        return False

    def stop(self):
        from potato.user_state_management import clear_user_state_manager
        from potato.item_state_management import clear_item_state_manager
        clear_user_state_manager()
        clear_item_state_manager()


class TestPoststudyNotSkipped:
    """
    Tests for issue #115: Poststudy phase should not be skipped after annotation.
    """

    @pytest.fixture
    def poststudy_server(self, request):
        port = find_free_port(preferred_port=9720)
        test_dir = create_test_directory(f"poststudy_test_{port}")

        config_file = create_poststudy_config(test_dir, port)

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_poststudy_shown_after_annotation_completion(self, poststudy_server):
        """
        Issue #115: After completing last annotation via POST, user should see
        poststudy page (not skip directly to done).
        """
        server, test_dir = poststudy_server
        session = requests.Session()

        # Register and login
        session.post(f"{server.base_url}/register",
                     data={"email": "user1", "pass": "pass"})
        session.post(f"{server.base_url}/auth",
                     data={"email": "user1", "pass": "pass"})

        # Save annotation on the single item
        session.post(
            f"{server.base_url}/updateinstance",
            json={
                "instance_id": "item_1",
                "annotations": {"sentiment:positive": "true"},
                "span_annotations": [],
            },
            timeout=5,
        )

        # Navigate to next (triggers completion detection via POST)
        response = session.post(
            f"{server.base_url}/annotate",
            json={"action": "next_instance", "instance_id": "item_1"},
            allow_redirects=True,
            timeout=5,
        )

        # After following redirects, the user should be on the poststudy page
        # NOT on the done/completion page
        text = response.text.lower()

        # The poststudy page should have survey content
        has_poststudy_content = (
            "post-study" in text
            or "poststudy" in text
            or "survey" in text
            or "how was" in text
        )

        # Should NOT be on done page
        is_done_page = "thank" in text and ("complet" in text or "done" in text)

        assert has_poststudy_content or not is_done_page, (
            "User was sent to done page, skipping poststudy (issue #115). "
            "The POST request leaked into the poststudy handler."
        )

    def test_poststudy_not_advanced_by_empty_post(self, poststudy_server):
        """
        Verify that arriving at poststudy via GET does not auto-advance.
        """
        server, test_dir = poststudy_server
        session = requests.Session()

        # Register, login, complete annotation
        session.post(f"{server.base_url}/register",
                     data={"email": "user2", "pass": "pass"})
        session.post(f"{server.base_url}/auth",
                     data={"email": "user2", "pass": "pass"})

        session.post(
            f"{server.base_url}/updateinstance",
            json={
                "instance_id": "item_1",
                "annotations": {"sentiment:negative": "true"},
                "span_annotations": [],
            },
            timeout=5,
        )

        # Complete annotation
        session.post(
            f"{server.base_url}/annotate",
            json={"action": "next_instance", "instance_id": "item_1"},
            allow_redirects=True,
            timeout=5,
        )

        # Now explicitly GET home — should still be on poststudy
        response = session.get(f"{server.base_url}/", allow_redirects=True, timeout=5)

        text = response.text.lower()
        # Should still show poststudy content (user hasn't submitted it yet)
        has_poststudy_content = (
            "post-study" in text
            or "poststudy" in text
            or "survey" in text
            or "how was" in text
        )
        assert has_poststudy_content, (
            "GET to home after annotation completion should show poststudy page"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
