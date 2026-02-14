"""
Unit tests for coordinate mapping utilities.
"""

import pytest
import json

from potato.format_handlers.coordinate_mapping import (
    CharacterCoordinate,
    PDFCoordinate,
    SpreadsheetCoordinate,
    DocumentCoordinate,
    CodeCoordinate,
    BoundingBoxCoordinate,
    CoordinateMapping,
    CoordinateMapper,
    get_column_letter,
    get_cell_reference,
)


class TestCoordinateTypes:
    """Tests for coordinate dataclasses."""

    def test_character_coordinate(self):
        """Test CharacterCoordinate."""
        coord = CharacterCoordinate(offset=100)
        result = coord.to_dict()

        assert result["format"] == "character"
        assert result["offset"] == 100

    def test_pdf_coordinate_minimal(self):
        """Test PDFCoordinate with minimal data."""
        coord = PDFCoordinate(page=1)
        result = coord.to_dict()

        assert result["format"] == "pdf"
        assert result["page"] == 1
        assert "bbox" not in result
        assert "line" not in result

    def test_pdf_coordinate_full(self):
        """Test PDFCoordinate with all fields."""
        coord = PDFCoordinate(
            page=2,
            bbox=[10.5, 20.3, 100.8, 35.2],
            line=5
        )
        result = coord.to_dict()

        assert result["format"] == "pdf"
        assert result["page"] == 2
        assert result["bbox"] == [10.5, 20.3, 100.8, 35.2]
        assert result["line"] == 5

    def test_spreadsheet_coordinate_row_only(self):
        """Test SpreadsheetCoordinate with row only."""
        coord = SpreadsheetCoordinate(row=5)
        result = coord.to_dict()

        assert result["format"] == "spreadsheet"
        assert result["row"] == 6  # 1-indexed output
        assert "col" not in result

    def test_spreadsheet_coordinate_full(self):
        """Test SpreadsheetCoordinate with all fields."""
        coord = SpreadsheetCoordinate(
            row=4,
            col=2,
            cell_ref="C5",
            sheet="Sheet1"
        )
        result = coord.to_dict()

        assert result["format"] == "spreadsheet"
        assert result["row"] == 5  # 1-indexed
        assert result["col"] == 3  # 1-indexed
        assert result["cell_ref"] == "C5"
        assert result["sheet"] == "Sheet1"

    def test_document_coordinate(self):
        """Test DocumentCoordinate."""
        coord = DocumentCoordinate(
            paragraph_id="p_5",
            local_offset=10,
            section="Introduction",
            heading_level=2
        )
        result = coord.to_dict()

        assert result["format"] == "document"
        assert result["paragraph_id"] == "p_5"
        assert result["local_offset"] == 10
        assert result["section"] == "Introduction"
        assert result["heading_level"] == 2

    def test_code_coordinate(self):
        """Test CodeCoordinate."""
        coord = CodeCoordinate(
            line=25,
            column=15,
            function_name="process_data",
            class_name="DataProcessor"
        )
        result = coord.to_dict()

        assert result["format"] == "code"
        assert result["line"] == 25
        assert result["column"] == 15
        assert result["function_name"] == "process_data"
        assert result["class_name"] == "DataProcessor"

    def test_bounding_box_coordinate_minimal(self):
        """Test BoundingBoxCoordinate with minimal data."""
        coord = BoundingBoxCoordinate(
            page=1,
            bbox=[0.1, 0.2, 0.3, 0.4]
        )
        result = coord.to_dict()

        assert result["format"] == "bounding_box"
        assert result["page"] == 1
        assert result["bbox"] == [0.1, 0.2, 0.3, 0.4]
        assert "label" not in result
        assert "confidence" not in result

    def test_bounding_box_coordinate_full(self):
        """Test BoundingBoxCoordinate with all fields."""
        coord = BoundingBoxCoordinate(
            page=3,
            bbox=[0.1, 0.2, 0.5, 0.3],
            bbox_pixels=[50.0, 100.0, 250.0, 150.0],
            label="FIGURE",
            confidence=0.95
        )
        result = coord.to_dict()

        assert result["format"] == "bounding_box"
        assert result["page"] == 3
        assert result["bbox"] == [0.1, 0.2, 0.5, 0.3]
        assert result["bbox_pixels"] == [50.0, 100.0, 250.0, 150.0]
        assert result["label"] == "FIGURE"
        assert result["confidence"] == 0.95

    def test_bounding_box_from_pixel_coords(self):
        """Test creating BoundingBoxCoordinate from pixel coordinates."""
        coord = BoundingBoxCoordinate.from_pixel_coords(
            page=2,
            x=100,
            y=200,
            width=300,
            height=150,
            page_width=1000,
            page_height=1000,
            label="TABLE"
        )

        assert coord.page == 2
        assert coord.bbox == [0.1, 0.2, 0.3, 0.15]
        assert coord.bbox_pixels == [100, 200, 300, 150]
        assert coord.label == "TABLE"

    def test_bounding_box_to_pixel_coords(self):
        """Test converting normalized coordinates to pixels."""
        coord = BoundingBoxCoordinate(
            page=1,
            bbox=[0.1, 0.2, 0.3, 0.15]
        )

        pixels = coord.to_pixel_coords(1000, 500)

        assert pixels == [100.0, 100.0, 300.0, 75.0]


class TestCoordinateMapping:
    """Tests for CoordinateMapping."""

    def test_contains(self):
        """Test contains method."""
        mapping = CoordinateMapping(
            start=10,
            end=20,
            coordinate=CharacterCoordinate(offset=10)
        )

        assert mapping.contains(10) is True
        assert mapping.contains(15) is True
        assert mapping.contains(19) is True
        assert mapping.contains(9) is False
        assert mapping.contains(20) is False

    def test_overlaps(self):
        """Test overlaps method."""
        mapping = CoordinateMapping(
            start=10,
            end=20,
            coordinate=CharacterCoordinate(offset=10)
        )

        # Overlapping ranges
        assert mapping.overlaps(5, 15) is True
        assert mapping.overlaps(15, 25) is True
        assert mapping.overlaps(12, 18) is True
        assert mapping.overlaps(5, 25) is True

        # Non-overlapping ranges
        assert mapping.overlaps(0, 10) is False
        assert mapping.overlaps(20, 30) is False
        assert mapping.overlaps(25, 30) is False


class TestCoordinateMapper:
    """Tests for CoordinateMapper."""

    @pytest.fixture
    def mapper(self):
        """Create a mapper with sample data."""
        m = CoordinateMapper()
        m.add_mapping(0, 50, PDFCoordinate(page=1))
        m.add_mapping(50, 100, PDFCoordinate(page=2))
        m.add_mapping(100, 150, PDFCoordinate(page=3))
        return m

    def test_add_mapping(self):
        """Test adding mappings."""
        mapper = CoordinateMapper()
        mapper.add_mapping(0, 10, CharacterCoordinate(offset=0))

        assert mapper.get_mapping_count() == 1

    def test_get_coordinate_at(self, mapper):
        """Test getting coordinate at offset."""
        coord = mapper.get_coordinate_at(25)
        assert coord is not None
        assert coord.page == 1

        coord = mapper.get_coordinate_at(75)
        assert coord is not None
        assert coord.page == 2

        coord = mapper.get_coordinate_at(125)
        assert coord is not None
        assert coord.page == 3

    def test_get_coordinate_at_boundary(self, mapper):
        """Test getting coordinate at boundaries."""
        # Start of range should be included
        coord = mapper.get_coordinate_at(50)
        assert coord is not None
        assert coord.page == 2

        # End of range should not be included
        coord = mapper.get_coordinate_at(100)
        assert coord is not None
        assert coord.page == 3

    def test_get_coordinate_at_outside(self, mapper):
        """Test getting coordinate outside mapped ranges."""
        coord = mapper.get_coordinate_at(200)
        assert coord is None

    def test_get_coords_for_range(self, mapper):
        """Test getting coords for character range."""
        coords = mapper.get_coords_for_range(25, 35)
        assert coords is not None
        assert coords["format"] == "pdf"
        assert coords["page"] == 1

    def test_get_all_coords_for_range(self, mapper):
        """Test getting all coords for a range spanning multiple mappings."""
        coords = mapper.get_all_coords_for_range(40, 110)

        # Should return pages 1, 2, and 3
        assert len(coords) == 3
        pages = [c["page"] for c in coords]
        assert 1 in pages
        assert 2 in pages
        assert 3 in pages

    def test_to_dict(self, mapper):
        """Test serialization to dict."""
        data = mapper.to_dict()

        assert "mappings" in data
        assert len(data["mappings"]) == 3

        first = data["mappings"][0]
        assert "start" in first
        assert "end" in first
        assert "coordinate" in first

    def test_to_json(self, mapper):
        """Test JSON serialization."""
        json_str = mapper.to_json()
        parsed = json.loads(json_str)

        assert "mappings" in parsed
        assert len(parsed["mappings"]) == 3

    def test_from_dict_pdf(self):
        """Test deserialization of PDF coordinates."""
        data = {
            "mappings": [
                {
                    "start": 0,
                    "end": 50,
                    "coordinate": {
                        "format": "pdf",
                        "page": 1,
                        "bbox": [10, 20, 100, 30]
                    }
                }
            ]
        }

        mapper = CoordinateMapper.from_dict(data)
        coord = mapper.get_coordinate_at(25)

        assert coord is not None
        assert isinstance(coord, PDFCoordinate)
        assert coord.page == 1
        assert coord.bbox == [10, 20, 100, 30]

    def test_from_dict_spreadsheet(self):
        """Test deserialization of spreadsheet coordinates."""
        data = {
            "mappings": [
                {
                    "start": 0,
                    "end": 20,
                    "coordinate": {
                        "format": "spreadsheet",
                        "row": 5,  # 1-indexed in serialization
                        "col": 3,
                        "cell_ref": "C5"
                    }
                }
            ]
        }

        mapper = CoordinateMapper.from_dict(data)
        coord = mapper.get_coordinate_at(10)

        assert coord is not None
        assert isinstance(coord, SpreadsheetCoordinate)
        assert coord.row == 4  # 0-indexed internally
        assert coord.col == 2
        assert coord.cell_ref == "C5"

    def test_from_dict_code(self):
        """Test deserialization of code coordinates."""
        data = {
            "mappings": [
                {
                    "start": 0,
                    "end": 30,
                    "coordinate": {
                        "format": "code",
                        "line": 10,
                        "column": 5
                    }
                }
            ]
        }

        mapper = CoordinateMapper.from_dict(data)
        coord = mapper.get_coordinate_at(15)

        assert coord is not None
        assert isinstance(coord, CodeCoordinate)
        assert coord.line == 10
        assert coord.column == 5

    def test_from_dict_bounding_box(self):
        """Test deserialization of bounding box coordinates."""
        data = {
            "mappings": [
                {
                    "start": 0,
                    "end": 100,
                    "coordinate": {
                        "format": "bounding_box",
                        "page": 2,
                        "bbox": [0.1, 0.2, 0.5, 0.3],
                        "bbox_pixels": [50, 100, 250, 150],
                        "label": "FIGURE",
                        "confidence": 0.9
                    }
                }
            ]
        }

        mapper = CoordinateMapper.from_dict(data)
        coord = mapper.get_coordinate_at(50)

        assert coord is not None
        assert isinstance(coord, BoundingBoxCoordinate)
        assert coord.page == 2
        assert coord.bbox == [0.1, 0.2, 0.5, 0.3]
        assert coord.bbox_pixels == [50, 100, 250, 150]
        assert coord.label == "FIGURE"
        assert coord.confidence == 0.9


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_column_letter_single(self):
        """Test single letter columns."""
        assert get_column_letter(0) == "A"
        assert get_column_letter(1) == "B"
        assert get_column_letter(25) == "Z"

    def test_get_column_letter_double(self):
        """Test double letter columns."""
        assert get_column_letter(26) == "AA"
        assert get_column_letter(27) == "AB"
        assert get_column_letter(51) == "AZ"
        assert get_column_letter(52) == "BA"

    def test_get_cell_reference(self):
        """Test A1-style cell references."""
        assert get_cell_reference(0, 0) == "A1"
        assert get_cell_reference(0, 1) == "B1"
        assert get_cell_reference(4, 2) == "C5"
        assert get_cell_reference(9, 26) == "AA10"
