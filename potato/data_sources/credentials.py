"""
Credential management for data sources.

This module provides secure credential handling including:
- Environment variable substitution in configuration values
- Support for .env files
- Service account and API key management
- Credential validation without logging sensitive values
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Pattern to match environment variable references: ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def substitute_env_vars(value: Any, env_file: Optional[str] = None) -> Any:
    """
    Substitute environment variable references in a configuration value.

    Supports the ${VAR_NAME} syntax for referencing environment variables.
    If an environment variable is not set, the reference is left unchanged
    and a warning is logged.

    Args:
        value: The value to process (string, dict, list, or other)
        env_file: Optional path to .env file to load additional variables

    Returns:
        The value with environment variables substituted

    Examples:
        >>> os.environ['API_KEY'] = 'secret123'
        >>> substitute_env_vars('Bearer ${API_KEY}')
        'Bearer secret123'

        >>> substitute_env_vars({'auth': '${TOKEN}'})
        {'auth': '<value of TOKEN>'}
    """
    # Load .env file if specified and exists
    if env_file:
        load_env_file(env_file)

    return _substitute_recursive(value)


def _substitute_recursive(value: Any) -> Any:
    """Recursively substitute environment variables in nested structures."""
    if isinstance(value, str):
        return _substitute_in_string(value)
    elif isinstance(value, dict):
        return {k: _substitute_recursive(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_recursive(v) for v in value]
    else:
        return value


def _substitute_in_string(value: str) -> str:
    """Substitute environment variables in a string value."""
    def replacer(match):
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            logger.warning(
                f"Environment variable '{var_name}' is not set. "
                f"The reference ${{{var_name}}} will be left unchanged."
            )
            return match.group(0)  # Return original ${VAR_NAME}
        return env_value

    return ENV_VAR_PATTERN.sub(replacer, value)


def load_env_file(env_file: str) -> int:
    """
    Load environment variables from a .env file.

    The file format is:
        VAR_NAME=value
        # Comments are ignored
        ANOTHER_VAR="quoted value"

    Variables are added to os.environ but do not override existing values.

    Args:
        env_file: Path to the .env file

    Returns:
        Number of variables loaded

    Raises:
        FileNotFoundError: If the env_file does not exist
    """
    env_path = Path(env_file)
    if not env_path.exists():
        raise FileNotFoundError(f"Environment file not found: {env_file}")

    count = 0
    with open(env_path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Parse VAR=value format
            if '=' not in line:
                logger.warning(
                    f"Invalid line {line_no} in {env_file}: missing '=' separator"
                )
                continue

            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()

            # Remove quotes if present
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]

            # Only set if not already in environment (don't override)
            if key not in os.environ:
                os.environ[key] = value
                count += 1
                logger.debug(f"Loaded environment variable: {key}")
            else:
                logger.debug(
                    f"Skipping {key} from {env_file}: already set in environment"
                )

    logger.info(f"Loaded {count} environment variables from {env_file}")
    return count


@dataclass
class CredentialManager:
    """
    Manages credentials for data source authentication.

    This class provides a centralized way to handle credentials including:
    - Environment variable substitution
    - Loading from .env files
    - Validating required credentials
    - Masking credentials in logs

    Attributes:
        env_substitution: Whether to perform env var substitution
        env_file: Path to optional .env file
    """

    env_substitution: bool = True
    env_file: Optional[str] = None
    _env_loaded: bool = False

    def __post_init__(self):
        """Load .env file if configured."""
        if self.env_file and not self._env_loaded:
            try:
                load_env_file(self.env_file)
                self._env_loaded = True
            except FileNotFoundError:
                logger.warning(f"Environment file not found: {self.env_file}")

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "CredentialManager":
        """
        Create a CredentialManager from configuration.

        Args:
            config: Configuration dictionary containing:
                - credentials.env_substitution: bool (default True)
                - credentials.env_file: str (optional path to .env file)

        Returns:
            Configured CredentialManager instance
        """
        cred_config = config.get("credentials", {})
        return cls(
            env_substitution=cred_config.get("env_substitution", True),
            env_file=cred_config.get("env_file")
        )

    def process_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a configuration dictionary, substituting environment variables.

        Args:
            config: Configuration dictionary to process

        Returns:
            Configuration with environment variables substituted
        """
        if not self.env_substitution:
            return config

        return substitute_env_vars(config, self.env_file)

    def get_credential(
        self,
        config: Dict[str, Any],
        key: str,
        required: bool = True
    ) -> Optional[str]:
        """
        Get a credential value from configuration.

        This method retrieves a credential, performing environment variable
        substitution if enabled.

        Args:
            config: Configuration dictionary
            key: Key to look up
            required: Whether to raise an error if missing

        Returns:
            The credential value, or None if not found and not required

        Raises:
            ValueError: If required credential is missing
        """
        value = config.get(key)
        if value is None:
            if required:
                raise ValueError(f"Required credential '{key}' is not configured")
            return None

        if self.env_substitution and isinstance(value, str):
            value = _substitute_in_string(value)

        # Check if substitution failed (still contains ${...})
        if isinstance(value, str) and ENV_VAR_PATTERN.search(value):
            unresolved = ENV_VAR_PATTERN.findall(value)
            if required:
                raise ValueError(
                    f"Credential '{key}' contains unresolved environment variables: "
                    f"{', '.join(unresolved)}"
                )
            logger.warning(
                f"Credential '{key}' has unresolved env vars: {unresolved}"
            )

        return value

    def validate_credentials(
        self,
        config: Dict[str, Any],
        required_keys: list
    ) -> list:
        """
        Validate that required credentials are present and resolved.

        Args:
            config: Configuration dictionary
            required_keys: List of required credential keys

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        for key in required_keys:
            try:
                value = self.get_credential(config, key, required=True)
                if not value:
                    errors.append(f"Credential '{key}' is empty")
            except ValueError as e:
                errors.append(str(e))

        return errors

    @staticmethod
    def mask_credential(value: str, show_chars: int = 4) -> str:
        """
        Mask a credential value for safe logging.

        Args:
            value: The credential value to mask
            show_chars: Number of characters to show at the end

        Returns:
            Masked value like '***abc123'
        """
        if not value or len(value) <= show_chars:
            return '***'

        return '***' + value[-show_chars:]

    def get_service_account_credentials(
        self,
        config: Dict[str, Any],
        credentials_file_key: str = "credentials_file"
    ) -> Optional[Dict[str, Any]]:
        """
        Load service account credentials from a JSON file.

        Args:
            config: Configuration dictionary
            credentials_file_key: Key containing path to credentials file

        Returns:
            Parsed credentials dictionary, or None if not configured

        Raises:
            FileNotFoundError: If credentials file doesn't exist
            ValueError: If credentials file is invalid JSON
        """
        import json

        cred_file = config.get(credentials_file_key)
        if not cred_file:
            return None

        # Substitute env vars in the path
        if self.env_substitution:
            cred_file = _substitute_in_string(cred_file)

        cred_path = Path(cred_file)
        if not cred_path.exists():
            raise FileNotFoundError(
                f"Service account credentials file not found: {cred_file}"
            )

        try:
            with open(cred_path, 'r', encoding='utf-8') as f:
                credentials = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Invalid JSON in credentials file {cred_file}: {e}"
            )

        logger.debug(f"Loaded service account credentials from {cred_file}")
        return credentials
