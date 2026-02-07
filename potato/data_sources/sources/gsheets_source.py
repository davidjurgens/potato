"""
Google Sheets data source.

This module provides data loading from Google Sheets spreadsheets,
supporting service account authentication.
"""

import logging
from typing import Any, Dict, Iterator, List, Optional

from potato.data_sources.base import DataSource, SourceConfig

logger = logging.getLogger(__name__)


class GoogleSheetsSource(DataSource):
    """
    Data source for Google Sheets.

    Loads data from Google Sheets using the Sheets API with
    service account authentication.

    Configuration:
        type: google_sheets
        spreadsheet_id: "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        sheet_name: "Sheet1"      # Optional: sheet name (default: first sheet)
        range: "A:Z"              # Optional: range to read
        credentials_file: "credentials/service_account.json"

        # Header options
        header_row: 1             # Row containing headers (1-indexed)
        skip_rows: 0              # Rows to skip after header

    Note: Requires google-api-python-client:
          pip install google-api-python-client google-auth
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
        """Initialize the Google Sheets source."""
        super().__init__(config)

        self._spreadsheet_id = config.config.get("spreadsheet_id", "")
        self._sheet_name = config.config.get("sheet_name")
        self._range = config.config.get("range", "A:Z")
        self._credentials_file = config.config.get("credentials_file")

        self._header_row = config.config.get("header_row", 1)
        self._skip_rows = config.config.get("skip_rows", 0)

        self._service = None
        self._cached_data: Optional[List[Dict]] = None

    def get_source_id(self) -> str:
        """Get unique identifier."""
        return self._source_id

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = []

        if not self._spreadsheet_id:
            errors.append("'spreadsheet_id' is required for Google Sheets source")

        if not self._credentials_file:
            errors.append("'credentials_file' is required for Google Sheets source")

        return errors

    def is_available(self) -> bool:
        """Check if the source is available."""
        if not self._check_dependencies():
            logger.warning(
                "Google API dependencies not installed. "
                "Install with: pip install google-api-python-client google-auth"
            )
            return False

        import os
        if self._credentials_file and not os.path.exists(self._credentials_file):
            logger.warning(f"Credentials file not found: {self._credentials_file}")
            return False

        return True

    def _get_service(self):
        """Get or create the Sheets API service."""
        if self._service:
            return self._service

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            self._credentials_file,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )

        self._service = build('sheets', 'v4', credentials=credentials)
        return self._service

    def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch and parse data from Google Sheets."""
        service = self._get_service()

        # Construct the range
        if self._sheet_name:
            range_notation = f"'{self._sheet_name}'!{self._range}"
        else:
            range_notation = self._range

        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range=range_notation,
                valueRenderOption='UNFORMATTED_VALUE',
                dateTimeRenderOption='FORMATTED_STRING'
            ).execute()

            values = result.get('values', [])

            if not values:
                logger.warning("No data found in spreadsheet")
                return []

            # Extract headers
            header_index = self._header_row - 1  # Convert to 0-indexed
            if header_index >= len(values):
                raise ValueError(
                    f"Header row {self._header_row} is beyond data range"
                )

            headers = values[header_index]

            # Clean up headers
            headers = [str(h).strip() if h else f"column_{i}"
                      for i, h in enumerate(headers)]

            # Extract data rows
            data_start = header_index + 1 + self._skip_rows
            data_rows = values[data_start:]

            # Convert to list of dictionaries
            items = []
            for row_index, row in enumerate(data_rows):
                # Skip empty rows
                if not row or all(cell == '' or cell is None for cell in row):
                    continue

                # Pad row if shorter than headers
                while len(row) < len(headers):
                    row.append('')

                item = {headers[i]: row[i] for i in range(len(headers))}

                # Add row number as fallback ID if no 'id' column
                if 'id' not in item:
                    item['_row_number'] = data_start + row_index + 1

                items.append(item)

            logger.info(
                f"Loaded {len(items)} rows from spreadsheet "
                f"(sheet={self._sheet_name or 'first'}, "
                f"columns={len(headers)})"
            )

            return items

        except Exception as e:
            raise RuntimeError(f"Failed to fetch spreadsheet data: {e}")

    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Read items from Google Sheets."""
        if self._cached_data is None:
            self._cached_data = self._fetch_data()

        items = self._cached_data[start:]
        if count is not None:
            items = items[:count]

        yield from items

    def get_total_count(self) -> Optional[int]:
        """Get total number of rows."""
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
        status["spreadsheet_id"] = self._spreadsheet_id
        status["sheet_name"] = self._sheet_name
        status["range"] = self._range
        status["cached"] = self._cached_data is not None
        return status

    def close(self) -> None:
        """Close the source."""
        self._service = None
        self._cached_data = None
