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


def _issue_cert(directory, hostname):
    """Write a CA and a server certificate for ``hostname`` signed by it."""
    import datetime
    import os
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    window = (now - datetime.timedelta(days=1), now + datetime.timedelta(days=1))

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "potato test CA")])
    ca = (x509.CertificateBuilder()
          .subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(window[0]).not_valid_after(window[1])
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .sign(ca_key, hashes.SHA256()))

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
            .issuer_name(ca_name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(window[0]).not_valid_after(window[1])
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .sign(ca_key, hashes.SHA256()))

    paths = {name: os.path.join(directory, name) for name in ("ca.pem", "cert.pem", "key.pem")}
    with open(paths["ca.pem"], "wb") as f:
        f.write(ca.public_bytes(serialization.Encoding.PEM))
    with open(paths["cert.pem"], "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(paths["key.pem"], "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    return paths


class TestPinnedHttps:
    """A pinned https fetch must send the hostname as SNI and verify it.

    The pinned URL holds an IP, and the fetch used to send no SNI and run with
    verification off: every CDN-hosted media URL failed the handshake, and a
    server presenting any certificate at all was accepted.
    """

    def _serve(self, directory, cert_host, sni_required=True):
        import http.server
        import ssl
        import threading

        paths = _issue_cert(directory, cert_host)
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"ID3audio"
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        def require_sni(sock, server_name, context):
            seen.append(server_name)
            if server_name is None and sni_required:
                return ssl.ALERT_DESCRIPTION_HANDSHAKE_FAILURE
            return None

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(paths["cert.pem"], paths["key.pem"])
        context.sni_callback = require_sni
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, paths["ca.pem"], seen

    @pytest.fixture
    def directory(self):
        from tests.helpers.test_utils import create_test_directory
        return create_test_directory("url_guard_pinned_https")

    def _fetch(self, monkeypatch, ca, port):
        from potato.server_utils import url_guard
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", ca)
        # The server is on loopback, which the guard blocks; stand in for a
        # public resolution that pins to it.
        monkeypatch.setattr(url_guard, "resolve_public_addresses",
                            lambda host, p: [(socket.AF_INET, "127.0.0.1")])
        return url_guard.fetch("https://media.test:%d/clip.mp3" % port, timeout=10)

    def test_sends_the_hostname_as_sni(self, directory, monkeypatch):
        server, ca, seen = self._serve(directory, "media.test")
        try:
            response = self._fetch(monkeypatch, ca, server.server_address[1])
            assert response.status_code == 200
            assert response.content == b"ID3audio"
            assert seen == ["media.test"]
        finally:
            server.shutdown()

    def test_refuses_a_certificate_for_another_name(self, directory, monkeypatch):
        import requests
        # SNI is optional here so the handshake gets as far as the
        # certificate; refusing it is then verification's job alone.
        server, ca, _ = self._serve(directory, "other.test", sni_required=False)
        try:
            with pytest.raises(requests.exceptions.SSLError):
                self._fetch(monkeypatch, ca, server.server_address[1])
        finally:
            server.shutdown()
