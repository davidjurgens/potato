"""
Tests for issue #113: url_direct login does not initialize phase page for phased workflows.

When using url_direct login with phased workflows (e.g., consent -> annotation),
the page for the first phase was not initialized, causing a KeyError: None when
trying to render the phase template.

The root cause: the url_direct path called advance_to_phase(first_phase, None)
directly instead of using advance_phase() which looks up the first page name.
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


def create_phased_url_direct_config(test_dir: str, port: int, phases_order: list = None) -> str:
    """Create a config with url_direct login AND phased workflow (consent, etc.)."""

    # Create test data
    test_data = [
        {"id": "item_1", "text": "First item to annotate."},
        {"id": "item_2", "text": "Second item to annotate."},
    ]
    data_file = os.path.join(test_dir, "test_data.json")
    with open(data_file, "w") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")

    # Create output directory
    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Create a consent survey file
    consent_survey = {
        "title": "Consent Form",
        "description": "Please read and agree to the consent form.",
        "questions": [
            {
                "question": "Do you consent to participate?",
                "type": "radio",
                "options": ["Yes", "No"]
            }
        ]
    }
    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)
    consent_file = os.path.join(surveys_dir, "consent.json")
    with open(consent_file, "w") as f:
        json.dump(consent_survey, f)

    # Create instruction survey file
    instructions_survey = {
        "title": "Instructions",
        "description": "Please read the instructions carefully.",
        "questions": []
    }
    instructions_file = os.path.join(surveys_dir, "instructions.json")
    with open(instructions_file, "w") as f:
        json.dump(instructions_survey, f)

    if phases_order is None:
        phases_order = ["consent", "annotation"]

    # Build phases config
    phases = {"order": phases_order}
    if "consent" in phases_order:
        phases["consent"] = {"type": "consent", "file": "surveys/consent.json"}
    if "instructions" in phases_order:
        phases["instructions"] = {"type": "instructions", "file": "surveys/instructions.json"}
    if "annotation" in phases_order:
        phases["annotation"] = {"type": "annotation"}

    config = {
        "annotation_task_name": f"Phased URL-Direct Test {port}",
        "login": {
            "type": "url_direct",
            "url_argument": "PROLIFIC_PID",
        },
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?",
            }
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 2,
        "max_annotations_per_item": 3,
        "phases": phases,
        "site_file": "base_template.html",
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False,
        "alert_time_each_instance": 0,
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
        """Start the server and wait for it to be ready."""
        from datetime import timedelta
        from flask import Flask
        from jinja2 import ChoiceLoader, FileSystemLoader

        # Clear any existing state
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
                generated_templates_dir = os.path.join(
                    real_templates_dir, "generated"
                )
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
                self.app.jinja_loader = ChoiceLoader(
                    [
                        FileSystemLoader(real_templates_dir),
                        FileSystemLoader(generated_templates_dir),
                    ]
                )

                from potato.server_utils.html_sanitizer import register_jinja_filters
                register_jinja_filters(self.app)

                import secrets
                self.app.secret_key = secrets.token_hex(32)
                self.app.permanent_session_lifetime = timedelta(days=2)

                from potato.routes import configure_routes
                configure_routes(self.app, config)

                self.app.run(
                    host="127.0.0.1",
                    port=self.port,
                    debug=False,
                    use_reloader=False,
                    threaded=True,
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
        """Stop the server."""
        from potato.user_state_management import clear_user_state_manager
        from potato.item_state_management import clear_item_state_manager
        clear_user_state_manager()
        clear_item_state_manager()


class TestURLDirectWithPhasedWorkflow:
    """
    Tests for issue #113: url_direct login with phased workflows.

    When using url_direct login with phases like consent -> annotation,
    the first phase page must be properly initialized.
    """

    @pytest.fixture
    def phased_server(self, request):
        """Create a test server with url_direct login and consent phase."""
        port = find_free_port(preferred_port=9700)
        test_dir = create_test_directory(f"url_direct_phased_{port}")

        config_file = create_phased_url_direct_config(
            test_dir, port, phases_order=["consent", "annotation"]
        )

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    @pytest.fixture
    def multi_phase_server(self, request):
        """Create a test server with url_direct login and multiple pre-annotation phases."""
        port = find_free_port(preferred_port=9710)
        test_dir = create_test_directory(f"url_direct_multi_phase_{port}")

        config_file = create_phased_url_direct_config(
            test_dir, port,
            phases_order=["consent", "instructions", "annotation"]
        )

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_url_direct_with_consent_phase_does_not_crash(self, phased_server):
        """
        Issue #113: URL-direct login with consent phase should not cause KeyError: None.

        The bug was that advance_to_phase(first_phase, None) was called instead of
        advance_phase() which properly looks up the first page name for the phase.
        """
        server, test_dir = phased_server
        session = requests.Session()

        # This request should NOT cause a 500 error / KeyError: None
        response = session.get(
            f"{server.base_url}/",
            params={"PROLIFIC_PID": "worker_consent_test"},
            allow_redirects=True,
            timeout=10,
        )

        # Should get a successful page (consent form), not a 500 error
        assert response.status_code == 200, (
            f"Expected 200 but got {response.status_code}. "
            f"This likely means the phase page was not initialized (issue #113)."
        )
        # Should NOT contain a traceback or error page
        assert "KeyError" not in response.text
        assert "Internal Server Error" not in response.text

    def test_url_direct_consent_phase_shows_consent_content(self, phased_server):
        """After url_direct login with consent phase, user should see consent form."""
        server, test_dir = phased_server
        session = requests.Session()

        response = session.get(
            f"{server.base_url}/",
            params={"PROLIFIC_PID": "worker_consent_content"},
            allow_redirects=True,
            timeout=10,
        )

        assert response.status_code == 200
        # The consent page should contain some consent-related content
        text = response.text.lower()
        assert "consent" in text or "agree" in text or "survey" in text, (
            "Consent page content not found in response"
        )

    def test_url_direct_multi_phase_does_not_crash(self, multi_phase_server):
        """URL-direct login with consent -> instructions -> annotation should work."""
        server, test_dir = multi_phase_server
        session = requests.Session()

        response = session.get(
            f"{server.base_url}/",
            params={"PROLIFIC_PID": "worker_multi_phase"},
            allow_redirects=True,
            timeout=10,
        )

        assert response.status_code == 200
        assert "KeyError" not in response.text
        assert "Internal Server Error" not in response.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
