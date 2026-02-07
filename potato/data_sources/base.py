"""
Base classes and types for data sources.

This module defines the abstract base class for all data sources and
common types used throughout the data sources subsystem.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional
import logging

logger = logging.getLogger(__name__)


class SourceType(Enum):
    """Enumeration of supported data source types."""
    FILE = "file"
    URL = "url"
    GOOGLE_DRIVE = "google_drive"
    DROPBOX = "dropbox"
    S3 = "s3"
    HUGGINGFACE = "huggingface"
    GOOGLE_SHEETS = "google_sheets"
    DATABASE = "database"


@dataclass
class SourceConfig:
    """
    Configuration for a data source.

    This dataclass holds the parsed configuration for a single data source,
    including type-specific settings and common options.

    Attributes:
        source_type: The type of data source
        source_id: Unique identifier for this source (auto-generated if not provided)
        config: The raw configuration dictionary for this source
        enabled: Whether this source is enabled
    """
    source_type: SourceType
    source_id: str
    config: Dict[str, Any]
    enabled: bool = True

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any], index: int = 0) -> "SourceConfig":
        """
        Create a SourceConfig from a configuration dictionary.

        Args:
            config_dict: Dictionary containing source configuration
            index: Index in the sources list (used for auto-generated ID)

        Returns:
            SourceConfig instance

        Raises:
            ValueError: If the source type is invalid or required fields are missing
        """
        type_str = config_dict.get("type")
        if not type_str:
            raise ValueError("Data source configuration must include 'type' field")

        try:
            source_type = SourceType(type_str)
        except ValueError:
            valid_types = [t.value for t in SourceType]
            raise ValueError(
                f"Invalid data source type '{type_str}'. "
                f"Valid types are: {', '.join(valid_types)}"
            )

        # Generate source_id if not provided
        source_id = config_dict.get("id") or config_dict.get("source_id")
        if not source_id:
            # Generate ID based on type and index or key identifying info
            if source_type == SourceType.FILE:
                path = config_dict.get("path", "")
                source_id = f"file_{index}_{path.replace('/', '_').replace('.', '_')}"
            elif source_type == SourceType.URL:
                url = config_dict.get("url", "")
                # Use last part of URL path as identifier
                source_id = f"url_{index}_{url.split('/')[-1][:30]}"
            else:
                source_id = f"{source_type.value}_{index}"

        enabled = config_dict.get("enabled", True)

        return cls(
            source_type=source_type,
            source_id=source_id,
            config=config_dict,
            enabled=enabled
        )


class DataSource(ABC):
    """
    Abstract base class for all data sources.

    Each data source implementation must provide methods for:
    - Identifying the source
    - Checking availability
    - Reading items (with optional partial reading support)
    - Reporting total item count

    Thread Safety:
        Implementations should be thread-safe for concurrent read operations.
        Write operations (if any) should be protected by appropriate locking.
    """

    def __init__(self, config: SourceConfig):
        """
        Initialize the data source.

        Args:
            config: Source configuration
        """
        self._config = config
        self._source_id = config.source_id
        self._raw_config = config.config

    @property
    def source_id(self) -> str:
        """Get the unique identifier for this source."""
        return self._source_id

    @property
    def source_type(self) -> SourceType:
        """Get the type of this source."""
        return self._config.source_type

    @property
    def config(self) -> Dict[str, Any]:
        """Get the raw configuration dictionary."""
        return self._raw_config

    @abstractmethod
    def get_source_id(self) -> str:
        """
        Get the unique identifier for this data source.

        Returns:
            String identifier unique within the DataSourceManager
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the data source is available and accessible.

        This method should verify that:
        - Required dependencies are installed
        - Credentials are valid (if applicable)
        - The source location exists and is readable

        Returns:
            True if the source is ready to read from
        """
        pass

    @abstractmethod
    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Read items from the data source.

        This method yields dictionaries representing annotation items.
        For sources that support partial reading, the start and count
        parameters allow fetching specific ranges of items.

        Args:
            start: Index of the first item to read (0-based)
            count: Maximum number of items to read (None = all remaining)

        Yields:
            Dictionary containing item data with at least id_key field

        Raises:
            RuntimeError: If the source is not available
            IOError: If reading fails
        """
        pass

    @abstractmethod
    def get_total_count(self) -> Optional[int]:
        """
        Get the total number of items in the source.

        Returns:
            Total item count, or None if unknown (e.g., streaming source)
        """
        pass

    @abstractmethod
    def supports_partial_reading(self) -> bool:
        """
        Check if this source supports reading partial ranges.

        Partial reading allows loading data in chunks, which is useful
        for large datasets or incremental annotation workflows.

        Returns:
            True if read_items() supports start/count parameters
        """
        pass

    def validate_config(self) -> List[str]:
        """
        Validate the source configuration.

        Override this method to add source-specific validation.

        Returns:
            List of validation error messages (empty if valid)
        """
        return []

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of this data source.

        Returns:
            Dictionary containing status information:
            - source_id: The source identifier
            - source_type: The source type
            - available: Whether the source is available
            - total_count: Total item count (or None)
            - supports_partial: Whether partial reading is supported
        """
        return {
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "available": self.is_available(),
            "total_count": self.get_total_count(),
            "supports_partial": self.supports_partial_reading(),
        }

    def refresh(self) -> bool:
        """
        Refresh the data source (re-fetch from remote, re-validate, etc.).

        Override this method for sources that cache data or need
        periodic refresh. The default implementation does nothing.

        Returns:
            True if refresh was successful
        """
        return True

    def close(self) -> None:
        """
        Close the data source and release any resources.

        Override this method for sources that hold resources like
        database connections or file handles.
        """
        pass

    def __enter__(self) -> "DataSource":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source_id={self.source_id!r})"
