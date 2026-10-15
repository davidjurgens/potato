"""
Admin API Key Resolution

Shared utility for resolving the admin API key from config, environment,
or auto-generated key file. Used by both routes.py and admin.py to ensure
consistent authentication across all admin endpoints.
"""

import ipaddress
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


def admin_api_key_source(config):
    """Where the key that ``get_admin_api_key`` returns comes from.

    ``"config"``, ``"env"`` or ``"file"``, in the same priority order. The
    admin login page used to say the key was in ``admin_api_key.txt`` even
    when the config file set ``admin_api_key`` inline, so an administrator
    who followed the instruction looked for a file that was never written.
    """
    if config.get("admin_api_key"):
        return "config"
    if os.environ.get("POTATO_ADMIN_API_KEY"):
        return "env"
    return "file"


def is_loopback_bind(config) -> bool:
    """True when the server is bound to loopback only.

    The debug conveniences are for a server only the developer can reach. On
    any other interface they are a way in for whoever else can connect.
    """
    host = str(config.get("host", "0.0.0.0")).strip()
    if host in ("localhost", ""):
        return host == "localhost"
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname we cannot classify. Treat as not-loopback: the failure
        # mode of guessing wrong in the other direction is an open admin API.
        return False


#: Headers a reverse proxy adds. A request carrying one came from elsewhere,
#: whatever its socket address says.
_FORWARDING_HEADERS = ("X-Forwarded-For", "X-Real-IP", "Forwarded")


def request_is_local(request) -> bool:
    """True when this request came from this machine: a loopback peer, and no
    proxy header saying it was forwarded from somewhere else."""
    try:
        if any(request.headers.get(h) for h in _FORWARDING_HEADERS):
            return False
        return ipaddress.ip_address(request.remote_addr or "").is_loopback
    except (ValueError, AttributeError, TypeError):
        return False


def debug_grants_admin(config, request=None) -> bool:
    """Whether `debug: true` should bypass admin authentication for this call.

    Debug bypassing the admin key is deliberate and documented, but it was
    unconditional, so a server started with `debug: true` on the default
    0.0.0.0 bind handed the admin dashboard and the admin API to anyone who
    could reach the port. It applies to requests from this machine: on a
    loopback bind every request is, and on any other bind (debug servers may
    be reached from other machines) the request must come over loopback with
    no forwarding header. Other callers need the admin API key, as without
    debug.
    """
    if not config.get("debug", False):
        return False
    if is_loopback_bind(config):
        return True
    if request is None:
        try:
            from flask import has_request_context, request as current
            request = current if has_request_context() else None
        except Exception:
            request = None
    return request is not None and request_is_local(request)


def validate_admin_api_key(provided_key, config):
    """Validate an admin API key against the configured or auto-generated key.

    Args:
        provided_key: The API key provided in the request.
        config: The application config dict.

    Returns:
        bool: True if the key is valid, or debug mode is enabled on a loopback
        bind.
    """
    if debug_grants_admin(config):
        return True

    expected_key = get_admin_api_key(config)
    if not expected_key:
        logger.warning("Could not obtain admin API key")
        return False

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(str(provided_key or ""), expected_key)
