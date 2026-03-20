"""
CLI password reset utility for the Potato annotation platform.

Usage:
    python potato/flask_server.py reset-password <config.yaml> --username <user>
"""

import getpass
import logging
import sys

from potato.server_utils.config_module import init_config, config
from potato.authentication import UserAuthenticator

logger = logging.getLogger(__name__)


def cli_reset_password(args):
    """Reset a user's password from the command line.

    Args:
        args: Parsed command-line arguments (must include config_file, optionally username)
    """
    # Initialize config (loads YAML, sets up paths)
    init_config(args)

    # Initialize authenticator from config
    authenticator = UserAuthenticator.init_from_config(config)

    # Get username
    username = args.username
    if not username:
        username = input("Username: ").strip()
        if not username:
            print("Error: Username is required.")
            sys.exit(1)

    # Check that user exists
    if not authenticator.is_valid_username(username):
        print(f"Error: User '{username}' does not exist.")
        sys.exit(1)

    # Get new password
    new_password = getpass.getpass("New password: ")
    confirm_password = getpass.getpass("Confirm password: ")

    if new_password != confirm_password:
        print("Error: Passwords do not match.")
        sys.exit(1)

    if not new_password:
        print("Error: Password cannot be empty.")
        sys.exit(1)

    # Update password
    if authenticator.update_password(username, new_password):
        authenticator.save_user_config()
        print(f"Password for '{username}' has been reset successfully.")
    else:
        print(f"Error: Failed to reset password for '{username}'.")
        sys.exit(1)
