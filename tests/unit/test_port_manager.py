"""
Unit tests for test-server port allocation.

These guard a failure mode that is very hard to diagnose from the symptom. If
``_is_port_available`` reports a busy port as free, ``find_free_port`` hands it out,
the test server fails to bind ("Port N is in use by another program"), and the test
then talks to whatever process *was* listening on that port — typically a leftover
server from an earlier run, with a different admin key. The visible failure is an
unexplained 403 in a completely unrelated assertion.

The probe must therefore bind exactly the way the server under test binds:
``0.0.0.0``, without ``SO_REUSEADDR``.
"""

import socket

import pytest

from tests.helpers.port_manager import _is_port_available, find_free_port


@pytest.fixture
def bound_port():
    """A port held open the way werkzeug holds it: 0.0.0.0, no SO_REUSEADDR."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    yield port
    sock.close()


class TestIsPortAvailable:

    def test_reports_busy_port_as_unavailable(self, bound_port):
        """The regression: SO_REUSEADDR + localhost used to answer True here."""
        assert _is_port_available(bound_port) is False

    def test_reports_free_port_as_available(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("0.0.0.0", 0))
        port = sock.getsockname()[1]
        sock.close()
        assert _is_port_available(port) is True

    def test_probe_does_not_leave_the_port_bound(self):
        """Two probes in a row must both succeed, or the check would poison its own
        answer for the caller that is about to bind."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("0.0.0.0", 0))
        port = sock.getsockname()[1]
        sock.close()
        assert _is_port_available(port) is True
        assert _is_port_available(port) is True


class TestFindFreePort:

    def test_routes_around_a_busy_preferred_port(self, bound_port):
        """A hardcoded port in a test must not be handed out when it is occupied.
        53 files under tests/server/ pass a literal port, so this is the safety net
        for all of them rather than rewriting each one."""
        chosen = find_free_port(preferred_port=bound_port,
                                port_range=(bound_port - 40, bound_port + 40))
        assert chosen != bound_port
        assert _is_port_available(chosen) is True, (
            "find_free_port handed out a port that cannot actually be bound")

    def test_honours_an_available_preferred_port(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("0.0.0.0", 0))
        port = sock.getsockname()[1]
        sock.close()
        assert find_free_port(preferred_port=port,
                              port_range=(port - 40, port + 40)) == port
