"""
Conftest for archived Selenium tests.

This prevents pytest from collecting tests in this directory.
These tests are kept for reference but are no longer part of the active test suite.
"""

# Ignore all files in this directory
collect_ignore_glob = ["*.py"]
