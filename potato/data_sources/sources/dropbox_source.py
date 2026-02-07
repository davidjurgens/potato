"""
Dropbox data source.

This module provides data loading from Dropbox files,
supporting both public share links and authenticated access.
"""

import json
import logging
import re
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlparse, parse_qs

from potato.data_sources.base import DataSource, SourceConfig

logger = logging.getLogger(__name__)


def convert_share_link(url: str) -> str:
    """
    Convert a Dropbox share link to a direct download URL.

    Args:
        url: Dropbox share link

    Returns:
        Direct download URL

    Examples:
        https://www.dropbox.com/s/xxx/file.json?dl=0
        -> https://www.dropbox.com/s/xxx/file.json?dl=1
    """
    parsed = urlparse(url)

    # Check if it's a Dropbox URL
    if 'dropbox.com' not in parsed.netloc:
        raise ValueError(f"Not a Dropbox URL: {url}")

    # Convert dl=0 to dl=1 for direct download
    if 'dl=0' in url:
        return url.replace('dl=0', 'dl=1')
    elif 'dl=1' in url:
        return url
    else:
        # Add dl=1 parameter
        separator = '&' if '?' in url else '?'
        return f"{url}{separator}dl=1"


class DropboxSource(DataSource):
    """
    Data source for Dropbox files.

    Supports both public share links (no authentication required)
    and private files with access token authentication.

    Configuration for public files:
        type: dropbox
        url: "https://www.dropbox.com/s/xxx/file.jsonl?dl=0"

    Configuration for private files:
        type: dropbox
        path: "/path/to/file.jsonl"  # Path in Dropbox
        access_token: "${DROPBOX_TOKEN}"

    Supported formats: JSON, JSONL, CSV, TSV
    """

    # Check for optional dependencies
    _HAS_DROPBOX = None

    @classmethod
    def _check_dependencies(cls) -> bool:
        """Check if Dropbox SDK is available."""
        if cls._HAS_DROPBOX is None:
            try:
                import dropbox
                cls._HAS_DROPBOX = True
            except ImportError:
                cls._HAS_DROPBOX = False
        return cls._HAS_DROPBOX

    def __init__(self, config: SourceConfig):
        """Initialize the Dropbox source."""
        super().__init__(config)

        self._url = config.config.get("url", "")
        self._path = config.config.get("path", "")
        self._access_token = config.config.get("access_token")

        self._cached_data: Optional[List[Dict]] = None
        self._client = None

    def get_source_id(self) -> str:
        """Get unique identifier."""
        return self._source_id

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = []

        if not self._url and not self._path:
            errors.append(
                "Either 'url' or 'path' is required for Dropbox source"
            )
            return errors

        # If path is provided, token is required
        if self._path and not self._access_token:
            errors.append(
                "'access_token' is required when using 'path' for private files"
            )

        # Validate URL format if provided
        if self._url:
            try:
                convert_share_link(self._url)
            except ValueError as e:
                errors.append(str(e))

        return errors

    def is_available(self) -> bool:
        """Check if the source is available."""
        # For authenticated access, check dependencies
        if self._access_token:
            if not self._check_dependencies():
                logger.warning(
                    "Dropbox SDK not installed. "
                    "Install with: pip install dropbox"
                )
                return False

        return True

    def _get_client(self):
        """Get or create the Dropbox client."""
        if self._client:
            return self._client

        if not self._access_token:
            return None

        import dropbox
        self._client = dropbox.Dropbox(self._access_token)
        return self._client

    def _fetch_public_file(self, url: str) -> bytes:
        """Fetch a public file using direct download URL."""
        import urllib.request
        import urllib.error

        download_url = convert_share_link(url)

        request = urllib.request.Request(download_url)
        request.add_header('User-Agent', 'Potato-Annotation-Tool/1.0')

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError("File not found or link has expired")
            raise RuntimeError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"URL error: {e.reason}")

    def _fetch_authenticated_file(self, path: str) -> bytes:
        """Fetch a file using authenticated API access."""
        client = self._get_client()
        if not client:
            raise RuntimeError("No access token configured")

        import dropbox

        try:
            # Ensure path starts with /
            if not path.startswith('/'):
                path = '/' + path

            metadata, response = client.files_download(path)
            logger.debug(f"Downloaded: {metadata.name} ({metadata.size} bytes)")
            return response.content

        except dropbox.exceptions.ApiError as e:
            if e.error.is_path():
                raise ValueError(f"File not found: {path}")
            raise RuntimeError(f"Dropbox API error: {e}")

    def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch and parse data from Dropbox."""
        # Fetch the file
        if self._url:
            content = self._fetch_public_file(self._url)
        else:
            content = self._fetch_authenticated_file(self._path)

        # Decode and parse
        text = content.decode('utf-8')
        return self._parse_content(text)

    def _parse_content(self, text: str) -> List[Dict[str, Any]]:
        """Parse file content."""
        # Try JSON array first
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

        # Try JSONL
        items = []
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, list):
                    items.extend(item)
                else:
                    items.append(item)
            except json.JSONDecodeError:
                pass

        if items:
            return items

        # Try CSV
        import csv
        from io import StringIO

        try:
            reader = csv.DictReader(StringIO(text))
            items = [dict(row) for row in reader]
            if items:
                return items
        except Exception:
            pass

        raise ValueError("Could not parse file content as JSON, JSONL, or CSV")

    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Read items from Dropbox file."""
        if self._cached_data is None:
            self._cached_data = self._fetch_data()

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
                logger.error(f"Error fetching data: {e}")
                return None

        return len(self._cached_data)

    def supports_partial_reading(self) -> bool:
        """Partial reading is supported after initial fetch."""
        return True

    def refresh(self) -> bool:
        """Refresh by clearing cached data."""
        self._cached_data = None
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get source status."""
        status = super().get_status()
        status["url"] = self._url
        status["path"] = self._path
        status["authenticated"] = self._access_token is not None
        status["cached"] = self._cached_data is not None
        return status

    def close(self) -> None:
        """Close the source."""
        self._client = None
        self._cached_data = None
