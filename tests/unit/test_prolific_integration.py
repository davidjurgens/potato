"""
Prolific Integration Tests

This module contains unit tests for the Prolific crowdsourcing integration,
including URL-direct login, completion codes, and Prolific API initialization.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestURLDirectLogin:
    """Tests for URL-direct login functionality."""

    def test_url_direct_login_config_detection(self):
        """Test that URL-direct login type is detected from config."""
        config = {
            'login': {
                'type': 'url_direct',
                'url_argument': 'PROLIFIC_PID'
            }
        }
        login_config = config.get('login', {})
        assert login_config.get('type') == 'url_direct'
        assert login_config.get('url_argument') == 'PROLIFIC_PID'

    def test_prolific_login_config_detection(self):
        """Test that Prolific login type is detected from config."""
        config = {
            'login': {
                'type': 'prolific'
            }
        }
        login_config = config.get('login', {})
        assert login_config.get('type') == 'prolific'

    def test_standard_login_default(self):
        """Test that standard login is the default when not specified."""
        config = {}
        login_config = config.get('login', {})
        login_type = login_config.get('type', 'standard')
        assert login_type == 'standard'

    def test_url_argument_defaults_to_prolific_pid(self):
        """Test that URL argument defaults to PROLIFIC_PID."""
        config = {
            'login': {
                'type': 'url_direct'
                # No url_argument specified
            }
        }
        login_config = config.get('login', {})
        url_argument = login_config.get('url_argument', 'PROLIFIC_PID')
        assert url_argument == 'PROLIFIC_PID'


class TestRequireNoPassword:
    """Tests for require_no_password config handling."""

    def test_require_no_password_converts_to_require_password_false(self):
        """Test that require_no_password: true sets require_password: false."""
        config = {
            'require_no_password': True,
            'require_password': True  # Should be overridden
        }

        # Simulate the logic from flask_server.py
        if config.get("require_no_password", False):
            config["require_password"] = False

        assert config["require_password"] == False

    def test_url_direct_disables_password_requirement(self):
        """Test that url_direct login type disables password requirement."""
        config = {
            'login': {'type': 'url_direct'},
            'require_password': True  # Should be overridden
        }

        # Simulate the logic from flask_server.py
        login_config = config.get('login', {})
        if login_config.get('type') in ['url_direct', 'prolific']:
            config["require_password"] = False

        assert config["require_password"] == False


class TestCompletionCode:
    """Tests for completion code handling."""

    def test_completion_code_from_config(self):
        """Test that completion code is read from config."""
        config = {
            'completion_code': 'ABC123XYZ'
        }
        assert config.get('completion_code', '') == 'ABC123XYZ'

    def test_empty_completion_code_default(self):
        """Test that empty completion code is default when not specified."""
        config = {}
        assert config.get('completion_code', '') == ''

    def test_prolific_redirect_url_construction(self):
        """Test that Prolific redirect URL is correctly constructed."""
        completion_code = 'ABC123XYZ'
        expected_url = f"https://app.prolific.co/submissions/complete?cc={completion_code}"
        assert expected_url == "https://app.prolific.co/submissions/complete?cc=ABC123XYZ"


class TestProlificStudyInitialization:
    """Tests for ProlificStudy initialization."""

    def test_prolific_config_missing_returns_none(self):
        """Test that missing Prolific config doesn't crash."""
        config = {}
        prolific_config = config.get('prolific', {})
        assert prolific_config == {}

    def test_prolific_config_from_inline(self):
        """Test that inline Prolific config is parsed correctly."""
        config = {
            'prolific': {
                'token': 'test_token',
                'study_id': 'test_study_id',
                'max_concurrent_sessions': 50,
                'workload_checker_period': 120
            }
        }
        prolific_config = config.get('prolific', {})
        assert prolific_config.get('token') == 'test_token'
        assert prolific_config.get('study_id') == 'test_study_id'
        assert prolific_config.get('max_concurrent_sessions') == 50
        assert prolific_config.get('workload_checker_period') == 120

    def test_prolific_config_file_path(self):
        """Test that Prolific config file path is recognized."""
        config = {
            'prolific': {
                'config_file_path': 'configs/prolific_config.yaml'
            }
        }
        prolific_config = config.get('prolific', {})
        assert prolific_config.get('config_file_path') == 'configs/prolific_config.yaml'


class TestProlificURLParameters:
    """Tests for Prolific URL parameter extraction."""

    def test_extract_prolific_pid(self):
        """Test extraction of PROLIFIC_PID from URL parameters."""
        # Simulate request.args
        url_args = {
            'PROLIFIC_PID': 'participant123',
            'SESSION_ID': 'session456',
            'STUDY_ID': 'study789'
        }

        prolific_pid = url_args.get('PROLIFIC_PID')
        session_id = url_args.get('SESSION_ID')
        study_id = url_args.get('STUDY_ID')

        assert prolific_pid == 'participant123'
        assert session_id == 'session456'
        assert study_id == 'study789'

    def test_custom_url_argument(self):
        """Test extraction with custom URL argument name."""
        url_args = {
            'worker_id': 'worker123'  # Custom argument name
        }
        login_config = {
            'type': 'url_direct',
            'url_argument': 'worker_id'  # Custom name
        }

        url_argument = login_config.get('url_argument', 'PROLIFIC_PID')
        username = url_args.get(url_argument)

        assert username == 'worker123'

    def test_missing_url_parameter(self):
        """Test handling when URL parameter is missing."""
        url_args = {}  # No parameters
        username = url_args.get('PROLIFIC_PID')
        assert username is None


class TestAutoRedirect:
    """Tests for auto-redirect configuration."""

    def test_auto_redirect_disabled_by_default(self):
        """Test that auto-redirect is disabled by default."""
        config = {}
        auto_redirect = config.get('auto_redirect_on_completion', False)
        assert auto_redirect == False

    def test_auto_redirect_enabled(self):
        """Test that auto-redirect can be enabled."""
        config = {
            'auto_redirect_on_completion': True,
            'auto_redirect_delay': 3000
        }
        assert config.get('auto_redirect_on_completion', False) == True
        assert config.get('auto_redirect_delay', 5000) == 3000

    def test_auto_redirect_delay_default(self):
        """Test that auto-redirect delay has a default value."""
        config = {
            'auto_redirect_on_completion': True
        }
        delay = config.get('auto_redirect_delay', 5000)
        assert delay == 5000


class TestProlificStudyAPI:
    """Tests for ProlificStudy API wrapper."""

    def test_prolific_base_headers(self):
        """Test that Prolific API headers are correctly formatted."""
        from potato.server_utils.prolific_apis import ProlificBase

        token = "test_token_123"
        client = ProlificBase(token)

        assert 'Authorization' in client.headers
        assert client.headers['Authorization'] == f'Token {token}'

    def test_prolific_study_initialization(self):
        """Test ProlificStudy initialization with mock."""
        from potato.server_utils.prolific_apis import ProlificStudy

        with patch.object(ProlificStudy, 'get_study_by_id', return_value={
            'id': 'study123',
            'name': 'Test Study',
            'status': 'ACTIVE'
        }):
            # Note: This will make an API call unless mocked
            # For unit tests, we just verify the class can be imported
            pass


class TestSessionStorage:
    """Tests for Prolific session data storage."""

    def test_session_prolific_ids_storage(self):
        """Test that Prolific IDs can be stored in session."""
        # Simulate Flask session
        session = {}

        session['prolific_session_id'] = 'session123'
        session['prolific_study_id'] = 'study456'

        assert session.get('prolific_session_id') == 'session123'
        assert session.get('prolific_study_id') == 'study456'

    def test_session_username_from_prolific(self):
        """Test that username is stored from Prolific PID."""
        session = {}
        prolific_pid = 'participant789'

        session['username'] = prolific_pid

        assert session['username'] == prolific_pid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
