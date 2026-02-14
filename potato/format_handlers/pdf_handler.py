"""
PDF Format Handler

Extracts text and layout information from PDF files using pdfplumber.
Supports text extraction with character-level position mapping.

Usage:
    from potato.format_handlers.pdf_handler import PDFHandler

    handler = PDFHandler()
    output = handler.extract("document.pdf", {
        "extraction_mode": "text",  # or "layout"
        "max_pages": 10,
    })

    # Access extracted content
    text = output.text
    html = output.rendered_html
    coords = output.coordinate_map
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import html
import logging

from .base import BaseFormatHandler, FormatOutput
from .coordinate_mapping import CoordinateMapper, PDFCoordinate

logger = logging.getLogger(__name__)

# Check if pdfplumber is available
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    pdfplumber = None


class PDFHandler(BaseFormatHandler):
    """
    Handler for PDF documents.

    Uses pdfplumber for text extraction with position information.
    Generates HTML representation suitable for span annotation.
    """

    format_name = "pdf"
    supported_extensions = [".pdf"]
    description = "PDF document text extraction with page/position mapping"
    requires_dependencies = ["pdfplumber"]

    def get_default_options(self) -> Dict[str, Any]:
        """Get default extraction options."""
        return {
            "extraction_mode": "text",  # "text" or "layout"
            "preserve_layout": False,
            "max_pages": None,
            "include_page_breaks": True,
            "page_separator": "\n\n--- Page {page} ---\n\n",
            "extract_tables": False,
            "x_tolerance": 3,  # Horizontal tolerance for word grouping
            "y_tolerance": 3,  # Vertical tolerance for line grouping
        }

    def extract(
        self,
        file_path: str,
        options: Optional[Dict[str, Any]] = None
    ) -> FormatOutput:
        """
        Extract text and layout from a PDF file.

        Args:
            file_path: Path to the PDF file
            options: Extraction options:
                - extraction_mode: "text" (plain) or "layout" (preserve layout)
                - max_pages: Maximum pages to process (None for all)
                - include_page_breaks: Include page separators in text
                - page_separator: Format string for page breaks ({page} replaced)
                - extract_tables: Also extract table structures

        Returns:
            FormatOutput with extracted text, HTML, and coordinate mappings
        """
        if not PDFPLUMBER_AVAILABLE:
            raise ImportError(
                "pdfplumber is required for PDF extraction. "
                "Install with: pip install pdfplumber"
            )

        opts = self.merge_options(options)
        mapper = CoordinateMapper()

        text_parts = []
        html_parts = []
        current_offset = 0

        metadata = {
            "format": "pdf",
            "pages": [],
            "total_pages": 0,
            "source_file": str(file_path),
        }

        html_parts.append('<div class="pdf-content">')

        with pdfplumber.open(file_path) as pdf:
            metadata["total_pages"] = len(pdf.pages)
            max_pages = opts.get("max_pages") or len(pdf.pages)

            for page_num, page in enumerate(pdf.pages[:max_pages], start=1):
                page_text, page_html, page_coords = self._extract_page(
                    page, page_num, opts, current_offset
                )

                # Add page coordinates to mapper
                for coord_info in page_coords:
                    mapper.add_mapping(
                        coord_info["start"],
                        coord_info["end"],
                        PDFCoordinate(
                            page=page_num,
                            bbox=coord_info.get("bbox", []),
                            line=coord_info.get("line"),
                        )
                    )

                # Add page separator
                if page_num > 1 and opts.get("include_page_breaks"):
                    separator = opts["page_separator"].format(page=page_num)
                    text_parts.append(separator)
                    current_offset += len(separator)

                text_parts.append(page_text)
                html_parts.append(page_html)
                current_offset += len(page_text)

                # Page metadata
                page_meta = {
                    "page_number": page_num,
                    "width": float(page.width),
                    "height": float(page.height),
                    "char_count": len(page_text),
                }
                metadata["pages"].append(page_meta)

        html_parts.append('</div>')

        full_text = "".join(text_parts)
        full_html = "\n".join(html_parts)

        # Create output with coordinate lookup function
        coord_dict = mapper.to_dict()
        coord_dict["get_coords_for_range"] = mapper.get_coords_for_range

        return FormatOutput(
            text=full_text,
            rendered_html=full_html,
            coordinate_map=coord_dict,
            metadata=metadata,
            format_name=self.format_name,
            source_path=str(file_path),
        )

    def _extract_page(
        self,
        page,
        page_num: int,
        opts: Dict[str, Any],
        base_offset: int
    ) -> tuple:
        """
        Extract text and HTML from a single page.

        Returns:
            Tuple of (text, html, coordinate_mappings)
        """
        extraction_mode = opts.get("extraction_mode", "text")

        if extraction_mode == "layout":
            return self._extract_page_layout(page, page_num, opts, base_offset)
        else:
            return self._extract_page_text(page, page_num, opts, base_offset)

    def _extract_page_text(
        self,
        page,
        page_num: int,
        opts: Dict[str, Any],
        base_offset: int
    ) -> tuple:
        """
        Extract text with word-level coordinate mapping.
        """
        text_parts = []
        html_parts = []
        coords = []
        current_offset = base_offset

        # Extract words with their positions
        words = page.extract_words(
            x_tolerance=opts.get("x_tolerance", 3),
            y_tolerance=opts.get("y_tolerance", 3),
        )

        html_parts.append(f'<div class="pdf-page" data-page="{page_num}">')

        if not words:
            # Fall back to full text extraction if no words found
            text = page.extract_text() or ""
            text_parts.append(text)
            html_parts.append(f'<span class="pdf-text">{html.escape(text)}</span>')

            if text:
                coords.append({
                    "start": current_offset,
                    "end": current_offset + len(text),
                    "bbox": [0, 0, float(page.width), float(page.height)],
                })
        else:
            # Process words with positions
            current_line_top = None
            line_words = []

            for word in words:
                word_top = word["top"]

                # Check if this is a new line
                if current_line_top is None:
                    current_line_top = word_top
                elif abs(word_top - current_line_top) > opts.get("y_tolerance", 3):
                    # Flush current line
                    if line_words:
                        line_text, line_html, line_coords = self._process_line(
                            line_words, current_offset
                        )
                        text_parts.append(line_text)
                        text_parts.append("\n")
                        html_parts.append(line_html)
                        html_parts.append("<br>")
                        coords.extend(line_coords)
                        current_offset += len(line_text) + 1  # +1 for newline

                    line_words = []
                    current_line_top = word_top

                line_words.append(word)

            # Process final line
            if line_words:
                line_text, line_html, line_coords = self._process_line(
                    line_words, current_offset
                )
                text_parts.append(line_text)
                html_parts.append(line_html)
                coords.extend(line_coords)

        html_parts.append('</div>')

        return "".join(text_parts), "\n".join(html_parts), coords

    def _process_line(
        self,
        words: List[Dict],
        base_offset: int
    ) -> tuple:
        """
        Process a line of words into text, HTML, and coordinates.
        """
        text_parts = []
        html_parts = []
        coords = []
        current_offset = base_offset

        for i, word in enumerate(words):
            word_text = word["text"]

            # Add space between words
            if i > 0:
                text_parts.append(" ")
                current_offset += 1

            start = current_offset
            end = start + len(word_text)

            text_parts.append(word_text)
            html_parts.append(
                f'<span class="pdf-word" '
                f'data-start="{start}" '
                f'data-end="{end}">'
                f'{html.escape(word_text)}</span>'
            )

            # Store coordinate mapping
            coords.append({
                "start": start,
                "end": end,
                "bbox": [
                    float(word["x0"]),
                    float(word["top"]),
                    float(word["x1"]),
                    float(word["bottom"]),
                ],
            })

            current_offset = end

        return "".join(text_parts), " ".join(html_parts), coords

    def _extract_page_layout(
        self,
        page,
        page_num: int,
        opts: Dict[str, Any],
        base_offset: int
    ) -> tuple:
        """
        Extract text preserving visual layout.
        """
        # Use extract_text with layout preservation
        text = page.extract_text(layout=True) or ""

        html_parts = []
        html_parts.append(f'<div class="pdf-page pdf-page-layout" data-page="{page_num}">')
        html_parts.append(f'<pre class="pdf-layout-text">{html.escape(text)}</pre>')
        html_parts.append('</div>')

        # For layout mode, we map the entire page
        coords = [{
            "start": base_offset,
            "end": base_offset + len(text),
            "bbox": [0, 0, float(page.width), float(page.height)],
        }]

        return text, "\n".join(html_parts), coords

    def get_page_count(self, file_path: str) -> int:
        """
        Get the number of pages in a PDF.

        Args:
            file_path: Path to the PDF file

        Returns:
            Number of pages
        """
        if not PDFPLUMBER_AVAILABLE:
            raise ImportError("pdfplumber is required")

        with pdfplumber.open(file_path) as pdf:
            return len(pdf.pages)

    def extract_page(
        self,
        file_path: str,
        page_number: int,
        options: Optional[Dict[str, Any]] = None
    ) -> FormatOutput:
        """
        Extract a single page from a PDF.

        Args:
            file_path: Path to the PDF file
            page_number: Page number (1-indexed)
            options: Extraction options

        Returns:
            FormatOutput for the single page
        """
        if not PDFPLUMBER_AVAILABLE:
            raise ImportError("pdfplumber is required")

        opts = self.merge_options(options)
        opts["max_pages"] = page_number  # Process up to this page
        opts["include_page_breaks"] = False

        # Extract only the requested page
        mapper = CoordinateMapper()

        with pdfplumber.open(file_path) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                raise ValueError(
                    f"Page {page_number} out of range (1-{len(pdf.pages)})"
                )

            page = pdf.pages[page_number - 1]
            page_text, page_html, page_coords = self._extract_page(
                page, page_number, opts, 0
            )

            for coord_info in page_coords:
                mapper.add_mapping(
                    coord_info["start"],
                    coord_info["end"],
                    PDFCoordinate(
                        page=page_number,
                        bbox=coord_info.get("bbox", []),
                    )
                )

        coord_dict = mapper.to_dict()
        coord_dict["get_coords_for_range"] = mapper.get_coords_for_range

        return FormatOutput(
            text=page_text,
            rendered_html=page_html,
            coordinate_map=coord_dict,
            metadata={
                "format": "pdf",
                "page_number": page_number,
                "total_pages": len(pdf.pages),
            },
            format_name=self.format_name,
            source_path=str(file_path),
        )
