"""
Admin API Key Resolution

Shared utility for resolving the admin API key from config, environment,
or auto-generated key file. Used by both routes.py and admin.py to ensure
consistent authentication across all admin endpoints.
"""

import os
import hmac
import logging

logger = logging.getLogger(__name__)

# Cache for auto-generated admin API key
_generated_admin_api_key = None


def get_admin_api_key(config):
    """Get the admin API key from config, environment variable, or auto-generate one.

    Priority order:
    1. Config file: admin_api_key setting
    2. Environment variable: POTATO_ADMIN_API_KEY
    3. Auto-generated: Creates a random key and saves it to {task_dir}/admin_api_key.txt

    Args:
        config: The application config dict.

    Returns:
        str or None: The admin API key, or None if generation fails.
    """
    global _generated_admin_api_key

    # Check config first
    configured_key = config.get("admin_api_key")
    if configured_key:
        return configured_key

    # Check environment variable
    env_key = os.environ.get("POTATO_ADMIN_API_KEY")
    if env_key:
        return env_key

    # Return cached generated key if we have one
    if _generated_admin_api_key:
        return _generated_admin_api_key

    # Auto-generate a key and save it to task directory
    task_dir = config.get("task_dir", ".")
    if not task_dir:
        task_dir = "."

    key_file_path = os.path.join(task_dir, "admin_api_key.txt")

    # Check if a key file already exists (from previous run)
    if os.path.exists(key_file_path):
        try:
            with open(key_file_path, 'r', encoding='utf-8') as f:
                existing_key = f.read().strip()
                if existing_key:
                    _generated_admin_api_key = existing_key
                    logger.info(f"Loaded existing admin API key from {key_file_path}")
                    return _generated_admin_api_key
        except Exception as e:
            logger.warning(f"Could not read existing admin API key file: {e}")

    # Generate a new key
    import secrets
    _generated_admin_api_key = secrets.token_urlsafe(32)

    # Save to file
    try:
        with open(key_file_path, 'w', encoding='utf-8') as f:
            f.write(_generated_admin_api_key)
        logger.info(f"Generated admin API key and saved to {key_file_path}")
        logger.info(f"Use this key to access the admin dashboard at /admin")
    except Exception as e:
        logger.warning(f"Could not save admin API key to file: {e}")
        logger.info(f"Auto-generated admin API key (not persisted): {_generated_admin_api_key}")

    return _generated_admin_api_key


def validate_admin_api_key(provided_key, config):
    """Validate an admin API key against the configured or auto-generated key.

    Args:
        provided_key: The API key provided in the request.
        config: The application config dict.

    Returns:
        bool: True if the key is valid or debug mode is enabled.
    """
    if config.get("debug", False):
        return True

    expected_key = get_admin_api_key(config)
    if not expected_key:
        logger.warning("Could not obtain admin API key")
        return False

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(str(provided_key or ""), expected_key)
