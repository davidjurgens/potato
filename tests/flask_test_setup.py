#!/usr/bin/env python3
"""
Core test setup for Flask server integration tests.
Provides a base class that can start a Flask server with a simple configuration.
"""

import os
import sys
import time
import tempfile
import json
import yaml
import threading
import requests
from typing import Optional, Dict, Any
from contextlib import contextmanager
import signal

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class FlaskTestServer:
    """A test server that can be started and stopped for integration tests."""

    def __init__(self, port: int = 9001, debug: bool = False, config_file: Optional[str] = None):
        self.port = port
        self.debug = debug
        self.config_file = config_file
        self.server_process = None
        self.server_thread = None
        self.app = None
        self.base_url = f"http://localhost:{self.port}"
        self.server_error = None
        self.session = requests.Session()  # Use a session to persist cookies

    def create_test_config(self, config_dir: str, data_file: str) -> str:
        """Create a simple test configuration file."""
        # Use a subdirectory for phase files, as in the full example
        phase_dir = os.path.join(config_dir, 'configs', 'test-phases')
        os.makedirs(phase_dir, exist_ok=True)
        consent_file = os.path.join('configs', 'test-phases', 'consent.json')
        instructions_file = os.path.join('configs', 'test-phases', 'instructions.json')
        config = {
            "debug": self.debug,
            "max_annotations_per_user": 5,
            "max_annotations_per_item": -1,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Test Annotation Task",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": [data_file],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
            "annotation_schemes": [
                {
                    "name": "radio_choice",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["option_1", "option_2", "option_3"],
                    "description": "Choose one option."
                }
            ],
            "phases": {
                "order": ["consent", "instructions"],
                "consent": {
                    "type": "consent",
                    "file": consent_file
                },
                "instructions": {
                    "type": "instructions",
                    "file": instructions_file
                }
            },
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(config_dir, "output"),
            "task_dir": os.path.join(config_dir, "task"),
            "base_html_template": "default",
            "header_file": "default",
            "html_layout": "default",
            "site_dir": os.path.join(config_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Ensure output and task directories exist
        os.makedirs(config["output_annotation_dir"], exist_ok=True)
        os.makedirs(config["task_dir"], exist_ok=True)

        config_path = os.path.join(config_dir, 'test_config.yaml')
        with open(config_path, 'w') as f:
            yaml.dump(config, f)
        # Print the config file contents for debugging
        with open(config_path, 'r') as f:
            print(f"[DEBUG] Written config file {config_path} contents:\n" + f.read())
        return config_path

    def create_phase_files(self, config_dir: str) -> None:
        """Create phase files for consent and instructions in a subdirectory."""
        phase_dir = os.path.join(config_dir, 'configs', 'test-phases')
        os.makedirs(phase_dir, exist_ok=True)

        # Create consent phase file
        consent_data = [
            {
                "name": "consent_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I agree", "I do not agree"],
                "description": "Do you agree to participate in this study?"
            }
        ]
        consent_path = os.path.join(phase_dir, 'consent.json')
        with open(consent_path, 'w') as f:
            json.dump(consent_data, f, indent=2)

        # Create instructions phase file
        instructions_data = [
            {
                "name": "instructions_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I understand", "I need more explanation"],
                "description": "Do you understand the instructions?"
            }
        ]
        instructions_path = os.path.join(phase_dir, 'instructions.json')
        with open(instructions_path, 'w') as f:
            json.dump(instructions_data, f, indent=2)

    def create_test_data(self, config_dir: str) -> str:
        """Create test data file in JSONL format (one JSON object per line)."""
        test_data = [
            {"id": f"item_{i}", "text": f"This is test item {i}"}
            for i in range(1, 6)
        ]

        data_path = os.path.join(config_dir, 'test_data.json')
        with open(data_path, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')
        # Debug print
        print(f"[DEBUG] Test data file written: {data_path}")
        with open(data_path) as f:
            print(f"[DEBUG] Test data file contents: {f.read()}")
        return data_path

    def create_test_template(self, config_dir: str) -> str:
        """Create a simple test template."""
        template_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Annotation</title>
</head>
<body>
    <h1>Test Annotation Task</h1>
    <p>Instance: {{ instance }}</p>
    <p>Instance ID: {{ instance_id }}</p>
    <p>Username: {{ username }}</p>
    <p>Debug: {{ debug }}</p>

    <div id="annotation-container">
        <h2>Annotation Schemes:</h2>
        {% for scheme in annotation_schemes %}
        <div class="scheme">
            <h3>{{ scheme.name }} ({{ scheme.type }})</h3>
            {% if scheme.type == 'radio' %}
                {% for label in scheme.labels %}
                <label>
                    <input type="radio" name="{{ scheme.name }}" value="{{ label }}">
                    {{ label }}
                </label>
                {% endfor %}
            {% endif %}
        </div>
        {% endfor %}
    </div>

    <div id="navigation">
        <button onclick="submitAnnotation()">Submit</button>
        <button onclick="nextInstance()">Next</button>
        <button onclick="prevInstance()">Previous</button>
    </div>

    <script>
        function submitAnnotation() {
            // Mock submission
            console.log('Annotation submitted');
        }

        function nextInstance() {
            // Mock navigation
            console.log('Next instance');
        }

        function prevInstance() {
            // Mock navigation
            console.log('Previous instance');
        }
    </script>
</body>
</html>
"""

        templates_dir = os.path.join(config_dir, 'templates')
        os.makedirs(templates_dir, exist_ok=True)
        template_path = os.path.join(templates_dir, 'base_template.html')
        with open(template_path, 'w') as f:
            f.write(template_content)
        return template_path

    def start_server(self, config_dir: Optional[str] = None) -> bool:
        """Start the Flask server in a separate thread."""
        if self.config_file:
            # Use the provided config file (production config)
            config_file = self.config_file
            config_dir = os.path.dirname(os.path.abspath(config_file))
        else:
            # Use test config
            if config_dir is None:
                config_dir = tempfile.mkdtemp()

            # Create test data file first
            data_file = self.create_test_data(config_dir)
            template_file = self.create_test_template(config_dir)

            # Create phase files
            self.create_phase_files(config_dir)

            # Use just the filename for data_files
            data_file_name = os.path.basename(data_file)
            config_file = self.create_test_config(config_dir, data_file_name)

        # Set environment variables for the server
        os.environ['POTATO_CONFIG_FILE'] = config_file
        os.environ['POTATO_DEBUG'] = str(self.debug).lower()

        # Ensure debug mode is set in the config
        if self.debug:
            os.environ['FLASK_DEBUG'] = '1'

        def run_server():
            """Run the Flask server in a separate thread."""
            try:
                # Change working directory to config_dir so relative paths work
                os.chdir(config_dir)
                # Import and configure the Flask app properly
                from potato.flask_server import app
                from potato.server_utils.config_module import init_config
                from potato.server_utils.arg_utils import arguments

                # Create args object for config initialization
                class Args:
                    pass
                args = Args()
                args.config_file = config_file
                args.verbose = False
                args.very_verbose = False
                args.customjs = None
                args.customjs_hostname = None
                args.debug = self.debug

                # Initialize config
                init_config(args)

                # Ensure debug mode is set in the config
                from potato.server_utils.config_module import config
                config['debug'] = self.debug

                # Initialize the managers and data (same as run_server)
                from potato.user_state_management import init_user_state_manager
                from potato.item_state_management import init_item_state_manager
                from potato.flask_server import load_all_data
                from potato.authentificaton import UserAuthenticator

                # Initialize authenticator
                UserAuthenticator.init_from_config(config)

                # Initialize managers
                init_user_state_manager(config)
                init_item_state_manager(config)
                load_all_data(config)

                # Configure routes
                from potato.routes import configure_routes
                configure_routes(app, config)

                self.app = app
                app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)
            except Exception as e:
                print(f"Error starting server: {e}")
                import traceback
                traceback.print_exc()

        # Start server in a separate thread
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # Wait for server to start
        max_wait = 10  # seconds
        wait_time = 0
        while wait_time < max_wait:
            try:
                response = self.session.get(f"{self.base_url}/", timeout=1)
                if response.status_code == 200:
                    print(f"✅ Server started successfully on {self.base_url}")
                    # Initialize session and debug user by visiting home
                    self.session.get(f"{self.base_url}/", timeout=1)

                    # Force session initialization by making a request that sets the session
                    if self.debug:
                        # Set debug session by calling the new endpoint
                        response = self.session.post(f"{self.base_url}/test/set_debug_session", timeout=1)
                        print(f"🔍 /test/set_debug_session response: {response.status_code}")
                        print(f"🔍 Session cookies after set_debug_session: {dict(self.session.cookies)}")

                    return True
            except requests.exceptions.RequestException:
                pass

            time.sleep(0.5)
            wait_time += 0.5

        print(f"❌ Failed to start server on {self.base_url}")
        return False

    def register_user(self, username: str, password: str) -> bool:
        """Register a new user via the registration endpoint."""
        try:
            response = self.session.post(f"{self.base_url}/register", data={
                'action': 'signup',
                'email': username,
                'pass': password
            }, timeout=5)

            print(f"🔍 Registration response: {response.status_code}")
            print(f"🔍 Registration redirect: {response.url}")

            # Check if registration was successful (should redirect to home or annotation page)
            return response.status_code in [200, 302] and 'error' not in response.text.lower()
        except Exception as e:
            print(f"❌ Registration failed: {e}")
            return False

    def login_user(self, username: str, password: str) -> bool:
        """Login a user via the auth endpoint."""
        try:
            response = self.session.post(f"{self.base_url}/auth", data={
                'action': 'login',
                'email': username,
                'pass': password
            }, timeout=5)

            print(f"🔍 Login response: {response.status_code}")
            print(f"🔍 Login redirect: {response.url}")

            # Check if login was successful (should redirect to annotation page)
            return response.status_code in [200, 302] and 'error' not in response.text.lower()
        except Exception as e:
            print(f"❌ Login failed: {e}")
            return False

    def get_user_state(self, username: str) -> Optional[Dict[str, Any]]:
        """Get the current user state."""
        try:
            if self.debug:
                response = self.session.get(f"{self.base_url}/test/user_state/{username}", timeout=5)
            else:
                # In production mode, we might need to use a different endpoint
                response = self.session.get(f"{self.base_url}/user_state", timeout=5)

            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"❌ Failed to get user state: {e}")
            return None

    @contextmanager
    def server_context(self):
        """Context manager for server lifecycle."""
        try:
            self.start_server()
            yield self
        finally:
            self.stop_server()

    def stop_server(self):
        """Stop the Flask server."""
        if self.app:
            # Shutdown the Flask app
            try:
                resp = self.session.post(f"{self.base_url}/shutdown", timeout=1)
                print(f"[DEBUG] /shutdown response: {getattr(resp, 'status_code', None)} {getattr(resp, 'text', None)}")
            except Exception as e:
                print(f"[DEBUG] Exception during /shutdown: {e}")
            self.app = None

        if self.server_thread and self.server_thread.is_alive():
            # Try to join, then forcibly kill if needed
            self.server_thread.join(timeout=5)
            if self.server_thread.is_alive():
                print("[DEBUG] Server thread still alive after join. Forcibly killing.")
                # On Unix, we can try to send SIGKILL to the process
                import os
                os._exit(0)

    def is_server_running(self) -> bool:
        """Check if the server is running."""
        try:
            response = self.session.get(f"{self.base_url}/", timeout=1)
            return response.status_code == 200
        except:
            return False

    def get(self, path: str, **kwargs) -> requests.Response:
        """Make a GET request to the server using the session."""
        return self.session.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        """Make a POST request to the server using the session."""
        return self.session.post(f"{self.base_url}{path}", **kwargs)


class FlaskTestBase:
    """Base class for tests that need a running Flask server."""

    def __init__(self, port: int = 9001, debug: bool = False, config_file: Optional[str] = None):
        self.server = FlaskTestServer(port=port, debug=debug, config_file=config_file)
        self.server_started = False

    def setUp(self):
        """Set up the test server."""
        if not self.server_started:
            self.server_started = self.server.start_server()
            if not self.server_started:
                raise RuntimeError("Failed to start test server")

    def tearDown(self):
        """Tear down the test server."""
        if self.server_started:
            self.server.stop_server()
            self.server_started = False

    @contextmanager
    def server_context(self):
        """Context manager for server lifecycle."""
        try:
            self.setUp()
            yield self.server
        finally:
            self.tearDown()


def create_test_server(port: int = 9001, debug: bool = False, config_file: Optional[str] = None) -> FlaskTestServer:
    """Factory function to create a test server."""
    return FlaskTestServer(port=port, debug=debug, config_file=config_file)


if __name__ == "__main__":
    # Test the server setup
    print("🧪 Testing Flask server setup...")

    server = create_test_server(port=9001, debug=True)

    try:
        if server.start_server():
            print("✅ Server started successfully!")

            # Test a simple request
            response = server.get("/")
            print(f"✅ GET / returned status: {response.status_code}")

            # Test debug endpoint
            response = server.get("/test/debug")
            print(f"✅ GET /test/debug returned status: {response.status_code}")

        else:
            print("❌ Failed to start server")
    finally:
        server.stop_server()
        print("🛑 Server stopped")