"""
Unit tests for the opt-in OCR extraction path in PDFHandler.

OCR is off by default and requires pytesseract + the tesseract binary. These
tests verify the opt-in gating and the error surfaced when the dependency is
missing, and (when available) that OCR yields the same word-span/coord output
shape as text extraction so downstream span code is unchanged.
"""

import os

import pytest

from potato.format_handlers import pdf_handler
from potato.format_handlers.pdf_handler import PDFHandler, PDFPLUMBER_AVAILABLE

SAMPLE_PDF = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "examples", "advanced", "pdf-link-paginated", "media", "sample-paper.pdf",
)

pytestmark = pytest.mark.skipif(not PDFPLUMBER_AVAILABLE, reason="pdfplumber not installed")


def test_ocr_default_is_off():
    """Default options must not enable OCR (it is slow to initialize)."""
    assert PDFHandler().get_default_options()["ocr"] is False


def test_ocr_requested_without_pytesseract_raises_clear_error(monkeypatch):
    """When OCR is requested but pytesseract is absent, fail loudly & clearly."""
    monkeypatch.setattr(pdf_handler, "PYTESSERACT_AVAILABLE", False)
    handler = PDFHandler()
    with pytest.raises(ImportError, match="pytesseract"):
        handler.extract(SAMPLE_PDF, {"ocr": True})


@pytest.mark.skipif(not pdf_handler.PYTESSERACT_AVAILABLE, reason="pytesseract not installed")
def test_ocr_extraction_produces_word_spans_and_coords():
    """When available, OCR emits pdf-word spans + per-word PDF-point bboxes."""
    handler = PDFHandler()
    out = handler.extract(SAMPLE_PDF, {"ocr": True, "max_pages": 1})
    assert "pdf-word" in out.rendered_html
    assert out.text.strip()
    # coordinate map should carry at least one word mapping
    assert out.coordinate_map


def test_extract_words_by_page_text_mode():
    """The client text-layer feed: per-page words with per-page offsets + boxes.

    'auto' needs no OCR when the page has embedded text, so this exercises the
    plumbing that powers the scanned-PDF text layer without a tesseract binary.
    """
    pages = PDFHandler().extract_words_by_page(SAMPLE_PDF, {"ocr": "auto"})
    assert sorted(pages.keys()) == [1, 2, 3]
    p1 = pages[1]
    assert p1, "expected words on page 1"
    for w in p1:
        assert set(w) == {"text", "start", "end", "bbox"}
        assert w["end"] > w["start"]
        assert len(w["bbox"]) == 4
    # per-page offsets are strictly increasing and non-overlapping
    assert all(p1[i]["end"] <= p1[i + 1]["start"] for i in range(len(p1) - 1))
    # offsets reset per page (page 2 starts at 0 like page 1)
    assert pages[2][0]["start"] == 0
