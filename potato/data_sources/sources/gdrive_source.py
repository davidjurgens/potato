"""
Google Drive data source.

This module provides data loading from Google Drive files,
supporting both public share links and authenticated access
via service account credentials.
"""

import io
import json
import logging
import re
from typing import Any, Dict, Iterator, List, Optional

from potato.data_sources.base import DataSource, SourceConfig

logger = logging.getLogger(__name__)

# Patterns for extracting file ID from various Google Drive URL formats
GDRIVE_URL_PATTERNS = [
    # https://drive.google.com/file/d/FILE_ID/view
    re.compile(r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)'),
    # https://drive.google.com/open?id=FILE_ID
    re.compile(r'drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)'),
    # https://docs.google.com/document/d/FILE_ID/edit
    re.compile(r'docs\.google\.com/\w+/d/([a-zA-Z0-9_-]+)'),
    # https://drive.google.com/uc?id=FILE_ID
    re.compile(r'drive\.google\.com/uc\?.*id=([a-zA-Z0-9_-]+)'),
]


def extract_file_id(url_or_id: str) -> str:
    """
    Extract Google Drive file ID from a URL or return the ID directly.

    Args:
        url_or_id: Either a Google Drive URL or a file ID

    Returns:
        The file ID

    Raises:
        ValueError: If the URL format is not recognized
    """
    # Check if it's already a file ID (no slashes or dots)
    if not ('/' in url_or_id or '.' in url_or_id):
        return url_or_id

    # Try each URL pattern
    for pattern in GDRIVE_URL_PATTERNS:
        match = pattern.search(url_or_id)
        if match:
            return match.group(1)

    raise ValueError(
        f"Could not extract Google Drive file ID from: {url_or_id}. "
        f"Please provide a valid Google Drive URL or file ID."
    )


class GoogleDriveSource(DataSource):
    """
    Data source for Google Drive files.

    Supports both public share links (no authentication required)
    and private files with service account credentials.

    Configuration for public files:
        type: google_drive
        url: "https://drive.google.com/file/d/xxx/view?usp=sharing"

    Configuration for private files:
        type: google_drive
        file_id: "xxx"  # Or use url
        credentials_file: "credentials/gdrive_service_account.json"

    Supported formats: JSON, JSONL, CSV, TSV
    """

    # Check for optional dependencies
    _HAS_GOOGLE_API = None

    @classmethod
    def _check_dependencies(cls) -> bool:
        """Check if Google API dependencies are available."""
        if cls._HAS_GOOGLE_API is None:
            try:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build
                cls._HAS_GOOGLE_API = True
            except ImportError:
                cls._HAS_GOOGLE_API = False
        return cls._HAS_GOOGLE_API

    def __init__(self, config: SourceConfig):
        """Initialize the Google Drive source."""
        super().__init__(config)

        self._url = config.config.get("url", "")
        self._file_id = config.config.get("file_id", "")
        self._credentials_file = config.config.get("credentials_file")

        # Resolve file ID from URL if provided
        if self._url and not self._file_id:
            self._file_id = extract_file_id(self._url)

        self._cached_data: Optional[List[Dict]] = None
        self._service = None

    def get_source_id(self) -> str:
        """Get unique identifier."""
        return self._source_id

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = []

        if not self._url and not self._file_id:
            errors.append("Either 'url' or 'file_id' is required for Google Drive source")
            return errors

        # Try to extract file ID
        try:
            if self._url and not self._file_id:
                extract_file_id(self._url)
        except ValueError as e:
            errors.append(str(e))

        return errors

    def is_available(self) -> bool:
        """Check if the source is available."""
        # For authenticated access, check dependencies and credentials
        if self._credentials_file:
            if not self._check_dependencies():
                logger.warning(
                    "Google API dependencies not installed. "
                    "Install with: pip install google-api-python-client google-auth"
                )
                return False

            import os
            if not os.path.exists(self._credentials_file):
                logger.warning(
                    f"Credentials file not found: {self._credentials_file}"
                )
                return False

        return True

    def _get_service(self):
        """Get or create the Google Drive API service."""
        if self._service:
            return self._service

        if not self._credentials_file:
            return None

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            self._credentials_file,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )

        self._service = build('drive', 'v3', credentials=credentials)
        return self._service

    def _fetch_public_file(self, file_id: str) -> bytes:
        """Fetch a public file using direct download URL."""
        import urllib.request
        import urllib.error

        # Construct direct download URL
        # This works for publicly shared files
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        request = urllib.request.Request(download_url)
        request.add_header('User-Agent', 'Potato-Annotation-Tool/1.0')

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read()

                # Check for virus scan warning (large files)
                if b'Google Drive - Virus scan warning' in content:
                    # Extract confirmation token and retry
                    import re
                    confirm_match = re.search(
                        rb'confirm=([0-9A-Za-z_-]+)',
                        content
                    )
                    if confirm_match:
                        confirm_token = confirm_match.group(1).decode()
                        download_url = (
                            f"https://drive.google.com/uc?export=download"
                            f"&confirm={confirm_token}&id={file_id}"
                        )
                        request = urllib.request.Request(download_url)
                        request.add_header('User-Agent', 'Potato-Annotation-Tool/1.0')
                        with urllib.request.urlopen(request, timeout=60) as response2:
                            content = response2.read()

                return content

        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(
                    f"File not found. Make sure the file is publicly shared."
                )
            raise RuntimeError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"URL error: {e.reason}")

    def _fetch_authenticated_file(self, file_id: str) -> bytes:
        """Fetch a file using authenticated API access."""
        service = self._get_service()
        if not service:
            raise RuntimeError(
                "No credentials configured for authenticated access"
            )

        from googleapiclient.http import MediaIoBaseDownload

        # Get file metadata
        file_metadata = service.files().get(fileId=file_id).execute()
        logger.debug(f"Fetching file: {file_metadata.get('name')}")

        # Download file content
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.debug(f"Download progress: {int(status.progress() * 100)}%")

        buffer.seek(0)
        return buffer.read()

    def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch and parse data from Google Drive."""
        file_id = self._file_id

        # Fetch the file
        if self._credentials_file:
            content = self._fetch_authenticated_file(file_id)
        else:
            content = self._fetch_public_file(file_id)

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
        """Read items from Google Drive file."""
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
        status["file_id"] = self._file_id
        status["authenticated"] = self._credentials_file is not None
        status["cached"] = self._cached_data is not None
        return status

    def close(self) -> None:
        """Close the source."""
        self._service = None
        self._cached_data = None
