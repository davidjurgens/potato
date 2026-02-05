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

# Import port manager for reliable port allocation
from tests.helpers.port_manager import find_free_port, release_port


def clear_all_global_state():
    """Clear all global singleton state to ensure test isolation.

    This function clears all known singleton managers in the potato package.
    Call this between tests to ensure no state leaks.
    """
    # Core state managers
    clear_item_state_manager()
    clear_user_state_manager()

    # Config module
    try:
        from potato.server_utils.config_module import clear_config
        clear_config()
    except ImportError:
        pass

    # Span counter reset
    try:
        from potato.server_utils.schemas.span import reset_span_counter
        reset_span_counter()
    except ImportError:
        pass

    # Expertise manager
    try:
        from potato.expertise_manager import clear_expertise_manager
        clear_expertise_manager()
    except ImportError:
        pass

    # Quality control manager
    try:
        from potato.quality_control import clear_quality_control_manager
        clear_quality_control_manager()
    except ImportError:
        pass

    # Active learning manager
    try:
        from potato.active_learning_manager import clear_active_learning_manager
        clear_active_learning_manager()
    except ImportError:
        pass

    # ICL labeler
    try:
        from potato.ai.icl_labeler import clear_icl_labeler
        clear_icl_labeler()
    except ImportError:
        pass

    # Directory watcher
    try:
        from potato.directory_watcher import clear_directory_watcher
        clear_directory_watcher()
    except ImportError:
        pass

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

        # Handle port parameter - use requested port if available, otherwise find a free one
        self.port = self._get_available_port(port)

        self.base_url = f"http://localhost:{self.port}"

        # Handle config_file parameter (new pattern)
        if config_file is not None:
            # Load and modify the config file to ensure port matches
            with open(config_file, 'r') as f:
                config_data = yaml.safe_load(f)

            # Update port to match the actual port being used
            config_data['port'] = self.port
            config_data['host'] = '0.0.0.0'

            # Write updated config to a temp file in the same directory
            config_dir = os.path.dirname(os.path.abspath(config_file))
            temp_config_path = os.path.join(config_dir, f'test_config_port_{self.port}.yaml')
            with open(temp_config_path, 'w') as f:
                yaml.dump(config_data, f)
            self.temp_config_file = temp_config_path
            self.config = temp_config_path
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

                # Write to temp YAML file within the project directory
                temp_path = self._create_temp_config_file(config, 'flasktest_config_')
                self.temp_config_file = temp_path
                self.config = temp_path
            elif isinstance(config, str):
                # If config is a file path, use it directly but update with test settings
                # This preserves the original directory structure and data file paths
                with open(config, 'r') as f:
                    config_data = yaml.safe_load(f)

                # Update settings for testing
                config_data['debug'] = False
                config_data['persist_sessions'] = False
                if 'random_seed' not in config_data:
                    config_data['random_seed'] = 1234
                config_data['require_password'] = False
                config_data['port'] = self.port
                config_data['host'] = '0.0.0.0'
                if 'session_lifetime_days' not in config_data:
                    config_data['session_lifetime_days'] = 2
                if 'secret_key' not in config_data:
                    config_data['secret_key'] = 'test-secret-key'

                # Write updated config back to the SAME directory to preserve data file paths
                config_dir = os.path.dirname(os.path.abspath(config))
                temp_config_path = os.path.join(config_dir, 'test_config_modified.yaml')
                with open(temp_config_path, 'w') as f:
                    yaml.dump(config_data, f)
                self.temp_config_file = temp_config_path
                self.config = temp_config_path
            else:
                raise ValueError('Config must be a dict or file path')
        self.process = None
        self.session = requests.Session()

    def __del__(self):
        if self.temp_config_file and os.path.exists(self.temp_config_file):
            os.remove(self.temp_config_file)

    def _get_available_port(self, requested_port=None):
        """Get an available port, using requested_port if available, otherwise find a free one.

        Uses the port_manager module for reliable port allocation with retry logic
        to handle TOCTOU race conditions.

        Args:
            requested_port: Preferred port to use. If None or unavailable, finds a free port.

        Returns:
            An available port number.
        """
        return find_free_port(preferred_port=requested_port)

    def _create_temp_config_file(self, config_data, prefix):
        """Create a temporary config file within the project directory."""
        # Use the new test utilities for secure file creation
        from tests.helpers.test_utils import create_test_directory, create_test_config, create_test_data_file

        # Create a test directory within tests/output/
        test_dir = create_test_directory(f"flasktest_{prefix}")

        # Handle 'data' key (legacy format) - convert inline data to data files
        data_files = config_data.get('data_files', [])
        if 'data' in config_data and config_data['data']:
            # Write inline data to a file
            data_file = create_test_data_file(test_dir, config_data['data'], "test_data.jsonl")
            data_files = [data_file]
            del config_data['data']

        # Handle 'annotation_schemas' dict format (legacy) - convert to list format
        annotation_schemes = config_data.get('annotation_schemes', [])
        if isinstance(annotation_schemes, dict):
            # Convert dict format to list format
            annotation_schemes_list = []
            for name, schema in annotation_schemes.items():
                scheme = {"name": name}
                if 'type' in schema:
                    scheme['annotation_type'] = schema['type']
                if 'options' in schema:
                    scheme['labels'] = schema['options']
                if 'description' in schema:
                    scheme['description'] = schema['description']
                annotation_schemes_list.append(scheme)
            annotation_schemes = annotation_schemes_list

        # Create a minimal annotation scheme if none provided
        if not annotation_schemes:
            annotation_schemes = [
                {
                    "name": "test_scheme",
                    "annotation_type": "radio",
                    "labels": ["option_1", "option_2"],
                    "description": "Test annotation scheme"
                }
            ]

        # Create the config file using the test utilities
        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=data_files,
            **{k: v for k, v in config_data.items() if k not in ['annotation_schemes', 'data_files']}
        )

        return config_file

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
        os.environ['POTATO_SKIP_CONFIG_PATH_VALIDATION'] = '1'  # Skip path validation in tests

        # Ensure debug mode is set in the config
        if self.debug:
            os.environ['FLASK_DEBUG'] = '1'

        def run_server():
            """Run the Flask server in a separate thread."""
            try:
                import os
                config_file = self.config
                # Change to config file's directory to ensure path validation works
                config_dir = os.path.dirname(os.path.abspath(config_file))
                os.chdir(config_dir)

                # Clear any existing state from previous test runs to ensure isolation
                try:
                    from potato.user_state_management import clear_user_state_manager
                    from potato.item_state_management import clear_item_state_manager
                    from potato.server_utils.config_module import clear_config
                    from potato.server_utils.schemas.span import reset_span_counter
                    clear_user_state_manager()
                    clear_item_state_manager()
                    clear_config()
                    reset_span_counter()
                    try:
                        from potato.adjudication import clear_adjudication_manager
                        clear_adjudication_manager()
                    except ImportError:
                        pass
                except Exception as e:
                    print(f"[DEBUG] Error clearing state managers at startup: {e}")

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
                # Let require_password come from config file if set, otherwise default to False
                args.require_password = None  # Will be set from config file
                args.port = self.port

                # Initialize config
                init_config(args)

                # Ensure debug mode is set in the config
                from potato.server_utils.config_module import config
                config['debug'] = self.debug
                config['persist_sessions'] = False
                config['random_seed'] = 1234
                # Don't override require_password if it's set in the config file
                if 'require_password' not in config:
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

                # Fix data file paths to be relative to the config file directory
                if 'data_files' in config:
                    config_dir = os.path.dirname(config_file) if config_file else os.getcwd()
                    fixed_data_files = []
                    for data_file in config['data_files']:
                        # If it's an absolute path, use it as is
                        if os.path.isabs(data_file):
                            full_path = data_file
                        # If it's a relative path, resolve it from the config file directory
                        else:
                            full_path = os.path.join(config_dir, data_file)
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
                from potato.authentication import UserAuthenticator

                # Clear any existing managers (for testing)
                clear_user_state_manager()
                clear_item_state_manager()
                # Clear ICL labeler if it exists
                try:
                    from potato.ai.icl_labeler import clear_icl_labeler
                    clear_icl_labeler()
                except ImportError:
                    pass

                # Initialize authenticator
                UserAuthenticator.init_from_config(config)

                # Initialize managers
                init_user_state_manager(config)
                init_item_state_manager(config)

                # Initialize AI support if enabled (BEFORE load_all_data)
                # This must happen before load_all_data() because template generation
                # needs get_ai_wrapper() to return the AI help div
                if config.get("ai_support", {}).get("enabled", False):
                    try:
                        from potato.ai.ai_prompt import init_ai_prompt
                        from potato.ai.ai_help_wrapper import init_dynamic_ai_help
                        print("[DEBUG] Initializing AI prompt and wrapper...")
                        init_ai_prompt(config)
                        init_dynamic_ai_help()
                        print("[DEBUG] AI prompt and wrapper initialized successfully")
                    except Exception as e:
                        print(f"[DEBUG] Error initializing AI support: {e}")

                load_all_data(config)

                # Initialize AI cache manager AFTER load_all_data
                if config.get("ai_support", {}).get("enabled", False):
                    try:
                        from potato.ai.ai_cache import init_ai_cache_manager
                        init_ai_cache_manager()
                        print("[DEBUG] AI cache manager initialized successfully")
                    except Exception as e:
                        print(f"[DEBUG] Error initializing AI cache manager: {e}")

                # Initialize ICL labeler if configured (same as run_server does)
                icl_config = config.get('icl_labeling', {})
                if icl_config.get('enabled', False):
                    try:
                        from potato.ai.icl_labeler import init_icl_labeler
                        icl_labeler = init_icl_labeler(config)
                        icl_labeler.start_background_worker()
                    except Exception as e:
                        print(f"Warning: Failed to initialize ICL labeler: {e}")

                # Initialize adjudication manager if configured
                if config.get('adjudication', {}).get('enabled', False):
                    try:
                        from potato.adjudication import init_adjudication_manager
                        init_adjudication_manager(config)
                        print("[DEBUG] Adjudication manager initialized successfully")
                    except Exception as e:
                        print(f"[DEBUG] Error initializing adjudication manager: {e}")

                # Create a fresh Flask app instance with explicit static folder
                static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../potato/static'))
                app = Flask(__name__, template_folder=real_templates_dir, static_folder=static_folder)

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

                # Register custom Jinja2 filters (including sanitize_html)
                from potato.server_utils.html_sanitizer import register_jinja_filters
                register_jinja_filters(app)

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

                # Add route to serve test audio files from tests/data directory
                test_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../data'))

                @app.route('/test-audio/<path:filename>')
                def serve_test_audio(filename):
                    """Serve test audio files from the tests/data directory."""
                    from flask import send_from_directory
                    return send_from_directory(test_data_dir, filename)

                # Use make_server instead of app.run() for proper shutdown support
                from werkzeug.serving import make_server
                self._wsgi_server = make_server('0.0.0.0', self.port, app, threaded=True)
                self._wsgi_server.serve_forever()
            except Exception as e:
                print(f"Error starting server: {e}")
                import traceback
                traceback.print_exc()

        # Initialize server reference
        self._wsgi_server = None

        # Start server in a separate thread
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # Wait for server to start
        max_wait = 10  # seconds - reduced timeout for faster test failures
        wait_time = 0
        while wait_time < max_wait:
            try:
                response = self.session.get(f"{self.base_url}/", timeout=2, allow_redirects=False)
                print(f"🔍 Server response: {response.status_code}")
                # Accept any non-error status code as success (server is responding)
                if response.status_code < 500:
                    print(f"✅ Server started successfully on {self.base_url}")
                    # Initialize session and debug user by visiting home
                    self.session.get(f"{self.base_url}/", timeout=2)

                    # Force session initialization by making a request that sets the session
                    if self.debug:
                        # Set debug session by calling the new endpoint
                        response = self.session.post(f"{self.base_url}/admin/set_debug_session", timeout=1)
                        print(f"🔍 /admin/set_debug_session response: {response.status_code}")
                        print(f"🔍 Session cookies after set_debug_session: {dict(self.session.cookies)}")

                    return True
            except requests.exceptions.RequestException as e:
                if wait_time % 5 == 0:  # Print every 5 seconds
                    print(f"🔄 Waiting for server... ({wait_time}s) - {type(e).__name__}: {e}")

            time.sleep(0.2)
            wait_time += 0.2

        print(f"❌ Failed to start server on {self.base_url} after {max_wait}s")
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

    def register_user(self, username: str, password: str = "test_password") -> bool:
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

            # Check if login was successful
            # Success is indicated by:
            # 1. Status code 200 or 302
            # 2. Being redirected to /annotate or another non-auth page
            # 3. Not being on an error page (check for specific error indicators)
            if response.status_code not in [200, 302]:
                return False

            # If redirected to annotate page, login succeeded
            if '/annotate' in response.url:
                return True

            # Check for authentication error messages in the response
            # These are specific error messages shown on the login page
            error_indicators = [
                'invalid credentials',
                'login failed',
                'authentication failed',
                'incorrect password',
                'user not found'
            ]
            response_lower = response.text.lower()
            for indicator in error_indicators:
                if indicator in response_lower:
                    return False

            # If we reached this point without errors, consider it successful
            return True
        except Exception as e:
            print(f"❌ Login failed: {e}")
            return False

    def get_user_state(self, username: str) -> Optional[Any]:
        """Get the current user state.

        Returns the actual UserState object when accessing directly,
        or a dict representation when using the API.
        """
        try:
            # First try to get it directly from the manager (more reliable for tests)
            from potato.user_state_management import get_user_state_manager
            usm = get_user_state_manager()
            if usm:
                user_state = usm.get_user_state(username)
                if user_state:
                    return user_state

            # Fall back to API endpoint
            response = self.session.get(
                f"{self.base_url}/admin/user_state/{username}",
                headers={"X-API-Key": "admin_api_key"},
                timeout=5
            )

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
        # Shutdown the WSGI server if it exists
        if hasattr(self, '_wsgi_server') and self._wsgi_server is not None:
            try:
                self._wsgi_server.shutdown()
                self._wsgi_server = None
            except Exception as e:
                print(f"[DEBUG] Error shutting down WSGI server: {e}")

        # Wait for server thread to finish (with timeout)
        if hasattr(self, 'server_thread') and self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)

        # Release the port for reuse by other tests
        if hasattr(self, 'port') and self.port:
            release_port(self.port)

        # Clear all global state to ensure test isolation
        try:
            clear_all_global_state()
        except Exception as e:
            print(f"[DEBUG] Error clearing global state: {e}")

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
def reset_state_managers(request):
    """Reset all global state between tests to ensure isolation.

    Note: For tests using class-scoped fixtures (like flask_server),
    we skip clearing config to avoid wiping out server configuration.
    """
    import os

    # Save original working directory
    original_cwd = os.getcwd()

    # Check if this test class has a class-scoped flask_server fixture or class attribute
    # If so, don't clear config as it would wipe out the server's configuration
    has_class_scoped_server = False
    if hasattr(request, 'cls') and request.cls is not None:
        # Check if this class has a flask_server fixture or a 'server' class attribute
        # (many unittest-style tests use cls.server instead of a pytest fixture)
        has_class_scoped_server = (
            hasattr(request.cls, 'flask_server') or
            hasattr(request.cls, 'server') or
            'flask_server' in getattr(request, 'fixturenames', [])
        )

    # Also check for session-scoped servers in fixture names
    session_scoped_fixtures = ['shared_flask_server', 'shared_form_server', 'shared_span_server']
    has_session_scoped_server = any(f in getattr(request, 'fixturenames', []) for f in session_scoped_fixtures)

    if not has_class_scoped_server and not has_session_scoped_server:
        # Clear state before test (only for tests without scoped servers)
        clear_all_global_state()

    yield

    if not has_class_scoped_server and not has_session_scoped_server:
        # Clear state after test (only for tests without scoped servers)
        clear_all_global_state()

    # Restore original working directory (init_config changes it)
    try:
        os.chdir(original_cwd)
    except Exception:
        pass  # Directory might not exist anymore


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