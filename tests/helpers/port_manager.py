"""
Port management utilities for test infrastructure.

Provides reliable port allocation with retry logic to handle race conditions
that can occur when multiple tests run concurrently.
"""

import socket
import time
import random
import os
from threading import Lock
from typing import Optional, Set

# Global lock for port allocation (within this process)
_port_lock = Lock()

# Track allocated ports within this process to avoid reuse
_allocated_ports: Set[int] = set()

# Port range for test servers (high range to avoid conflicts with common services)
DEFAULT_PORT_RANGE = (9100, 9999)


def find_free_port(
    preferred_port: Optional[int] = None,
    port_range: tuple = DEFAULT_PORT_RANGE,
    max_attempts: int = 10
) -> int:
    """
    Find an available port with retry logic to handle race conditions.

    This function mitigates TOCTOU (Time-of-Check-Time-of-Use) race conditions
    by attempting multiple times with random ports from a range.

    Args:
        preferred_port: Preferred port to try first. If None or unavailable,
                       a random port from port_range is selected.
        port_range: Tuple of (min_port, max_port) to select from.
        max_attempts: Maximum number of attempts before raising an error.

    Returns:
        An available port number.

    Raises:
        RuntimeError: If no port could be found after max_attempts.
    """
    min_port, max_port = port_range

    with _port_lock:
        for attempt in range(max_attempts):
            # Determine which port to try
            if attempt == 0 and preferred_port is not None:
                port = preferred_port
            else:
                # Random port to reduce collision probability
                port = random.randint(min_port, max_port)

            # Skip ports we've already allocated in this process
            if port in _allocated_ports:
                continue

            # Check if port is available
            if _is_port_available(port):
                _allocated_ports.add(port)
                return port

            # Small delay before retry to let other processes release ports
            if attempt < max_attempts - 1:
                time.sleep(0.1 * (attempt + 1))

        raise RuntimeError(
            f"Could not find an available port after {max_attempts} attempts. "
            f"Tried range {min_port}-{max_port}. "
            f"Already allocated in this process: {len(_allocated_ports)} ports."
        )


def _is_port_available(port: int) -> bool:
    """
    Check if a port is available for binding.

    This is inherently racy (TOCTOU), but combined with retry logic
    in find_free_port(), it provides reliable port allocation.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('localhost', port))
            return True
    except (socket.error, OSError):
        return False


def release_port(port: int) -> None:
    """
    Mark a port as released (available for reuse).

    Call this when a test server shuts down to allow the port
    to be reused by other tests.

    Args:
        port: The port number to release.
    """
    with _port_lock:
        _allocated_ports.discard(port)


def get_unique_port_for_test(test_name: str, base_port: int = 9100) -> int:
    """
    Get a deterministic but unique port for a specific test.

    Uses the test name to generate a consistent port offset, reducing
    the chance of collisions between tests while being reproducible.

    Args:
        test_name: Name of the test (used to generate offset).
        base_port: Starting port number.

    Returns:
        A port number based on the test name.
    """
    # Generate a hash-based offset from the test name
    offset = hash(test_name) % 800  # Keep within a reasonable range
    preferred_port = base_port + abs(offset)

    return find_free_port(preferred_port=preferred_port)


def wait_for_port_release(port: int, timeout: float = 5.0) -> bool:
    """
    Wait for a port to become available.

    Useful when restarting a server on the same port.

    Args:
        port: The port to wait for.
        timeout: Maximum time to wait in seconds.

    Returns:
        True if the port became available, False if timeout occurred.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if _is_port_available(port):
            return True
        time.sleep(0.1)
    return False
