"""
Base Trace Converter

Defines the abstract base class for trace format converters and
the canonical Potato trace data model.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class CanonicalTrace:
    """
    Potato's canonical agent trace format.

    This is the normalized representation that all converters produce.
    It maps directly to Potato's data model for annotation.
    """
    id: str
    task_description: str
    conversation: List[Dict[str, str]]
    agent_name: str = ""
    metadata_table: List[Dict[str, str]] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    extra_fields: Dict[str, Any] = field(default_factory=dict)

    # Core fields that extra_fields must not overwrite
    _CORE_FIELDS = frozenset({
        "id", "task_description", "conversation",
        "agent_name", "metadata_table", "screenshots",
    })

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary suitable for JSONL output."""
        result = {
            "id": self.id,
            "task_description": self.task_description,
            "conversation": self.conversation,
        }
        if self.agent_name:
            result["agent_name"] = self.agent_name
        if self.metadata_table:
            result["metadata_table"] = self.metadata_table
        if self.screenshots:
            result["screenshots"] = self.screenshots
        # Add extra fields, but never overwrite core fields
        for key, value in self.extra_fields.items():
            if key not in self._CORE_FIELDS:
                result[key] = value
        return result


class BaseTraceConverter(ABC):
    """
    Abstract base class for trace format converters.

    Subclasses must implement:
        - convert(): Parse input data and produce canonical traces
        - detect(): Attempt to auto-detect this format from input data
    """

    format_name: str = ""
    description: str = ""
    file_extensions: List[str] = []

    @abstractmethod
    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        """
        Convert input data to canonical trace format.

        Args:
            data: Parsed input data (usually a list of dicts or a dict)
            options: Format-specific conversion options

        Returns:
            List of CanonicalTrace objects
        """
        ...

    @abstractmethod
    def detect(self, data: Any) -> bool:
        """
        Check whether the input data matches this format.

        Args:
            data: Parsed input data

        Returns:
            True if this converter can handle the data
        """
        ...

    def get_format_info(self) -> Dict[str, str]:
        """Return metadata about this format."""
        return {
            "format_name": self.format_name,
            "description": self.description,
            "file_extensions": self.file_extensions,
        }
