"""
Authentication System Module

This module provides a comprehensive authentication system for the Potato annotation platform.
It supports multiple authentication backends including in-memory storage, database storage,
and third-party SSO providers like Clerk.

The system is designed to be extensible and supports both password-based and passwordless
authentication modes. It includes user management, session validation, and secure
password handling.

Key Features:
- Multiple authentication backends (in-memory, database, Clerk SSO)
- Password hashing with PBKDF2 and per-user salts
- Passwordless authentication support
- User registration and management
- Password reset with secure tokens
- Session-based authentication
- Configurable authentication requirements
"""

import os
import json
import logging
import hashlib
import hmac
import secrets
import sqlite3
import requests
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Union

logger = logging.getLogger(__name__)

# Global singleton instance of the user authenticator with thread-safe lock
USER_AUTHENTICATOR_SINGLETON = None
_USER_AUTHENTICATOR_LOCK = threading.Lock()

# Format for per-user salt storage: "<32-char-hex-salt>$<hash-hex>"
_SALT_HASH_SEPARATOR = "$"


def _is_salted_hash(value: str) -> bool:
    """Check if a stored password value is in the per-user salt$hash format."""
    if not value or _SALT_HASH_SEPARATOR not in value:
        return False
    parts = value.split(_SALT_HASH_SEPARATOR, 1)
    # salt is 32 hex chars (16 bytes), hash is 64 hex chars (32 bytes sha256)
    return len(parts) == 2 and len(parts[0]) == 32 and len(parts[1]) == 64


def _hash_password_with_salt(password: str, salt: str = None) -> str:
    """Hash a password with a per-user salt using PBKDF2.

    Args:
        password: The plain text password to hash
        salt: Hex-encoded salt string. If None, generates a new random salt.

    Returns:
        str: The combined "salt$hash" string
    """
    if not password:
        return ""
    if salt is None:
        salt = secrets.token_hex(16)
    hash_value = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return f"{salt}{_SALT_HASH_SEPARATOR}{hash_value}"


def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored salt$hash value using constant-time comparison."""
    if not password or not stored:
        return False
    if not _is_salted_hash(stored):
        return False
    salt, expected_hash = stored.split(_SALT_HASH_SEPARATOR, 1)
    actual_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return hmac.compare_digest(expected_hash, actual_hash)


class AuthBackend(ABC):
    """
    Abstract base class for authentication backends.

    This class defines the interface that all authentication backends must implement.
    It provides a consistent API for user authentication, registration, and validation
    regardless of the underlying storage mechanism.
    """
    @abstractmethod
    def authenticate(self, username: str, password: Optional[str]) -> bool:
        """Authenticate a user against this backend."""
        pass

    @abstractmethod
    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        """Add a user to this backend. Returns status message."""
        pass

    @abstractmethod
    def is_valid_username(self, username: str) -> bool:
        """Check if a username exists in this backend."""
        pass

    @abstractmethod
    def update_password(self, username: str, new_password: str) -> bool:
        """Update a user's password. Returns True on success."""
        pass

    @abstractmethod
    def get_all_users(self) -> List[str]:
        """Return list of all usernames."""
        pass

    def add_user_prehashed(self, username: str, hashed_password: str, **kwargs) -> str:
        """Load user with already-hashed password (for file loading). Override in subclasses."""
        raise NotImplementedError("This backend does not support loading pre-hashed passwords")


class InMemoryAuthBackend(AuthBackend):
    """
    Authentication backend that stores users in memory with per-user salts.

    Password storage format: "salt$hash" where salt is 32 hex chars and hash is 64 hex chars.
    """
    def __init__(self):
        self.users = {}  # username -> "salt$hash"
        self.user_data = {}  # username -> additional data

    def authenticate(self, username: str, password: Optional[str]) -> bool:
        if username not in self.users:
            return False
        if password is None:  # Passwordless login
            return True
        return _verify_password(password, self.users[username])

    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        if username in self.users:
            return "Duplicate user"
        self.users[username] = _hash_password_with_salt(password) if password else ""
        self.user_data[username] = kwargs
        return "Success"

    def add_user_prehashed(self, username: str, hashed_password: str, **kwargs) -> str:
        """Store a user with an already-hashed password (salt$hash format)."""
        if username in self.users:
            return "Duplicate user"
        self.users[username] = hashed_password
        self.user_data[username] = kwargs
        return "Success"

    def is_valid_username(self, username: str) -> bool:
        return username in self.users

    def update_password(self, username: str, new_password: str) -> bool:
        if username not in self.users:
            return False
        self.users[username] = _hash_password_with_salt(new_password)
        return True

    def get_all_users(self) -> List[str]:
        return list(self.users.keys())


class DatabaseAuthBackend(AuthBackend):
    """
    Authentication backend using SQLite (stdlib) or PostgreSQL (psycopg2).

    Connection string formats:
        sqlite:///path/to/db.db     (relative or absolute)
        postgresql://user:pass@host/dbname
    """
    def __init__(self, db_connection_string: str):
        self.db_connection_string = db_connection_string
        self._lock = threading.Lock()
        self._db_type = None  # 'sqlite' or 'postgresql'
        self._connection = None

        if db_connection_string.startswith("sqlite:///"):
            self._db_type = "sqlite"
            self._init_sqlite(db_connection_string[len("sqlite:///"):])
        elif db_connection_string.startswith("postgresql://"):
            self._db_type = "postgresql"
            self._init_postgresql(db_connection_string)
        else:
            raise ValueError(
                f"Unsupported database URL: {db_connection_string}. "
                "Use sqlite:///path/to/db or postgresql://user:pass@host/dbname"
            )

        logger.info(f"Database auth backend initialized ({self._db_type})")

    def _init_sqlite(self, db_path: str):
        """Initialize SQLite database."""
        # Create parent directories if needed
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                email TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self._connection.commit()

    def _init_postgresql(self, connection_string: str):
        """Initialize PostgreSQL database."""
        try:
            import psycopg2
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL authentication backend. "
                "Install it with: pip install psycopg2-binary"
            )
        self._connection = psycopg2.connect(connection_string)
        self._connection.autocommit = True
        with self._connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

    def _execute(self, query: str, params: tuple = (), fetch: str = None):
        """Thread-safe query execution.

        Args:
            query: SQL query with ? placeholders (auto-converted to %s for PostgreSQL)
            params: Query parameters
            fetch: None, 'one', or 'all'

        Returns:
            Query result based on fetch parameter
        """
        with self._lock:
            if self._db_type == "postgresql":
                query = query.replace("?", "%s")

            if self._db_type == "sqlite":
                cursor = self._connection.cursor()
                cursor.execute(query, params)
                if fetch == "one":
                    result = cursor.fetchone()
                elif fetch == "all":
                    result = cursor.fetchall()
                else:
                    self._connection.commit()
                    result = None
                cursor.close()
                return result
            else:
                with self._connection.cursor() as cur:
                    cur.execute(query, params)
                    if fetch == "one":
                        return cur.fetchone()
                    elif fetch == "all":
                        return cur.fetchall()
                    return None

    def authenticate(self, username: str, password: Optional[str]) -> bool:
        row = self._execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,), fetch="one"
        )
        if not row:
            return False
        if password is None:  # Passwordless login
            return True
        return _verify_password(password, row[0])

    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        existing = self._execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,), fetch="one"
        )
        if existing:
            return "Duplicate user"

        hashed = _hash_password_with_salt(password) if password else ""
        email = kwargs.get("email", "")
        self._execute(
            "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
            (username, hashed, email)
        )
        return "Success"

    def add_user_prehashed(self, username: str, hashed_password: str, **kwargs) -> str:
        """Store a user with an already-hashed password."""
        existing = self._execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,), fetch="one"
        )
        if existing:
            return "Duplicate user"

        email = kwargs.get("email", "")
        self._execute(
            "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
            (username, hashed_password, email)
        )
        return "Success"

    def is_valid_username(self, username: str) -> bool:
        row = self._execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,), fetch="one"
        )
        return row is not None

    def update_password(self, username: str, new_password: str) -> bool:
        if not self.is_valid_username(username):
            return False
        hashed = _hash_password_with_salt(new_password)
        if self._db_type == "sqlite":
            self._execute(
                "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE username = ?",
                (hashed, username)
            )
        else:
            self._execute(
                "UPDATE users SET password_hash = ?, updated_at = NOW() WHERE username = ?",
                (hashed, username)
            )
        return True

    def get_all_users(self) -> List[str]:
        rows = self._execute("SELECT username FROM users", fetch="all")
        return [r[0] for r in rows]

    def close(self):
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None


class ClerkAuthBackend(AuthBackend):
    """
    Authentication backend that uses Clerk for SSO.
    """
    def __init__(self, api_key: str, frontend_api: str):
        self.api_key = api_key
        self.frontend_api = frontend_api
        self.users = {}  # Cache of known users
        logger.info("Clerk SSO backend initialized")

    def authenticate(self, username: str, token: Optional[str]) -> bool:
        if not token:
            return False
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            response = requests.get(
                f"https://api.clerk.dev/v1/sessions/{token}",
                headers=headers
            )
            if response.status_code == 200:
                user_data = response.json()
                self.users[username] = user_data
                return True
            return False
        except Exception as e:
            logger.error(f"Error authenticating with Clerk: {str(e)}")
            return False

    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        return "User management happens through Clerk dashboard"

    def is_valid_username(self, username: str) -> bool:
        return username in self.users

    def update_password(self, username: str, new_password: str) -> bool:
        raise NotImplementedError("Password management is handled by Clerk")

    def get_all_users(self) -> List[str]:
        return list(self.users.keys())


class UserAuthenticator:
    """
    A class for maintaining state on which users are allowed to use the system.

    This class provides a unified interface for user authentication and management
    regardless of the underlying backend. It supports multiple authentication methods
    and can be configured for passwordless operation.
    """

    def __init__(self, user_config_path, auth_method="in_memory", auth_config=None):
        self.allow_all_users = True
        self.user_config_path = user_config_path
        self.user_config_path_explicit = False  # Set to True if path was explicitly configured
        self.authorized_users = []
        self.userlist = []
        self.usernames = set()
        self.users = {}
        self.required_user_info_keys = ["username", "password"]
        self.require_password = True
        self.auth_method = auth_method
        self.auth_config = auth_config or {}
        self.auth_backend = self._initialize_backend(auth_method, auth_config)

        # Token management for password reset
        self._reset_tokens = {}  # token -> {username, expires}
        self._token_lock = threading.Lock()

        # Load users from config file if it exists
        if os.path.isfile(self.user_config_path):
            logger.info(f"Loading users from {self.user_config_path}")
            with open(self.user_config_path, "rt", encoding="utf-8") as f:
                for line in f.readlines():
                    line = line.strip()
                    if not line:
                        continue
                    single_user = json.loads(line)
                    # Detect salt$hash format in password field
                    password_val = single_user.get("password", "")
                    if password_val and _is_salted_hash(password_val):
                        self._add_user_prehashed(single_user)
                    else:
                        self.add_single_user(single_user)

    def _initialize_backend(self, auth_method: str, auth_config: dict = None) -> AuthBackend:
        if auth_method == "in_memory":
            return InMemoryAuthBackend()
        elif auth_method == "database":
            db_url = (auth_config or {}).get("database_url") or \
                     os.environ.get("POTATO_DB_CONNECTION", "sqlite:///potato_users.db")
            return DatabaseAuthBackend(db_url)
        elif auth_method == "clerk":
            api_key = os.environ.get("CLERK_API_KEY", "")
            frontend_api = os.environ.get("CLERK_FRONTEND_API", "")
            if not api_key:
                logger.error("CLERK_API_KEY environment variable is not set")
                raise ValueError("CLERK_API_KEY must be set for Clerk authentication")
            return ClerkAuthBackend(api_key, frontend_api)
        elif auth_method == "oauth":
            from potato.auth_backends.oauth_backend import OAuthBackend
            if not auth_config:
                raise ValueError("OAuth authentication requires an 'authentication' config section with 'providers'")
            return OAuthBackend(auth_config)
        else:
            logger.error(f"Unknown authentication method: {auth_method}")
            raise ValueError(f"Unknown authentication method: {auth_method}")

    @staticmethod
    def init_from_config(config: dict) -> "UserAuthenticator":
        """Initialize the UserAuthenticator from a configuration dictionary (singleton)."""
        global USER_AUTHENTICATOR_SINGLETON

        if USER_AUTHENTICATOR_SINGLETON is None:
            with _USER_AUTHENTICATOR_LOCK:
                if USER_AUTHENTICATOR_SINGLETON is None:
                    auth_method = config.get("authentication", {}).get("method", "in_memory")
                    user_config_path = config.get("authentication", {}).get("user_config_path", None)
                    require_password = config.get("require_password", True)

                    path_explicit = user_config_path is not None

                    if user_config_path is None:
                        config_dir = os.path.dirname(config['output_annotation_dir'])
                        user_config_path = os.path.join(config_dir, "user_config.json")
                    else:
                        # Don't raise if file doesn't exist — it will be created on first registration
                        if not os.path.isfile(user_config_path):
                            logger.info(f"user_config_path '{user_config_path}' does not exist yet; will be created on first registration")

                    logger.debug(f"User config path: {user_config_path}")

                    auth_config = config.get("authentication", {})

                    USER_AUTHENTICATOR_SINGLETON = UserAuthenticator(user_config_path, auth_method, auth_config)
                    USER_AUTHENTICATOR_SINGLETON.require_password = require_password
                    USER_AUTHENTICATOR_SINGLETON.user_config_path_explicit = path_explicit

                    logger.info(f"Initialized UserAuthenticator with method: {auth_method}, require_password: {require_password}")

        return USER_AUTHENTICATOR_SINGLETON

    @staticmethod
    def get_instance():
        global USER_AUTHENTICATOR_SINGLETON
        if USER_AUTHENTICATOR_SINGLETON is None:
            raise ValueError("UserAuthenticator not initialized; call init_from_config first")
        return USER_AUTHENTICATOR_SINGLETON

    @staticmethod
    def authenticate(username: str, password: Optional[str]) -> bool:
        authenticator = UserAuthenticator.get_instance()

        if not authenticator.auth_backend.is_valid_username(username):
            logger.warning(f"Authentication failed: user '{username}' does not exist")
            return False

        if not authenticator.require_password:
            logger.debug(f"Passwordless authentication for user: {username}")
            return authenticator.auth_backend.authenticate(username, None)

        return authenticator.auth_backend.authenticate(username, password)

    def add_user(self, username, password: Optional[str], **kwargs):
        """Add a user to the authentication system."""
        if not self.require_password:
            logger.debug(f"Passwordless mode - allowing any user: {username}")
        elif self.allow_all_users == False and not self.is_authorized_user(username):
            return "Unauthorized user"

        result = self.auth_backend.add_user(username, password, **kwargs)
        if result == "Success":
            user_data = {"username": username}
            user_data.update(kwargs)
            self.users[username] = user_data
            self.userlist.append(username)
        return result

    def _add_user_prehashed(self, single_user):
        """Add a user with an already-hashed password (loaded from file)."""
        username = single_user["username"]
        hashed_password = single_user.get("password", "")

        result = self.auth_backend.add_user_prehashed(
            username,
            hashed_password,
            **{k: v for k, v in single_user.items() if k not in ["username", "password"]}
        )

        if result == "Success":
            self.users[username] = single_user
            self.userlist.append(username)

        return result

    def add_single_user(self, single_user):
        """Add a single user to the full user dict."""
        if not self.require_password:
            logger.debug(f"Passwordless mode - allowing any user: {single_user['username']}")
        elif self.allow_all_users == False and not self.is_authorized_user(single_user["username"]):
            return "Unauthorized user"

        if not self.require_password:
            required_keys = ["username"]
        else:
            required_keys = self.required_user_info_keys

        for key in required_keys:
            if key not in single_user:
                logger.error(f"Missing {key} in user info")
                return f"Missing {key} in user info"

        result = self.auth_backend.add_user(
            single_user["username"],
            single_user.get("password"),
            **{k: v for k, v in single_user.items() if k not in ["username", "password"]}
        )

        if result == "Success":
            self.users[single_user["username"]] = single_user
            self.userlist.append(single_user["username"])

        return result

    def update_password(self, username: str, new_password: str) -> bool:
        """Update a user's password via the backend."""
        result = self.auth_backend.update_password(username, new_password)
        if result and username in self.users:
            # Update the stored user dict with the new hash for save_user_config
            if isinstance(self.users[username], dict):
                self.users[username]["password"] = self.auth_backend.users[username] \
                    if hasattr(self.auth_backend, 'users') else _hash_password_with_salt(new_password)
        return result

    def save_user_config(self):
        """Save user config to file.

        Saves when:
        - auth_method is in_memory AND user_config_path was explicitly configured
        - auth_method is not in_memory and not database (other file-based methods)

        Skips when:
        - auth_method is database (DB handles its own persistence)
        - auth_method is in_memory with auto-generated default path (preserve old behavior)
        """
        if self.auth_method == "database":
            logger.debug("User config not saved - using database authentication (DB handles persistence)")
            return

        if self.auth_method == "in_memory" and not self.user_config_path_explicit:
            logger.debug("User config not saved - using in_memory with default path")
            return

        if self.user_config_path:
            with open(self.user_config_path, "wt", encoding="utf-8") as f:
                for k in self.userlist:
                    user_data = self.users.get(k, {})
                    if isinstance(user_data, dict):
                        # Ensure password field contains the hashed value
                        output = dict(user_data)
                        if hasattr(self.auth_backend, 'users') and k in self.auth_backend.users:
                            output["password"] = self.auth_backend.users[k]
                        f.write(json.dumps(output) + "\n")
                    else:
                        f.write(json.dumps({"username": k}) + "\n")
            logger.info(f"User info file saved at: {self.user_config_path}")
        else:
            logger.warning("WARNING: user_config_path not specified, user registration info are not saved")

    # --- Token-based password reset ---

    def create_reset_token(self, username: str, ttl_hours: int = 24) -> Optional[str]:
        """Create a password reset token for a user.

        Args:
            username: The username to create a token for
            ttl_hours: Token validity in hours (default 24)

        Returns:
            The token string, or None if user doesn't exist
        """
        if not self.auth_backend.is_valid_username(username):
            return None

        token = secrets.token_urlsafe(32)
        expires = time.time() + (ttl_hours * 3600)

        with self._token_lock:
            # Invalidate any existing tokens for this user
            self._reset_tokens = {
                t: v for t, v in self._reset_tokens.items()
                if v["username"] != username
            }
            self._reset_tokens[token] = {
                "username": username,
                "expires": expires
            }

        return token

    def validate_reset_token(self, token: str) -> Optional[str]:
        """Validate a reset token and return the username, or None if invalid/expired."""
        with self._token_lock:
            # Clean expired tokens
            now = time.time()
            self._reset_tokens = {
                t: v for t, v in self._reset_tokens.items()
                if v["expires"] > now
            }

            if token not in self._reset_tokens:
                return None
            return self._reset_tokens[token]["username"]

    def consume_reset_token(self, token: str) -> Optional[str]:
        """Validate, delete, and return the username for a reset token. Single-use."""
        with self._token_lock:
            now = time.time()
            self._reset_tokens = {
                t: v for t, v in self._reset_tokens.items()
                if v["expires"] > now
            }

            if token not in self._reset_tokens:
                return None
            username = self._reset_tokens[token]["username"]
            del self._reset_tokens[token]
            return username

    # --- End token management ---

    def is_authorized_user(self, username):
        return username in self.authorized_users

    def is_valid_username(self, username):
        return self.auth_backend.is_valid_username(username)

    def is_valid_password(self, username, password):
        return self.authenticate(username, password)

    def get_clerk_frontend_api(self) -> str:
        if self.auth_method == "clerk" and isinstance(self.auth_backend, ClerkAuthBackend):
            return self.auth_backend.frontend_api
        return ""

    def get_oauth_backend(self):
        if self.auth_method == "oauth":
            return self.auth_backend
        return None

    def get_login_providers(self) -> list:
        oauth_backend = self.get_oauth_backend()
        if oauth_backend:
            return oauth_backend.get_login_providers()
        return []
