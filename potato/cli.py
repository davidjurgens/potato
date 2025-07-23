#!/usr/bin/env python
"""
Command Line Interface for Potato Annotation Platform

This module provides the main CLI entry point for running the Potato annotation server.
It serves as a bridge between the command line and the Flask server application.

The CLI can be invoked directly or through the potato command after installation.
"""

from potato.flask_server import main
from potato import *

def potato():
    """
    Main CLI entry point for the Potato annotation platform.

    This function serves as the primary interface for starting the annotation server
    from the command line. It delegates to the main() function in flask_server.py
    which handles argument parsing, configuration loading, and server startup.

    Side Effects:
        - Initializes the Flask application
        - Loads configuration from files
        - Starts the web server on the configured port
        - Sets up logging and error handling
    """
    main()


if __name__ == '__main__':
    # Direct script execution - start the Potato annotation server
    potato()