"""
Coordinate Mapping Utilities

Provides data structures and utilities for mapping character offsets
to format-specific coordinates (page/bbox for PDF, row/col for spreadsheets, etc.).

Usage:
    from potato.format_handlers.coordinate_mapping import (
        CoordinateMapper,
        PDFCoordinate,
        SpreadsheetCoordinate,
    )

    # Build a coordinate map during extraction
    mapper = CoordinateMapper()
    mapper.add_mapping(0, 100, PDFCoordinate(page=1, bbox=[10, 20, 200, 30]))

    # Look up coordinates for a span
    coords = mapper.get_coords_for_range(50, 75)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Union
from bisect import bisect_left, bisect_right
import json


@dataclass
class CharacterCoordinate:
    """Base coordinate type representing a character position."""
    offset: int
    format_type: str = "character"

    def to_dict(self) -> Dict[str, Any]:
        return {"format": self.format_type, "offset": self.offset}


@dataclass
class PDFCoordinate:
    """
    Coordinate for PDF documents.

    Attributes:
        page: Page number (1-indexed)
        bbox: Bounding box [x0, y0, x1, y1] in PDF points
        line: Optional line number on the page
    """
    page: int
    bbox: List[float] = field(default_factory=list)
    line: Optional[int] = None
    format_type: str = "pdf"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "format": self.format_type,
            "page": self.page,
        }
        if self.bbox:
            result["bbox"] = self.bbox
        if self.line is not None:
            result["line"] = self.line
        return result


@dataclass
class SpreadsheetCoordinate:
    """
    Coordinate for spreadsheet documents.

    Attributes:
        row: Row number (0-indexed internally, displayed as 1-indexed)
        col: Column number (0-indexed internally)
        cell_ref: Cell reference in A1 notation (e.g., "B5")
        sheet: Sheet name (for multi-sheet documents)
    """
    row: int
    col: Optional[int] = None
    cell_ref: Optional[str] = None
    sheet: Optional[str] = None
    format_type: str = "spreadsheet"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "format": self.format_type,
            "row": self.row + 1,  # Convert to 1-indexed for output
        }
        if self.col is not None:
            result["col"] = self.col + 1
        if self.cell_ref:
            result["cell_ref"] = self.cell_ref
        if self.sheet:
            result["sheet"] = self.sheet
        return result


@dataclass
class DocumentCoordinate:
    """
    Coordinate for document formats (DOCX, Markdown).

    Attributes:
        paragraph_id: Unique identifier for the paragraph
        local_offset: Character offset within the paragraph
        section: Optional section name/number
        heading_level: If in a heading, its level (1-6)
    """
    paragraph_id: str
    local_offset: int = 0
    section: Optional[str] = None
    heading_level: Optional[int] = None
    format_type: str = "document"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "format": self.format_type,
            "paragraph_id": self.paragraph_id,
            "local_offset": self.local_offset,
        }
        if self.section:
            result["section"] = self.section
        if self.heading_level:
            result["heading_level"] = self.heading_level
        return result


@dataclass
class CodeCoordinate:
    """
    Coordinate for source code files.

    Attributes:
        line: Line number (1-indexed)
        column: Column number (1-indexed)
        function_name: Name of the containing function (if any)
        class_name: Name of the containing class (if any)
    """
    line: int
    column: int = 1
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    format_type: str = "code"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "format": self.format_type,
            "line": self.line,
            "column": self.column,
        }
        if self.function_name:
            result["function_name"] = self.function_name
        if self.class_name:
            result["class_name"] = self.class_name
        return result


@dataclass
class BoundingBoxCoordinate:
    """
    Coordinate for bounding box annotations on images/PDF pages.

    Attributes:
        page: Page number (1-indexed, for PDFs)
        bbox: Bounding box [x, y, width, height] in normalized coordinates (0-1)
        bbox_pixels: Optional bounding box in pixel coordinates
        label: Label/class for the bounding box
        confidence: Optional confidence score (0-1)
    """
    page: int
    bbox: List[float]  # [x, y, width, height] normalized 0-1
    bbox_pixels: Optional[List[float]] = None  # [x, y, width, height] in pixels
    label: Optional[str] = None
    confidence: Optional[float] = None
    format_type: str = "bounding_box"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "format": self.format_type,
            "page": self.page,
            "bbox": self.bbox,
        }
        if self.bbox_pixels:
            result["bbox_pixels"] = self.bbox_pixels
        if self.label:
            result["label"] = self.label
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result

    @classmethod
    def from_pixel_coords(
        cls,
        page: int,
        x: float,
        y: float,
        width: float,
        height: float,
        page_width: float,
        page_height: float,
        label: Optional[str] = None
    ) -> "BoundingBoxCoordinate":
        """
        Create a BoundingBoxCoordinate from pixel coordinates.

        Args:
            page: Page number (1-indexed)
            x, y, width, height: Bounding box in pixels
            page_width, page_height: Page dimensions in pixels
            label: Optional label for the box

        Returns:
            BoundingBoxCoordinate with normalized coords
        """
        return cls(
            page=page,
            bbox=[
                x / page_width,
                y / page_height,
                width / page_width,
                height / page_height
            ],
            bbox_pixels=[x, y, width, height],
            label=label
        )

    def to_pixel_coords(
        self,
        page_width: float,
        page_height: float
    ) -> List[float]:
        """
        Convert normalized coordinates to pixels.

        Args:
            page_width: Page width in pixels
            page_height: Page height in pixels

        Returns:
            [x, y, width, height] in pixels
        """
        return [
            self.bbox[0] * page_width,
            self.bbox[1] * page_height,
            self.bbox[2] * page_width,
            self.bbox[3] * page_height
        ]


# Type alias for any coordinate type
Coordinate = Union[
    CharacterCoordinate,
    PDFCoordinate,
    SpreadsheetCoordinate,
    DocumentCoordinate,
    CodeCoordinate,
    BoundingBoxCoordinate,
]


@dataclass
class CoordinateMapping:
    """
    Maps a character range to format-specific coordinates.

    Attributes:
        start: Start character offset (inclusive)
        end: End character offset (exclusive)
        coordinate: Format-specific coordinate data
    """
    start: int
    end: int
    coordinate: Coordinate

    def contains(self, offset: int) -> bool:
        """Check if an offset falls within this mapping."""
        return self.start <= offset < self.end

    def overlaps(self, start: int, end: int) -> bool:
        """Check if a range overlaps with this mapping."""
        return self.start < end and start < self.end


class CoordinateMapper:
    """
    Manages mappings from character offsets to format-specific coordinates.

    Provides efficient lookup of coordinates for character ranges.
    """

    def __init__(self):
        self._mappings: List[CoordinateMapping] = []
        self._sorted = True
        self._start_offsets: List[int] = []  # For binary search

    def add_mapping(
        self,
        start: int,
        end: int,
        coordinate: Coordinate
    ) -> None:
        """
        Add a mapping from character range to coordinate.

        Args:
            start: Start character offset (inclusive)
            end: End character offset (exclusive)
            coordinate: Format-specific coordinate data
        """
        mapping = CoordinateMapping(start=start, end=end, coordinate=coordinate)
        self._mappings.append(mapping)
        self._sorted = False

    def _ensure_sorted(self) -> None:
        """Sort mappings by start offset if needed."""
        if not self._sorted:
            self._mappings.sort(key=lambda m: m.start)
            self._start_offsets = [m.start for m in self._mappings]
            self._sorted = True

    def get_coordinate_at(self, offset: int) -> Optional[Coordinate]:
        """
        Get the coordinate at a specific character offset.

        Args:
            offset: Character offset

        Returns:
            Coordinate if found, None otherwise
        """
        self._ensure_sorted()

        # Binary search for the potential mapping
        idx = bisect_right(self._start_offsets, offset) - 1
        if idx >= 0 and self._mappings[idx].contains(offset):
            return self._mappings[idx].coordinate
        return None

    def get_coords_for_range(
        self,
        start: int,
        end: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get format coordinates for a character range.

        For spans crossing multiple coordinates (e.g., multiple PDF pages),
        returns the coordinates of the first character.

        Args:
            start: Start character offset (inclusive)
            end: End character offset (exclusive)

        Returns:
            Dictionary with format-specific coordinates, or None if not found
        """
        coord = self.get_coordinate_at(start)
        if coord:
            return coord.to_dict()
        return None

    def get_all_coords_for_range(
        self,
        start: int,
        end: int
    ) -> List[Dict[str, Any]]:
        """
        Get all coordinates that overlap with a character range.

        Useful for spans crossing multiple structural elements.

        Args:
            start: Start character offset (inclusive)
            end: End character offset (exclusive)

        Returns:
            List of coordinate dictionaries
        """
        self._ensure_sorted()
        coords = []

        for mapping in self._mappings:
            if mapping.overlaps(start, end):
                coords.append(mapping.coordinate.to_dict())
            elif mapping.start >= end:
                break  # No more overlapping mappings

        return coords

    def get_mapping_count(self) -> int:
        """Get the number of mappings stored."""
        return len(self._mappings)

    def to_dict(self) -> Dict[str, Any]:
        """
        Export mappings as a dictionary.

        Returns:
            Dictionary representation of all mappings
        """
        self._ensure_sorted()
        return {
            "mappings": [
                {
                    "start": m.start,
                    "end": m.end,
                    "coordinate": m.coordinate.to_dict()
                }
                for m in self._mappings
            ]
        }

    def to_json(self) -> str:
        """Export mappings as JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoordinateMapper":
        """
        Create a CoordinateMapper from a dictionary.

        Args:
            data: Dictionary with mappings

        Returns:
            New CoordinateMapper instance
        """
        mapper = cls()
        for m in data.get("mappings", []):
            coord_data = m["coordinate"]
            format_type = coord_data.get("format", "character")

            # Recreate coordinate object based on format type
            if format_type == "pdf":
                coord = PDFCoordinate(
                    page=coord_data["page"],
                    bbox=coord_data.get("bbox", []),
                    line=coord_data.get("line"),
                )
            elif format_type == "spreadsheet":
                coord = SpreadsheetCoordinate(
                    row=coord_data["row"] - 1,  # Convert back to 0-indexed
                    col=coord_data.get("col", 1) - 1 if coord_data.get("col") else None,
                    cell_ref=coord_data.get("cell_ref"),
                    sheet=coord_data.get("sheet"),
                )
            elif format_type == "document":
                coord = DocumentCoordinate(
                    paragraph_id=coord_data["paragraph_id"],
                    local_offset=coord_data.get("local_offset", 0),
                    section=coord_data.get("section"),
                    heading_level=coord_data.get("heading_level"),
                )
            elif format_type == "code":
                coord = CodeCoordinate(
                    line=coord_data["line"],
                    column=coord_data.get("column", 1),
                    function_name=coord_data.get("function_name"),
                    class_name=coord_data.get("class_name"),
                )
            elif format_type == "bounding_box":
                coord = BoundingBoxCoordinate(
                    page=coord_data["page"],
                    bbox=coord_data["bbox"],
                    bbox_pixels=coord_data.get("bbox_pixels"),
                    label=coord_data.get("label"),
                    confidence=coord_data.get("confidence"),
                )
            else:
                coord = CharacterCoordinate(offset=coord_data.get("offset", m["start"]))

            mapper.add_mapping(m["start"], m["end"], coord)

        return mapper


def get_column_letter(col_idx: int) -> str:
    """
    Convert a 0-indexed column number to Excel column letter.

    Args:
        col_idx: 0-indexed column number

    Returns:
        Column letter (A, B, ..., Z, AA, AB, ...)
    """
    result = ""
    col_idx += 1  # Convert to 1-indexed
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def get_cell_reference(row: int, col: int) -> str:
    """
    Get A1-style cell reference.

    Args:
        row: 0-indexed row number
        col: 0-indexed column number

    Returns:
        Cell reference like "A1", "B5", "AA100"
    """
    return f"{get_column_letter(col)}{row + 1}"
