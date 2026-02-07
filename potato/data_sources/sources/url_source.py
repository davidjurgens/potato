"""
URL data source.

This module provides data loading from HTTP/HTTPS URLs with security
protections against SSRF attacks.
"""

import ipaddress
import json
import logging
import os
import socket
import tempfile
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlparse

from potato.data_sources.base import DataSource, SourceConfig

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_MAX_SIZE_MB = 100
DEFAULT_TIMEOUT_SECONDS = 30

# Private IP ranges to block (SSRF protection)
PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private range."""
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in PRIVATE_IP_RANGES:
            if ip in network:
                return True
        return False
    except ValueError:
        return False


def resolve_and_validate_url(url: str, block_private_ips: bool = True) -> str:
    """
    Validate a URL and resolve it, checking for SSRF vulnerabilities.

    Args:
        url: The URL to validate
        block_private_ips: Whether to block private/internal IPs

    Returns:
        The validated URL

    Raises:
        ValueError: If the URL is invalid or points to a blocked IP
    """
    parsed = urlparse(url)

    # Only allow http/https
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Only http/https allowed.")

    if not parsed.netloc:
        raise ValueError("Invalid URL: missing host")

    # Extract hostname (without port)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: missing hostname")

    if block_private_ips:
        # Resolve hostname to IP
        try:
            # Get all IP addresses for the hostname
            addr_info = socket.getaddrinfo(hostname, None)
            for info in addr_info:
                ip = info[4][0]
                if is_private_ip(ip):
                    raise ValueError(
                        f"URL host '{hostname}' resolves to private IP {ip}. "
                        f"Access to private networks is not allowed."
                    )
        except socket.gaierror as e:
            raise ValueError(f"Could not resolve hostname '{hostname}': {e}")

    return url


class URLSource(DataSource):
    """
    Data source for HTTP/HTTPS URLs.

    Supports fetching data from remote URLs with:
    - SSRF protection (blocks private IPs)
    - Custom headers for authentication
    - Size limits and timeouts
    - Content-type validation
    - Caching integration

    Configuration:
        type: url
        url: "https://example.com/data.jsonl"  # Required
        headers:                               # Optional custom headers
          Authorization: "Bearer ${API_TOKEN}"
        max_size_mb: 100                       # Optional size limit
        timeout_seconds: 30                    # Optional request timeout
        block_private_ips: true                # Optional SSRF protection

    Supported content types:
        - application/json, application/x-ndjson
        - text/csv, text/tab-separated-values
        - application/x-jsonlines
    """

    def __init__(self, config: SourceConfig):
        """Initialize the URL source."""
        super().__init__(config)

        self._url = config.config.get("url", "")
        self._headers = config.config.get("headers", {})
        self._max_size_bytes = config.config.get(
            "max_size_mb", DEFAULT_MAX_SIZE_MB
        ) * 1024 * 1024
        self._timeout = config.config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        self._block_private_ips = config.config.get("block_private_ips", True)
        self._allowed_domains = config.config.get("allowed_domains")

        # Cached data
        self._cached_data: Optional[List[Dict]] = None
        self._content_type: Optional[str] = None

    def get_source_id(self) -> str:
        """Get unique identifier."""
        return self._source_id

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = []

        if not self._url:
            errors.append("'url' is required for URL source")
            return errors

        try:
            parsed = urlparse(self._url)
            if parsed.scheme not in ('http', 'https'):
                errors.append(
                    f"Invalid URL scheme '{parsed.scheme}'. Only http/https allowed."
                )

            if not parsed.netloc:
                errors.append("Invalid URL: missing host")

            # Check domain allowlist if configured
            if self._allowed_domains:
                hostname = parsed.hostname
                if hostname and hostname not in self._allowed_domains:
                    errors.append(
                        f"Domain '{hostname}' is not in allowed domains list"
                    )

        except Exception as e:
            errors.append(f"Invalid URL: {e}")

        return errors

    def is_available(self) -> bool:
        """Check if the URL is accessible."""
        try:
            resolve_and_validate_url(self._url, self._block_private_ips)
            return True
        except ValueError as e:
            logger.warning(f"URL not available: {e}")
            return False
        except Exception as e:
            logger.warning(f"Error checking URL availability: {e}")
            return False

    def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch and parse data from the URL."""
        import urllib.request
        import urllib.error

        # Validate URL again before fetching
        resolve_and_validate_url(self._url, self._block_private_ips)

        # Build request with headers
        request = urllib.request.Request(self._url)
        for key, value in self._headers.items():
            request.add_header(key, value)

        # Add User-Agent if not specified
        if 'User-Agent' not in self._headers:
            request.add_header('User-Agent', 'Potato-Annotation-Tool/1.0')

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                # Check content length
                content_length = response.headers.get('Content-Length')
                if content_length:
                    size = int(content_length)
                    if size > self._max_size_bytes:
                        raise ValueError(
                            f"Response size {size} exceeds limit {self._max_size_bytes}"
                        )

                # Read with size limit
                data = b""
                chunk_size = 8192
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > self._max_size_bytes:
                        raise ValueError(
                            f"Response exceeded size limit of "
                            f"{self._max_size_bytes / (1024*1024):.1f}MB"
                        )

                self._content_type = response.headers.get('Content-Type', '')

                # Parse based on content type
                return self._parse_content(data, self._content_type)

        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"URL error: {e.reason}")

    def _parse_content(
        self,
        data: bytes,
        content_type: str
    ) -> List[Dict[str, Any]]:
        """Parse content based on content type or URL extension."""
        text = data.decode('utf-8')

        # Determine format from content type or URL
        url_path = urlparse(self._url).path.lower()

        if any(ct in content_type for ct in ['json', 'ndjson', 'jsonlines']):
            return self._parse_json(text)
        elif url_path.endswith('.json') or url_path.endswith('.jsonl'):
            return self._parse_json(text)
        elif 'csv' in content_type or url_path.endswith('.csv'):
            return self._parse_csv(text, ',')
        elif 'tab-separated' in content_type or url_path.endswith('.tsv'):
            return self._parse_csv(text, '\t')
        else:
            # Try JSON first, fall back to JSONL
            try:
                return self._parse_json(text)
            except json.JSONDecodeError:
                raise ValueError(
                    f"Could not parse content. "
                    f"Content-Type: {content_type}, URL: {self._url}"
                )

    def _parse_json(self, text: str) -> List[Dict[str, Any]]:
        """Parse JSON or JSONL content."""
        # Try as JSON array first
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            else:
                raise ValueError(f"Unexpected JSON type: {type(data)}")
        except json.JSONDecodeError:
            pass

        # Parse as JSONL
        items = []
        for line_no, line in enumerate(text.split('\n'), 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, list):
                    items.extend(item)
                else:
                    items.append(item)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON at line {line_no}: {e}")

        return items

    def _parse_csv(self, text: str, delimiter: str) -> List[Dict[str, Any]]:
        """Parse CSV/TSV content."""
        import csv
        from io import StringIO

        reader = csv.DictReader(StringIO(text), delimiter=delimiter)
        return [dict(row) for row in reader]

    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Read items from the URL."""
        # Fetch data if not cached
        if self._cached_data is None:
            self._cached_data = self._fetch_data()

        # Apply start/count
        items = self._cached_data[start:]
        if count is not None:
            items = items[:count]

        yield from items

    def get_total_count(self) -> Optional[int]:
        """Get total number of items."""
        if self._cached_data is None:
            try:
                self._cached_data = self._fetch_data()
            except Exception as e:
                logger.error(f"Error fetching data for count: {e}")
                return None

        return len(self._cached_data)

    def supports_partial_reading(self) -> bool:
        """URL source supports partial reading after fetch."""
        return True

    def refresh(self) -> bool:
        """Refresh by clearing cached data."""
        self._cached_data = None
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get source status."""
        status = super().get_status()
        status["url"] = self._url
        status["cached"] = self._cached_data is not None
        status["content_type"] = self._content_type
        return status
