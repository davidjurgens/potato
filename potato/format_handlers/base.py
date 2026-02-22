"""
Base Format Handler

Provides the abstract base class for format handlers and the FormatOutput
dataclass that represents extracted content from documents.

Usage:
    from potato.format_handlers.base import BaseFormatHandler, FormatOutput

    class MyFormatHandler(BaseFormatHandler):
        format_name = "my_format"
        supported_extensions = [".myf"]

        def extract(self, file_path, options=None):
            # Parse file and return FormatOutput
            return FormatOutput(
                text="extracted text",
                rendered_html="<div>rendered content</div>",
                coordinate_map={...},
                metadata={...}
            )
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from pathlib import Path


@dataclass
class FormatOutput:
    """
    Represents the extracted content from a document.

    Attributes:
        text: Plain text extracted from the document (for annotation)
        rendered_html: HTML representation for display in the annotation UI
        coordinate_map: Mapping from character offsets to format-specific coordinates
        metadata: Additional document metadata (pages, structure, etc.)
        format_name: Name of the format that produced this output
        source_path: Path to the original source file
    """
    text: str
    rendered_html: str
    coordinate_map: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    format_name: str = ""
    source_path: str = ""

    def get_format_coords(self, start: int, end: int) -> Optional[Dict[str, Any]]:
        """
        Get format-specific coordinates for a character range.

        Args:
            start: Start character offset (inclusive)
            end: End character offset (exclusive)

        Returns:
            Dictionary with format-specific coordinates, or None if not available
        """
        if not self.coordinate_map:
            return None

        # Look up coordinates using the mapping
        # Implementation varies by format type
        if "get_coords_for_range" in self.coordinate_map:
            return self.coordinate_map["get_coords_for_range"](start, end)

        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "text": self.text,
            "rendered_html": self.rendered_html,
            "metadata": self.metadata,
            "format_name": self.format_name,
            "source_path": self.source_path,
        }


class BaseFormatHandler(ABC):
    """
    Abstract base class for document format handlers.

    Subclasses must implement the `extract` method and define class
    attributes for format identification.

    Class Attributes:
        format_name: Unique identifier for this format (e.g., "pdf", "docx")
        supported_extensions: List of file extensions this handler supports
        description: Human-readable description of this format handler
        requires_dependencies: List of optional dependencies needed
    """

    format_name: str = ""
    supported_extensions: List[str] = []
    description: str = ""
    requires_dependencies: List[str] = []

    @abstractmethod
    def extract(self, file_path: str, options: Optional[Dict[str, Any]] = None) -> FormatOutput:
        """
        Extract annotatable content from a document.

        Args:
            file_path: Path to the document file
            options: Optional configuration for extraction:
                - extraction_mode: How to extract text (e.g., 'text', 'ocr', 'hybrid')
                - preserve_layout: Whether to preserve document layout
                - max_pages: Maximum pages to process (for paged documents)
                - encoding: Text encoding to use

        Returns:
            FormatOutput with extracted text, rendered HTML, and coordinate mappings

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file format is not supported
            ImportError: If required dependencies are not installed
        """
        pass

    def can_handle(self, file_path: str) -> bool:
        """
        Check if this handler can process the given file.

        Args:
            file_path: Path to the file

        Returns:
            True if this handler supports the file's extension
        """
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions

    def check_dependencies(self) -> List[str]:
        """
        Check if required dependencies are installed.

        Returns:
            List of missing dependency names (empty if all installed)
        """
        missing = []
        for dep in self.requires_dependencies:
            try:
                __import__(dep.replace("-", "_"))
            except ImportError:
                missing.append(dep)
        return missing

    def validate_file(self, file_path: str) -> List[str]:
        """
        Validate that a file can be processed.

        Args:
            file_path: Path to the file

        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        path = Path(file_path)

        if not path.exists():
            errors.append(f"File not found: {file_path}")
            return errors

        if not path.is_file():
            errors.append(f"Not a file: {file_path}")
            return errors

        if not self.can_handle(file_path):
            errors.append(
                f"Unsupported extension '{path.suffix}'. "
                f"Supported: {', '.join(self.supported_extensions)}"
            )

        missing_deps = self.check_dependencies()
        if missing_deps:
            errors.append(
                f"Missing dependencies for {self.format_name}: "
                f"{', '.join(missing_deps)}. "
                f"Install with: pip install {' '.join(missing_deps)}"
            )

        return errors

    def get_default_options(self) -> Dict[str, Any]:
        """
        Get default extraction options for this handler.

        Override in subclasses to provide format-specific defaults.

        Returns:
            Dictionary of default option values
        """
        return {
            "preserve_layout": False,
            "max_pages": None,
            "encoding": "utf-8",
        }

    def merge_options(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Merge user options with defaults.

        Args:
            options: User-provided options

        Returns:
            Merged options dictionary
        """
        merged = self.get_default_options()
        if options:
            merged.update(options)
        return merged
