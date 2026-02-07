"""
Local file data source.

This module provides data loading from local files, supporting
JSON, JSONL, CSV, and TSV formats with partial reading support.
"""

import csv
import json
import logging
import os
from typing import Any, Dict, Iterator, List, Optional

from potato.data_sources.base import DataSource, SourceConfig

logger = logging.getLogger(__name__)


class LocalFileSource(DataSource):
    """
    Data source for local files.

    Supports reading from JSON, JSONL, CSV, and TSV files with
    optional partial reading for large files.

    Configuration:
        type: file
        path: "data/annotations.jsonl"  # Required: path to file

    Supported formats:
        - .json: JSON array or object per line
        - .jsonl: JSON Lines (one JSON object per line)
        - .csv: Comma-separated values
        - .tsv: Tab-separated values
    """

    SUPPORTED_EXTENSIONS = ('.json', '.jsonl', '.csv', '.tsv')

    def __init__(self, config: SourceConfig):
        """
        Initialize the local file source.

        Args:
            config: Source configuration
        """
        super().__init__(config)

        self._path = config.config.get("path", "")
        self._resolved_path: Optional[str] = None
        self._total_count: Optional[int] = None
        self._file_positions: Dict[int, int] = {}  # line_number -> file_position

    def get_source_id(self) -> str:
        """Get unique identifier for this source."""
        return self._source_id

    def _resolve_path(self) -> str:
        """Resolve the file path."""
        if self._resolved_path:
            return self._resolved_path

        path = self._path

        # If path is relative, resolve against task_dir from config
        if not os.path.isabs(path):
            task_dir = self._raw_config.get("task_dir", ".")
            path = os.path.join(task_dir, path)

        self._resolved_path = os.path.abspath(path)
        return self._resolved_path

    def is_available(self) -> bool:
        """Check if the file exists and is readable."""
        try:
            path = self._resolve_path()
            if not os.path.exists(path):
                logger.warning(f"File does not exist: {path}")
                return False
            if not os.path.isfile(path):
                logger.warning(f"Path is not a file: {path}")
                return False
            if not os.access(path, os.R_OK):
                logger.warning(f"File is not readable: {path}")
                return False
            return True
        except Exception as e:
            logger.error(f"Error checking file availability: {e}")
            return False

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = []

        if not self._path:
            errors.append("'path' is required for file source")
            return errors

        # Check extension
        ext = os.path.splitext(self._path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            errors.append(
                f"Unsupported file extension '{ext}'. "
                f"Supported: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )

        return errors

    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Read items from the file.

        Args:
            start: Index of first item to read (0-based)
            count: Maximum number of items to read

        Yields:
            Item dictionaries
        """
        path = self._resolve_path()
        ext = os.path.splitext(path)[1].lower()

        if ext in ('.json', '.jsonl'):
            yield from self._read_json_items(path, start, count)
        elif ext == '.csv':
            yield from self._read_csv_items(path, start, count, delimiter=',')
        elif ext == '.tsv':
            yield from self._read_csv_items(path, start, count, delimiter='\t')
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def _read_json_items(
        self,
        path: str,
        start: int,
        count: Optional[int]
    ) -> Iterator[Dict[str, Any]]:
        """Read items from JSON/JSONL file."""
        ext = os.path.splitext(path)[1].lower()

        with open(path, 'r', encoding='utf-8') as f:
            if ext == '.json':
                # Try to parse as JSON array first
                content = f.read()
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        # JSON array
                        items = data
                    elif isinstance(data, dict):
                        # Single object
                        items = [data]
                    else:
                        raise ValueError(f"Unexpected JSON type: {type(data)}")

                    # Apply start/count
                    items = items[start:]
                    if count is not None:
                        items = items[:count]

                    yield from items
                    return

                except json.JSONDecodeError:
                    # Fall back to JSONL parsing
                    pass

            # Reset file position for JSONL parsing
            f.seek(0)

            items_yielded = 0
            current_line = 0

            for line_no, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue

                # Skip lines before start
                if current_line < start:
                    current_line += 1
                    continue

                # Check count limit
                if count is not None and items_yielded >= count:
                    break

                try:
                    item = json.loads(line)
                    if isinstance(item, list):
                        # Line contains array - expand
                        for sub_item in item:
                            if count is not None and items_yielded >= count:
                                break
                            yield sub_item
                            items_yielded += 1
                    else:
                        yield item
                        items_yielded += 1
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON at line {line_no + 1}: {e}")

                current_line += 1

    def _read_csv_items(
        self,
        path: str,
        start: int,
        count: Optional[int],
        delimiter: str
    ) -> Iterator[Dict[str, Any]]:
        """Read items from CSV/TSV file."""
        with open(path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f, delimiter=delimiter)

            items_yielded = 0
            current_row = 0

            for row in reader:
                # Skip rows before start
                if current_row < start:
                    current_row += 1
                    continue

                # Check count limit
                if count is not None and items_yielded >= count:
                    break

                yield dict(row)
                items_yielded += 1
                current_row += 1

    def get_total_count(self) -> Optional[int]:
        """Get total number of items in the file."""
        if self._total_count is not None:
            return self._total_count

        if not self.is_available():
            return None

        try:
            path = self._resolve_path()
            ext = os.path.splitext(path)[1].lower()

            count = 0
            if ext in ('.json', '.jsonl'):
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    try:
                        data = json.loads(content)
                        if isinstance(data, list):
                            count = len(data)
                        else:
                            count = 1
                    except json.JSONDecodeError:
                        # JSONL - count non-empty lines
                        for line in content.split('\n'):
                            if line.strip():
                                count += 1

            elif ext in ('.csv', '.tsv'):
                delimiter = ',' if ext == '.csv' else '\t'
                with open(path, 'r', encoding='utf-8', newline='') as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    next(reader, None)  # Skip header
                    count = sum(1 for _ in reader)

            self._total_count = count
            return count

        except Exception as e:
            logger.error(f"Error counting items: {e}")
            return None

    def supports_partial_reading(self) -> bool:
        """Local files support partial reading."""
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get source status."""
        status = super().get_status()
        status["path"] = self._path
        status["resolved_path"] = self._resolve_path() if self.is_available() else None
        return status
