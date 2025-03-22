import os
import json
import logging
import hashlib
import secrets
import requests
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Union

logger = logging.getLogger(__name__)

USER_AUTHENTICATOR_SINGLETON = None

class AuthBackend(ABC):
    """
    Abstract base class for authentication backends
    """
    @abstractmethod
    def authenticate(self, username: str, password: Optional[str]) -> bool:
        """Authenticate a user against this backend"""
        pass

    @abstractmethod
    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        """Add a user to this backend"""
        pass

    @abstractmethod
    def is_valid_username(self, username: str) -> bool:
        """Check if a username exists in this backend"""
        pass

class InMemoryAuthBackend(AuthBackend):
    """
    Authentication backend that stores users in memory only
    """
    def __init__(self):
        self.users = {}  # username -> password_hash
        self.user_data = {}  # username -> additional data
        self.salt = secrets.token_hex(16)

    def _hash_password(self, password: str) -> str:
        """Hash a password with the salt"""
        if not password:
            return ""
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            self.salt.encode('utf-8'),
            100000
        ).hex()

    def authenticate(self, username: str, password: Optional[str]) -> bool:
        """Authenticate a user against in-memory store"""
        if username not in self.users:
            return False

        if password is None:  # Passwordless login
            return True

        hashed = self._hash_password(password)
        return self.users[username] == hashed

    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        """Add a user to the in-memory store"""
        if username in self.users:
            return "Duplicate user"

        # Store password hash
        self.users[username] = self._hash_password(password) if password else ""

        # Store additional user data
        self.user_data[username] = kwargs

        return "Success"

    def is_valid_username(self, username: str) -> bool:
        """Check if a username exists"""
        return username in self.users

class DatabaseAuthBackend(AuthBackend):
    """
    Authentication backend that stores users in a database
    """
    def __init__(self, db_connection_string: str):
        self.db_connection_string = db_connection_string
        # This is a placeholder - in a real implementation, you would:
        # 1. Connect to the database
        # 2. Create tables if they don't exist
        # 3. Set up indexes for username lookups

        # For simplicity, we'll use a dict as our "database" for this example
        self.users = {}

        logger.info(f"Database auth backend initialized with connection: {db_connection_string}")

    def authenticate(self, username: str, password: Optional[str]) -> bool:
        """Authenticate a user against the database"""
        # In a real implementation, you would:
        # 1. Query the database for the user
        # 2. Verify the password hash using a secure method

        if username not in self.users:
            return False

        if password is None:  # Passwordless login
            return True

        # This is insecure - only for demonstration
        # In production, use a proper password hashing library
        return self.users[username] == password

    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        """Add a user to the database"""
        # In a real implementation, you would:
        # 1. Hash the password
        # 2. Insert the user into the database
        # 3. Handle duplicate username errors

        if username in self.users:
            return "Duplicate user"

        self.users[username] = password
        return "Success"

    def is_valid_username(self, username: str) -> bool:
        """Check if a username exists in the database"""
        # In a real implementation, you would query the database
        return username in self.users

class ClerkAuthBackend(AuthBackend):
    """
    Authentication backend that uses Clerk for SSO
    """
    def __init__(self, api_key: str, frontend_api: str):
        self.api_key = api_key
        self.frontend_api = frontend_api
        self.users = {}  # Cache of known users

        logger.info("Clerk SSO backend initialized")

    def authenticate(self, username: str, token: Optional[str]) -> bool:
        """Authenticate a user using Clerk token"""
        if not token:
            return False

        # Verify the token with Clerk API
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            # This is a simplified example - in production you would use the Clerk SDK
            # or follow their API documentation for token verification
            response = requests.get(
                f"https://api.clerk.dev/v1/sessions/{token}",
                headers=headers
            )

            if response.status_code == 200:
                user_data = response.json()
                # Cache the user
                self.users[username] = user_data
                return True

            return False

        except Exception as e:
            logger.error(f"Error authenticating with Clerk: {str(e)}")
            return False

    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        """
        Add a user to Clerk - this typically happens on Clerk's side,
        not through our application
        """
        return "User management happens through Clerk dashboard"

    def is_valid_username(self, username: str) -> bool:
        """Check if a username exists in Clerk"""
        # In a real implementation, you would query Clerk's API
        # For now, we'll just check our local cache
        return username in self.users

class UserAuthenticator:
    """
    A class for maintaining state on which users are allowed to use the system
    """

    def __init__(self, user_config_path, auth_method="in_memory"):
        self.allow_all_users = True
        self.user_config_path = user_config_path
        self.authorized_users = []
        self.userlist = []
        self.usernames = set()
        self.users = {}
        self.required_user_info_keys = ["username", "password"]
        self.require_password = True
        self.auth_method = auth_method
        self.auth_backend = self._initialize_backend(auth_method)

        # Load users from config file if it exists
        if os.path.isfile(self.user_config_path):
            logger.info(f"Loading users from {self.user_config_path}")
            with open(self.user_config_path, "rt") as f:
                for line in f.readlines():
                    single_user = json.loads(line.strip())
                    self.add_single_user(single_user)

    def _initialize_backend(self, auth_method: str) -> AuthBackend:
        """Initialize the appropriate authentication backend"""
        if auth_method == "in_memory":
            return InMemoryAuthBackend()
        elif auth_method == "database":
            db_conn = os.environ.get("POTATO_DB_CONNECTION", "sqlite:///potato/users.db")
            return DatabaseAuthBackend(db_conn)
        elif auth_method == "clerk":
            api_key = os.environ.get("CLERK_API_KEY", "")
            frontend_api = os.environ.get("CLERK_FRONTEND_API", "")
            if not api_key:
                logger.error("CLERK_API_KEY environment variable is not set")
                raise ValueError("CLERK_API_KEY must be set for Clerk authentication")
            return ClerkAuthBackend(api_key, frontend_api)
        else:
            logger.error(f"Unknown authentication method: {auth_method}")
            raise ValueError(f"Unknown authentication method: {auth_method}")

    @staticmethod
    def init_from_config(config: dict) -> "UserAuthenticator":
        '''
        Initialize the UserAuthenticator from a configuration dictionary
        '''
        global USER_AUTHENTICATOR_SINGLETON
        if USER_AUTHENTICATOR_SINGLETON is None:
            # Determine authentication method from config
            auth_method = config.get("authentication", {}).get("method", "in_memory")

            # Get config path if specified
            user_config_path = config.get("authentication", {}).get("user_config_path", None)

            # Check if password is required
            require_password = config.get("require_password", True)

            # See if the user_config_path has been set
            if user_config_path is None:
                # If not, set it to the default path where the annotators are
                # stored
                config_dir = os.path.dirname(config['output_annotation_dir'])
                user_config_path = os.path.join(config_dir, "user_config.json")
            else:
                # If it has been set, make sure it's a valid path
                if not os.path.isfile(user_config_path):
                    logger.error(f"Invalid user_config_path: {user_config_path}")
                    raise ValueError(f"Invalid user_config_path: {user_config_path}")

            print(f"User config path: {user_config_path}")

            # Initialize the authenticator
            USER_AUTHENTICATOR_SINGLETON = UserAuthenticator(user_config_path, auth_method)
            USER_AUTHENTICATOR_SINGLETON.require_password = require_password

            logger.info(f"Initialized UserAuthenticator with method: {auth_method}, require_password: {require_password}")

        return USER_AUTHENTICATOR_SINGLETON

    @staticmethod
    def get_instance():
        '''
        Get the singleton instance of the UserAuthenticator
        '''
        global USER_AUTHENTICATOR_SINGLETON
        if USER_AUTHENTICATOR_SINGLETON is None:
            raise ValueError("UserAuthenticator not initialized; call init_from_config first")
        return USER_AUTHENTICATOR_SINGLETON

    @staticmethod
    def authenticate(username: str, password: Optional[str]) -> bool:
        """
        Authenticate a user with the current authentication backend
        """
        authenticator = UserAuthenticator.get_instance()

        # If passwords are not required, bypass password check
        if not authenticator.require_password:
            # Force password to None for passwordless authentication
            return authenticator.auth_backend.authenticate(username, None)

        # Regular password authentication
        return authenticator.auth_backend.authenticate(username, password)

    # This function will be deprecated
    def add_user(self, username, password: Optional[str], **kwargs):
        # For passwordless mode, don't enforce authorization checks
        if not self.require_password:
            logger.debug(f"Passwordless mode - allowing any user: {single_user['username']}")
        elif self.allow_all_users == False and not self.is_authorized_user(single_user["username"]):
            return "Unauthorized user"

        result = self.auth_backend.add_user(username, password, **kwargs)
        if result == "Success":
            self.users[username] = kwargs
            self.userlist.append(username)
        return result

    def add_single_user(self, single_user):
        """
        Add a single user to the full user dict
        """
        # For passwordless mode, don't enforce authorization checks
        if not self.require_password:
            logger.debug(f"Passwordless mode - allowing any user: {single_user['username']}")
        elif self.allow_all_users == False and not self.is_authorized_user(single_user["username"]):
            return "Unauthorized user"

        # In passwordless mode, we only need username
        if not self.require_password:
            required_keys = ["username"]
        else:
            required_keys = self.required_user_info_keys

        for key in required_keys:
            if key not in single_user:
                logger.error(f"Missing {key} in user info")
                return f"Missing {key} in user info"

        # Add user to the backend
        result = self.auth_backend.add_user(
            single_user["username"],
            single_user.get("password"),
            **{k: v for k, v in single_user.items() if k not in ["username", "password"]}
        )

        if result == "Success":
            # Update internal tracking
            self.users[single_user["username"]] = single_user
            self.userlist.append(single_user["username"])

        return result

    def save_user_config(self):
        """
        Save user config to file - only applicable for in_memory authentication
        """
        if self.auth_method == "in_memory":
            logger.info(f"User config not saved - using {self.auth_method} authentication")
            return

        elif self.user_config_path:
            with open(self.user_config_path, "wt") as f:
                for k in self.userlist:
                    f.write(json.dumps(self.users[k]) + "\n")
            logger.info(f"User info file saved at: {self.user_config_path}")
        else:
            logger.warning("WARNING: user_config_path not specified, user registration info are not saved")

    def is_authorized_user(self, username):
        """
        Check if a user name is in the authorized user list (as presented in the configuration file).
        """
        return username in self.authorized_users

    def is_valid_username(self, username):
        """
        Check if a user name is in the current user list.
        """
        return self.auth_backend.is_valid_username(username)

    def is_valid_password(self, username, password):
        """
        Check if the password is correct for a given (username, password) pair.
        """
        return self.authenticate(username, password)

    def get_clerk_frontend_api(self) -> str:
        """Get the Clerk frontend API key if using Clerk authentication"""
        if self.auth_method == "clerk" and isinstance(self.auth_backend, ClerkAuthBackend):
            return self.auth_backend.frontend_api
        return ""