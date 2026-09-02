"""
Tests for the shared SSRF guard.

The endpoints these protect were unauthenticated and fetched any URL a caller
supplied, so the guard is the whole defence. Each case here is an evasion that
a scheme-prefix check (the thing this replaced) lets through.
"""

import socket
from unittest.mock import patch

import pytest

from potato.server_utils.url_guard import (
    URLNotAllowed,
    _ip_is_blocked,
    resolve_public_addresses,
    validate_url,
)


class TestBlockedAddresses:
    @pytest.mark.parametrize("ip,label", [
        ("127.0.0.1", "loopback"),
        ("127.1.2.3", "loopback range"),
        ("10.0.0.1", "private 10/8"),
        ("172.16.5.4", "private 172.16/12"),
        ("192.168.1.1", "private 192.168/16"),
        ("169.254.169.254", "cloud metadata"),
        ("169.254.1.1", "link-local"),
        ("100.64.0.1", "CGNAT"),
        ("0.0.0.0", "unspecified"),
        ("224.0.0.1", "multicast"),
        ("::1", "v6 loopback"),
        ("fd00::1", "v6 unique local"),
        ("fe80::1", "v6 link-local"),
        ("::ffff:127.0.0.1", "v4-mapped loopback"),
    ])
    def test_blocked(self, ip, label):
        assert _ip_is_blocked(ip) is not None, "%s (%s) should be blocked" % (ip, label)

    @pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1"])
    def test_public_addresses_allowed(self, ip):
        assert _ip_is_blocked(ip) is None


class TestSchemes:
    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "gopher://evil.example/",
        "ftp://example.com/x",
        "data:text/plain,hello",
    ])
    def test_non_http_schemes_rejected(self, url):
        with pytest.raises(URLNotAllowed):
            validate_url(url)

    def test_missing_host_rejected(self):
        with pytest.raises(URLNotAllowed):
            validate_url("http:///nohost")

    def test_empty_url_rejected(self):
        with pytest.raises(URLNotAllowed):
            validate_url("")


class TestEncodedLoopback:
    """A scheme check does not care how the host is spelled; resolution does."""

    @pytest.mark.parametrize("url", [
        "http://2130706433/",       # decimal 127.0.0.1
        "http://0x7f000001/",       # hex
        "http://127.0.0.1/",
        "http://localhost/",
        "http://[::1]/",
    ])
    def test_blocked(self, url):
        with pytest.raises(URLNotAllowed):
            validate_url(url)


class TestFailsClosed:
    def test_unresolvable_host_is_refused(self):
        # The previous validator allowed this, reasoning that the fetch would
        # fail anyway. A name that fails once can answer on the retry.
        with pytest.raises(URLNotAllowed):
            validate_url("http://nonexistent-host-for-tests.invalid/")

    def test_any_blocked_address_rejects_the_host(self):
        """A name with one public and one private address is a rebind primitive."""
        infos = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ]
        with patch("socket.getaddrinfo", return_value=infos):
            with pytest.raises(URLNotAllowed):
                resolve_public_addresses("split.example", 80)

    def test_no_addresses_rejected(self):
        with patch("socket.getaddrinfo", return_value=[]):
            with pytest.raises(URLNotAllowed):
                resolve_public_addresses("empty.example", 80)


class TestAllowlist:
    def test_allowlisted_host_skips_resolution(self):
        parsed, addrs = validate_url("http://internal-media/x.mp3",
                                     allowlist=["internal-media"])
        assert parsed.hostname == "internal-media"
        assert addrs == []

    def test_allowlist_does_not_cover_other_hosts(self):
        with pytest.raises(URLNotAllowed):
            validate_url("http://169.254.169.254/", allowlist=["internal-media"])


class TestPinning:
    def test_public_host_returns_the_address_to_connect_to(self):
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch("socket.getaddrinfo", return_value=infos):
            parsed, addrs = validate_url("https://example.com/a.mp3")
        # Returning the address is what lets the fetch avoid a second
        # resolution, which is the window a rebinding attack needs.
        assert addrs == [(socket.AF_INET, "93.184.216.34")]
        assert parsed.hostname == "example.com"
