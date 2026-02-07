"""Tests for data_sources credentials module."""

import os
import tempfile
import pytest
from potato.data_sources.credentials import (
    substitute_env_vars,
    load_env_file,
    CredentialManager,
    ENV_VAR_PATTERN,
)


class TestEnvVarPattern:
    """Tests for the environment variable pattern regex."""

    def test_matches_simple_var(self):
        """Test matching simple variable names."""
        match = ENV_VAR_PATTERN.search("${API_KEY}")
        assert match is not None
        assert match.group(1) == "API_KEY"

    def test_matches_underscore_var(self):
        """Test matching variables with underscores."""
        match = ENV_VAR_PATTERN.search("${MY_API_KEY_123}")
        assert match is not None
        assert match.group(1) == "MY_API_KEY_123"

    def test_matches_in_string(self):
        """Test matching variable embedded in string."""
        match = ENV_VAR_PATTERN.search("Bearer ${TOKEN}")
        assert match is not None
        assert match.group(1) == "TOKEN"

    def test_no_match_for_invalid_names(self):
        """Test that invalid variable names don't match."""
        assert ENV_VAR_PATTERN.search("${123INVALID}") is None
        assert ENV_VAR_PATTERN.search("$NOBRACES") is None
        assert ENV_VAR_PATTERN.search("${-invalid}") is None


class TestSubstituteEnvVars:
    """Tests for substitute_env_vars function."""

    def test_substitute_simple_string(self):
        """Test substituting a simple string value."""
        os.environ["TEST_VAR"] = "test_value"
        result = substitute_env_vars("${TEST_VAR}")
        assert result == "test_value"
        del os.environ["TEST_VAR"]

    def test_substitute_in_context(self):
        """Test substituting variable in context."""
        os.environ["TEST_TOKEN"] = "secret123"
        result = substitute_env_vars("Bearer ${TEST_TOKEN}")
        assert result == "Bearer secret123"
        del os.environ["TEST_TOKEN"]

    def test_substitute_multiple_vars(self):
        """Test substituting multiple variables."""
        os.environ["VAR1"] = "first"
        os.environ["VAR2"] = "second"
        result = substitute_env_vars("${VAR1}-${VAR2}")
        assert result == "first-second"
        del os.environ["VAR1"]
        del os.environ["VAR2"]

    def test_unset_var_unchanged(self):
        """Test that unset variables are left unchanged."""
        result = substitute_env_vars("${UNSET_VAR_12345}")
        assert result == "${UNSET_VAR_12345}"

    def test_substitute_in_dict(self):
        """Test substituting in dictionary values."""
        os.environ["DICT_VAR"] = "dict_value"
        input_dict = {
            "key1": "${DICT_VAR}",
            "key2": "normal",
        }
        result = substitute_env_vars(input_dict)
        assert result["key1"] == "dict_value"
        assert result["key2"] == "normal"
        del os.environ["DICT_VAR"]

    def test_substitute_in_list(self):
        """Test substituting in list values."""
        os.environ["LIST_VAR"] = "list_value"
        input_list = ["${LIST_VAR}", "normal"]
        result = substitute_env_vars(input_list)
        assert result[0] == "list_value"
        assert result[1] == "normal"
        del os.environ["LIST_VAR"]

    def test_substitute_nested_structures(self):
        """Test substituting in nested structures."""
        os.environ["NESTED_VAR"] = "nested_value"
        input_data = {
            "outer": {
                "inner": "${NESTED_VAR}",
                "list": ["${NESTED_VAR}", "normal"]
            }
        }
        result = substitute_env_vars(input_data)
        assert result["outer"]["inner"] == "nested_value"
        assert result["outer"]["list"][0] == "nested_value"
        del os.environ["NESTED_VAR"]

    def test_non_string_values_unchanged(self):
        """Test that non-string values are unchanged."""
        input_data = {
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
        }
        result = substitute_env_vars(input_data)
        assert result == input_data


class TestLoadEnvFile:
    """Tests for load_env_file function."""

    def test_load_simple_env_file(self):
        """Test loading a simple .env file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("TEST_ENV_VAR=test_value\n")
            f.write("ANOTHER_VAR=another_value\n")
            env_file = f.name

        try:
            # Clear any existing value
            if "TEST_ENV_VAR" in os.environ:
                del os.environ["TEST_ENV_VAR"]
            if "ANOTHER_VAR" in os.environ:
                del os.environ["ANOTHER_VAR"]

            count = load_env_file(env_file)

            assert count == 2
            assert os.environ.get("TEST_ENV_VAR") == "test_value"
            assert os.environ.get("ANOTHER_VAR") == "another_value"

            # Cleanup
            del os.environ["TEST_ENV_VAR"]
            del os.environ["ANOTHER_VAR"]
        finally:
            os.unlink(env_file)

    def test_load_with_quotes(self):
        """Test loading values with quotes."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('QUOTED_VAR="quoted value"\n')
            f.write("SINGLE_QUOTED='single quoted'\n")
            env_file = f.name

        try:
            if "QUOTED_VAR" in os.environ:
                del os.environ["QUOTED_VAR"]
            if "SINGLE_QUOTED" in os.environ:
                del os.environ["SINGLE_QUOTED"]

            load_env_file(env_file)

            assert os.environ.get("QUOTED_VAR") == "quoted value"
            assert os.environ.get("SINGLE_QUOTED") == "single quoted"

            del os.environ["QUOTED_VAR"]
            del os.environ["SINGLE_QUOTED"]
        finally:
            os.unlink(env_file)

    def test_skips_comments(self):
        """Test that comments are skipped."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("# This is a comment\n")
            f.write("VALID_VAR=value\n")
            f.write("  # Another comment\n")
            env_file = f.name

        try:
            if "VALID_VAR" in os.environ:
                del os.environ["VALID_VAR"]

            count = load_env_file(env_file)

            assert count == 1
            assert os.environ.get("VALID_VAR") == "value"

            del os.environ["VALID_VAR"]
        finally:
            os.unlink(env_file)

    def test_does_not_override_existing(self):
        """Test that existing env vars are not overridden."""
        os.environ["EXISTING_VAR"] = "existing"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("EXISTING_VAR=new_value\n")
            env_file = f.name

        try:
            load_env_file(env_file)
            assert os.environ.get("EXISTING_VAR") == "existing"

            del os.environ["EXISTING_VAR"]
        finally:
            os.unlink(env_file)

    def test_file_not_found_raises(self):
        """Test that missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_env_file("/nonexistent/path/.env")


class TestCredentialManager:
    """Tests for CredentialManager class."""

    def test_from_config_default(self):
        """Test creating with default config."""
        manager = CredentialManager.from_config({})

        assert manager.env_substitution is True
        assert manager.env_file is None

    def test_from_config_with_settings(self):
        """Test creating with custom config."""
        config = {
            "credentials": {
                "env_substitution": False,
                "env_file": ".env.test"
            }
        }
        manager = CredentialManager.from_config(config)

        assert manager.env_substitution is False
        assert manager.env_file == ".env.test"

    def test_process_config_with_substitution(self):
        """Test processing config with substitution enabled."""
        os.environ["CRED_TEST"] = "credential_value"

        manager = CredentialManager(env_substitution=True)
        config = {"secret": "${CRED_TEST}"}
        result = manager.process_config(config)

        assert result["secret"] == "credential_value"
        del os.environ["CRED_TEST"]

    def test_process_config_without_substitution(self):
        """Test processing config with substitution disabled."""
        os.environ["CRED_TEST2"] = "credential_value"

        manager = CredentialManager(env_substitution=False)
        config = {"secret": "${CRED_TEST2}"}
        result = manager.process_config(config)

        assert result["secret"] == "${CRED_TEST2}"
        del os.environ["CRED_TEST2"]

    def test_get_credential_found(self):
        """Test getting a credential that exists."""
        os.environ["GET_CRED"] = "found_value"

        manager = CredentialManager()
        value = manager.get_credential({"key": "${GET_CRED}"}, "key")

        assert value == "found_value"
        del os.environ["GET_CRED"]

    def test_get_credential_missing_required_raises(self):
        """Test that missing required credential raises."""
        manager = CredentialManager()

        with pytest.raises(ValueError) as exc_info:
            manager.get_credential({}, "missing_key", required=True)

        assert "missing_key" in str(exc_info.value)

    def test_get_credential_missing_optional_returns_none(self):
        """Test that missing optional credential returns None."""
        manager = CredentialManager()
        value = manager.get_credential({}, "missing_key", required=False)

        assert value is None

    def test_mask_credential(self):
        """Test credential masking."""
        masked = CredentialManager.mask_credential("supersecretkey")
        assert masked == "***tkey"

    def test_mask_credential_short(self):
        """Test masking short credential."""
        masked = CredentialManager.mask_credential("abc")
        assert masked == "***"

    def test_validate_credentials_all_present(self):
        """Test validating when all credentials are present."""
        os.environ["VALID_CRED1"] = "value1"
        os.environ["VALID_CRED2"] = "value2"

        manager = CredentialManager()
        config = {
            "key1": "${VALID_CRED1}",
            "key2": "${VALID_CRED2}",
        }
        errors = manager.validate_credentials(config, ["key1", "key2"])

        assert len(errors) == 0

        del os.environ["VALID_CRED1"]
        del os.environ["VALID_CRED2"]

    def test_validate_credentials_missing(self):
        """Test validating when credential is missing."""
        manager = CredentialManager()
        config = {"key1": "value1"}
        errors = manager.validate_credentials(config, ["key1", "key2"])

        assert len(errors) == 1
        assert "key2" in errors[0]
