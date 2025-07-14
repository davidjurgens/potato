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
import pytest
from potato.item_state_management import clear_item_state_manager
from potato.user_state_management import clear_user_state_manager
import socket
import subprocess
from datetime import timedelta

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class FlaskTestServer:
    """A test server that can be started and stopped for integration tests."""

    def __init__(self, app_factory=None, config=None, debug=False, port=None, config_file=None, test_data_file=None):
        # Support both old and new constructor patterns
        # Old pattern: FlaskTestServer(app_factory, config, debug)
        # New pattern: FlaskTestServer(port=port, debug=debug, config_file=config_file, test_data_file=test_data_file)

        self.app_factory = app_factory
        self.config = None
        self.temp_config_file = None
        self.debug = debug
        self.test_data_file = test_data_file

        # Handle port parameter
        if port is not None:
            self.port = port
        else:
            self.port = self._find_free_port()

        self.base_url = f"http://localhost:{self.port}"

        # Handle config_file parameter (new pattern)
        if config_file is not None:
            self.config = config_file
        elif config is not None:
            if isinstance(config, dict):
                # Ensure debug is false and add all required config keys
                config = dict(config)
                config['debug'] = False
                config['persist_sessions'] = False

                # Add missing required config keys if not present
                if 'output_annotation_format' not in config:
                    config['output_annotation_format'] = 'jsonl'
                if 'site_dir' not in config:
                    config['site_dir'] = 'output'
                if 'alert_time_each_instance' not in config:
                    config['alert_time_each_instance'] = 0
                if 'random_seed' not in config:
                    config['random_seed'] = 1234
                if 'require_password' not in config:
                    config['require_password'] = False
                if 'port' not in config:
                    config['port'] = self.port
                if 'host' not in config:
                    config['host'] = '0.0.0.0'
                if 'session_lifetime_days' not in config:
                    config['session_lifetime_days'] = 2
                if 'secret_key' not in config:
                    config['secret_key'] = 'test-secret-key'

                # Write to temp YAML file
                fd, temp_path = tempfile.mkstemp(suffix='.yaml', prefix='flasktest_config_')
                with os.fdopen(fd, 'w') as f:
                    yaml.dump(config, f)
                self.temp_config_file = temp_path
                self.config = temp_path
            elif isinstance(config, str):
                # If config is a file path, ensure debug is false in the file
                with open(config, 'r') as f:
                    config_data = yaml.safe_load(f)
                if config_data.get('debug', False):
                    config_data['debug'] = False
                if 'persist_sessions' not in config_data:
                    config_data['persist_sessions'] = False
                if 'random_seed' not in config_data:
                    config_data['random_seed'] = 1234
                if 'require_password' not in config_data:
                    config_data['require_password'] = False
                if 'port' not in config_data:
                    config_data['port'] = self.port
                if 'host' not in config_data:
                    config_data['host'] = '0.0.0.0'
                if 'session_lifetime_days' not in config_data:
                    config_data['session_lifetime_days'] = 2
                if 'secret_key' not in config_data:
                    config_data['secret_key'] = 'test-secret-key'

                fd, temp_path = tempfile.mkstemp(suffix='.yaml', prefix='flasktest_config_')
                with os.fdopen(fd, 'w') as f:
                    yaml.dump(config_data, f)
                self.temp_config_file = temp_path
                self.config = temp_path
            else:
                raise ValueError('Config must be a dict or file path')
        self.process = None
        self.session = requests.Session()

    def __del__(self):
        if self.temp_config_file and os.path.exists(self.temp_config_file):
            os.remove(self.temp_config_file)

    def _find_free_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("localhost", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def start(self):
        """Start the Flask server in a separate thread."""
        return self._start_server()

    def start_server(self, config_dir=None):
        """Alias for start() method for backward compatibility."""
        return self._start_server(config_dir)

    def _start_server(self, config_dir=None):
        """Internal method to start the Flask server in a separate thread."""
        # Handle config_dir parameter for backward compatibility
        if config_dir is not None:
            # This is the old pattern - we need to handle config file creation
            if self.config is None:
                # Create a temporary config file in the config_dir
                import tempfile
                config_file = os.path.join(config_dir, 'test_config.yaml')
                # For now, we'll use a simple config - this can be enhanced if needed
                simple_config = {
                    "debug": self.debug,
                    "port": self.port,
                    "host": "0.0.0.0",
                    "task_dir": config_dir,
                    "output_annotation_dir": os.path.join(config_dir, "output"),
                    "data_files": [],
                    "annotation_schemes": [],
                    "item_properties": {"id_key": "id", "text_key": "text"},
                    "authentication": {"method": "in_memory"},
                    "require_password": False,
                    "persist_sessions": False
                }
                with open(config_file, 'w') as f:
                    yaml.dump(simple_config, f)
                self.config = config_file

        # Set environment variables for the server
        os.environ['POTATO_CONFIG_FILE'] = self.config
        os.environ['POTATO_DEBUG'] = 'false'  # Always false for test servers

        # Ensure debug mode is set in the config
        if self.debug:
            os.environ['FLASK_DEBUG'] = '1'

        def run_server():
            """Run the Flask server in a separate thread."""
            try:
                import os
                config_file = self.config
                # Don't change directory - keep current working directory
                # config_dir = os.path.dirname(config_file)
                # os.chdir(config_dir)

                # Create a fresh Flask app instance instead of importing the global one
                from flask import Flask
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
                args.persist_sessions = False  # Add missing attribute
                args.require_password = False
                args.port = self.port

                # Initialize config
                init_config(args)

                # Ensure debug mode is set in the config
                from potato.server_utils.config_module import config
                config['debug'] = self.debug
                print(f"🔍 Setting debug mode to: {self.debug}")
                print(f"🔍 Config debug value: {config.get('debug', 'NOT_SET')}")
                config['persist_sessions'] = False
                config['random_seed'] = 1234
                config['require_password'] = False
                config['port'] = self.port
                config['host'] = '0.0.0.0'
                config['session_lifetime_days'] = 2
                config['secret_key'] = 'test-secret-key'

                # Add missing required fields
                if 'output_annotation_dir' not in config:
                    config['output_annotation_dir'] = os.path.join(config.get('task_dir', '/tmp'), 'output')
                if 'task_dir' not in config:
                    config['task_dir'] = '/tmp/potato_test'
                # Patch: Use real templates directory for tests
                real_templates_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../potato/templates'))
                config['site_dir'] = real_templates_dir
                config['base_html_template'] = os.path.join(real_templates_dir, 'base_template.html')
                config['header_file'] = os.path.join(real_templates_dir, 'base_template.html')
                config['site_file'] = os.path.join(real_templates_dir, 'base_template.html')
                config['html_layout'] = os.path.join(real_templates_dir, 'base_template.html')
                if 'annotation_schemes' not in config:
                    config['annotation_schemes'] = []
                if 'data_files' not in config:
                    config['data_files'] = []
                if 'item_properties' not in config:
                    config['item_properties'] = {'id_key': 'id', 'text_key': 'text'}
                if 'user_config' not in config:
                    config['user_config'] = {'allow_all_users': True, 'users': []}
                if 'authentication' not in config:
                    config['authentication'] = {'method': 'in_memory'}
                if 'annotation_task_name' not in config:
                    config['annotation_task_name'] = 'Test Annotation Task'
                if 'site_file' not in config:
                    config['site_file'] = 'base_template.html'
                if 'html_layout' not in config:
                    config['html_layout'] = 'base_template.html'
                if 'base_html_template' not in config:
                    config['base_html_template'] = 'base_template.html'
                if 'header_file' not in config:
                    config['header_file'] = 'base_template.html'
                if 'customjs' not in config:
                    config['customjs'] = None
                if 'customjs_hostname' not in config:
                    config['customjs_hostname'] = None
                if 'alert_time_each_instance' not in config:
                    config['alert_time_each_instance'] = 10000000

                # Fix data file paths to be relative to project root
                if 'data_files' in config:
                    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
                    fixed_data_files = []
                    for data_file in config['data_files']:
                        # If it's a relative path starting with ../, resolve it from project root
                        if data_file.startswith('../'):
                            # Remove the ../ prefix and resolve from project root
                            relative_path = data_file[3:]  # Remove '../'
                            full_path = os.path.join(project_root, relative_path)
                        else:
                            # Assume it's relative to project root
                            full_path = os.path.join(project_root, data_file)
                        fixed_data_files.append(full_path)
                    config['data_files'] = fixed_data_files

                # Create required directories
                if 'task_dir' in config:
                    os.makedirs(config['task_dir'], exist_ok=True)
                if 'output_annotation_dir' in config:
                    os.makedirs(config['output_annotation_dir'], exist_ok=True)
                if 'site_dir' in config:
                    os.makedirs(config['site_dir'], exist_ok=True)

                # Initialize the managers and data (same as run_server)
                from potato.user_state_management import init_user_state_manager, clear_user_state_manager
                from potato.item_state_management import init_item_state_manager, clear_item_state_manager
                from potato.flask_server import load_all_data
                from potato.authentificaton import UserAuthenticator

                # Clear any existing managers (for testing)
                clear_user_state_manager()
                clear_item_state_manager()

                # Initialize authenticator
                UserAuthenticator.init_from_config(config)

                # Initialize managers
                init_user_state_manager(config)
                init_item_state_manager(config)
                load_all_data(config)

                                # Create a fresh Flask app instance
                app = Flask(__name__, template_folder=real_templates_dir)

                # Configure Jinja2 to also look in the generated templates directory
                generated_templates_dir = os.path.join(real_templates_dir, 'generated')
                if not os.path.exists(generated_templates_dir):
                    os.makedirs(generated_templates_dir, exist_ok=True)

                # Add the generated directory to the template search path
                from jinja2 import ChoiceLoader, FileSystemLoader
                app.jinja_loader = ChoiceLoader([
                    FileSystemLoader(real_templates_dir),
                    FileSystemLoader(generated_templates_dir)
                ])

                # Configure the app
                if config.get("persist_sessions", False):
                    app.secret_key = config.get("secret_key", "potato-annotation-platform")
                else:
                    # Generate a random secret key to ensure sessions don't persist between restarts
                    import secrets
                    app.secret_key = secrets.token_hex(32)

                app.permanent_session_lifetime = timedelta(days=config.get("session_lifetime_days", 2))

                # Configure routes
                from potato.routes import configure_routes
                configure_routes(app, config)

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
                        response = self.session.post(f"{self.base_url}/admin/set_debug_session", timeout=1)
                        print(f"🔍 /admin/set_debug_session response: {response.status_code}")
                        print(f"🔍 Session cookies after set_debug_session: {dict(self.session.cookies)}")

                    return True
            except requests.exceptions.RequestException:
                pass

            time.sleep(0.5)
            wait_time += 0.5

        print(f"❌ Failed to start server on {self.base_url}")
        return False

    def _wait_for_server_ready(self, timeout=10):
        start = time.time()
        while time.time() - start < timeout:
            try:
                r = requests.get(f"http://localhost:{self.port}/", timeout=1)
                if r.status_code == 200:
                    return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError(f"Flask server did not start on port {self.port} within {timeout} seconds")

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None

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
            self.start()
            yield self
        finally:
            self.stop()

    def stop_server(self):
        """Stop the Flask server."""
        # Try to shutdown the Flask app via HTTP
        try:
            resp = self.session.post(f"{self.base_url}/shutdown", timeout=1)
            print(f"[DEBUG] /shutdown response: {getattr(resp, 'status_code', None)} {getattr(resp, 'text', None)}")
        except Exception as e:
            print(f"[DEBUG] Exception during /shutdown: {e}")

        if self.server_thread and self.server_thread.is_alive():
            # Try to join, then forcibly kill if needed
            self.server_thread.join(timeout=5)
            if self.server_thread.is_alive():
                print("[DEBUG] Server thread still alive after join. Forcibly killing.")
                # On Unix, we can try to send SIGKILL to the process
                import os
                os._exit(0)

    def stop(self):
        """Alias for stop_server() method for backward compatibility."""
        self.stop_server()

    def is_server_running(self) -> bool:
        """Check if the server is running."""
        try:
            response = self.session.get(f"{self.base_url}/", timeout=1)
            return response.status_code == 200
        except:
            return False

    @property
    def app(self):
        """Property to maintain compatibility with existing tests."""
        return None  # The app is not directly accessible in this implementation

    def get(self, path: str, **kwargs) -> requests.Response:
        """Make a GET request to the server using the session."""
        # Add admin API key for admin endpoints
        if path.startswith('/admin/'):
            headers = kwargs.get('headers', {})
            headers['X-API-Key'] = 'admin_api_key'
            kwargs['headers'] = headers
        return self.session.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        """Make a POST request to the server using the session."""
        # Add admin API key for admin endpoints
        if path.startswith('/admin/'):
            headers = kwargs.get('headers', {})
            headers['X-API-Key'] = 'admin_api_key'
            kwargs['headers'] = headers
        return self.session.post(f"{self.base_url}{path}", **kwargs)


class FlaskTestBase:
    """Base class for tests that need a running Flask server."""

    def __init__(self, port: int = 9001, debug: bool = False, config_file: Optional[str] = None):
        self.server = FlaskTestServer(port=port, debug=debug, config_file=config_file)
        self.server_started = False

    def setUp(self):
        """Set up the test server."""
        if not self.server_started:
            self.server_started = self.server.start()
            if not self.server_started:
                raise RuntimeError("Failed to start test server")

    def tearDown(self):
        """Tear down the test server."""
        if self.server_started:
            self.server.stop()
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


def create_chrome_options(headless: bool = True):
    """Create standardized Chrome options for Selenium tests.

    Args:
        headless: Whether to run Chrome in headless mode (default: True)

    Returns:
        Chrome options configured for testing
    """
    from selenium.webdriver.chrome.options import Options

    chrome_options = Options()

    if headless:
        chrome_options.add_argument("--headless=new")  # Use the new headless mode

    # Standard options for testing
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--disable-javascript")  # Only if not needed for tests
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    return chrome_options


@pytest.fixture(autouse=True)
def reset_state_managers():
    clear_item_state_manager()
    clear_user_state_manager()
    yield
    clear_item_state_manager()
    clear_user_state_manager()


if __name__ == "__main__":
    # Test the server setup
    print("🧪 Testing Flask server setup...")

    server = create_test_server(port=9001, debug=False)

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