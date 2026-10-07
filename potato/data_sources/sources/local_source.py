"""
Local file data source.

Data loading from local files, supporting
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
        """Resolve the file path, validating relative paths stay within the task directory."""
        if self._resolved_path:
            return self._resolved_path

        path = self._path
        task_dir = os.path.abspath(self._raw_config.get("task_dir", "."))

        # If path is relative, resolve against task_dir and validate containment
        if not os.path.isabs(path):
            resolved = os.path.abspath(os.path.join(task_dir, path))

            # Ensure the resolved path is within the task directory
            if not resolved.startswith(task_dir + os.sep) and resolved != task_dir:
                raise ValueError(
                    f"Path '{self._path}' resolves to '{resolved}' which is "
                    f"outside the task directory '{task_dir}'. "
                    f"Path traversal is not allowed."
                )
        else:
            # Absolute paths are used as-is (admin-provided via config)
            resolved = os.path.abspath(path)

        self._resolved_path = resolved
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

    def _read_all(self) -> List[Any]:
        """Every record in the file, parsed the way ``data_files`` parses it."""
        from potato.data_sources.parsing import format_for, parse_records, read_text

        path = self._resolve_path()
        fmt = format_for(path)
        if fmt is None:
            raise ValueError(f"Unsupported file format: {os.path.splitext(path)[1].lower()}")
        return parse_records(read_text(path), fmt, path)

    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Read items from the file.

        ``start`` and ``count`` index records, not lines: a JSON Lines line
        holding an array contributes one record per element, and a quoted CSV
        cell may span lines.

        A malformed line raises ``SourceDataError`` naming it, as ``data_files``
        does. It used to be logged and skipped, so a file with one bad line
        loaded short with nothing but a warning to show for it.

        Args:
            start: Index of first item to read (0-based)
            count: Maximum number of items to read

        Yields:
            Item dictionaries
        """
        records = self._read_all()
        self._total_count = len(records)
        end = None if count is None else start + count
        yield from records[start:end]

    def get_total_count(self) -> Optional[int]:
        """Get total number of items in the file."""
        if self._total_count is not None:
            return self._total_count

        if not self.is_available():
            return None

        try:
            self._total_count = len(self._read_all())
            return self._total_count
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
