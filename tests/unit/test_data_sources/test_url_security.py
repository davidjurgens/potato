"""Tests for URL source security (SSRF protection)."""

import pytest
from potato.data_sources.sources.url_source import (
    is_private_ip,
    resolve_and_validate_url,
)


class TestIsPrivateIP:
    """Tests for private IP detection."""

    def test_localhost_ipv4(self):
        """Test that localhost is detected as private."""
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.255.255.255") is True

    def test_localhost_ipv6(self):
        """Test that IPv6 localhost is detected as private."""
        assert is_private_ip("::1") is True

    def test_private_10_range(self):
        """Test 10.0.0.0/8 private range."""
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    def test_private_172_range(self):
        """Test 172.16.0.0/12 private range."""
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True

    def test_private_192_range(self):
        """Test 192.168.0.0/16 private range."""
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True

    def test_link_local(self):
        """Test link-local addresses."""
        assert is_private_ip("169.254.1.1") is True

    def test_public_ip(self):
        """Test that public IPs are not private."""
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False
        assert is_private_ip("142.250.185.238") is False  # google.com

    def test_invalid_ip_returns_false(self):
        """Test that invalid IPs return False."""
        assert is_private_ip("not.an.ip") is False
        assert is_private_ip("") is False


class TestResolveAndValidateUrl:
    """Tests for URL validation and SSRF protection."""

    def test_valid_https_url(self):
        """Test that valid HTTPS URL passes."""
        # Use a well-known public URL
        url = "https://example.com/data.json"
        result = resolve_and_validate_url(url, block_private_ips=True)
        assert result == url

    def test_valid_http_url(self):
        """Test that valid HTTP URL passes."""
        url = "http://example.com/data.json"
        result = resolve_and_validate_url(url, block_private_ips=True)
        assert result == url

    def test_invalid_scheme_ftp(self):
        """Test that FTP scheme is rejected."""
        with pytest.raises(ValueError) as exc_info:
            resolve_and_validate_url("ftp://example.com/file")
        assert "scheme" in str(exc_info.value).lower()

    def test_invalid_scheme_file(self):
        """Test that file:// scheme is rejected."""
        with pytest.raises(ValueError) as exc_info:
            resolve_and_validate_url("file:///etc/passwd")
        assert "scheme" in str(exc_info.value).lower()

    def test_missing_host(self):
        """Test that missing host is rejected."""
        with pytest.raises(ValueError) as exc_info:
            resolve_and_validate_url("https:///path")
        assert "host" in str(exc_info.value).lower()

    def test_localhost_blocked(self):
        """Test that localhost is blocked when block_private_ips=True."""
        with pytest.raises(ValueError) as exc_info:
            resolve_and_validate_url("http://localhost/api", block_private_ips=True)
        assert "private" in str(exc_info.value).lower()

    def test_127_0_0_1_blocked(self):
        """Test that 127.0.0.1 is blocked."""
        with pytest.raises(ValueError) as exc_info:
            resolve_and_validate_url("http://127.0.0.1/api", block_private_ips=True)
        assert "private" in str(exc_info.value).lower()

    def test_private_ip_allowed_when_disabled(self):
        """Test that private IPs work when blocking is disabled."""
        # localhost should resolve without error when blocking is disabled
        url = "http://localhost/api"
        result = resolve_and_validate_url(url, block_private_ips=False)
        assert result == url

    def test_unresolvable_host(self):
        """Test that unresolvable host raises error."""
        with pytest.raises(ValueError) as exc_info:
            resolve_and_validate_url(
                "http://this-domain-definitely-does-not-exist-12345.com/api",
                block_private_ips=True
            )
        assert "resolve" in str(exc_info.value).lower()


class TestUrlSourceValidation:
    """Tests for URLSource configuration validation."""

    def test_url_source_requires_url(self):
        """Test that URLSource requires url field."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.url_source import URLSource

        config = SourceConfig.from_dict({
            "type": "url",
            "url": "",  # Empty URL
        })
        source = URLSource(config)
        errors = source.validate_config()

        assert len(errors) > 0
        assert any("url" in e.lower() for e in errors)

    def test_url_source_valid_config(self):
        """Test that valid URLSource config passes validation."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.url_source import URLSource

        config = SourceConfig.from_dict({
            "type": "url",
            "url": "https://example.com/data.json",
        })
        source = URLSource(config)
        errors = source.validate_config()

        assert len(errors) == 0

    def test_url_source_with_headers(self):
        """Test URLSource with custom headers."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.url_source import URLSource

        config = SourceConfig.from_dict({
            "type": "url",
            "url": "https://api.example.com/data",
            "headers": {
                "Authorization": "Bearer token123",
                "X-Custom-Header": "value",
            }
        })
        source = URLSource(config)

        assert source._headers["Authorization"] == "Bearer token123"
        assert source._headers["X-Custom-Header"] == "value"
