"""
PDF display asset wiring.

Regression tests for a defect where the *default* PDF annotation mode
(``annotation_mode: span``) rendered a container that no script ever
initialized: ``pdf-viewer.js`` existed but was not referenced by any template
and had no ``FRONTEND_ASSET_MARKERS`` key, so ``examples/image/pdf-annotation``
displayed an empty box. ``pdf_display.get_js_init()`` guarded on
``typeof initPDFViewers === 'function'`` and is itself never called, so the
failure was silent from every direction.
"""

import re
from pathlib import Path

import pytest

from potato.flask_server import FRONTEND_ASSET_MARKERS
from potato.server_utils.displays.pdf_display import PDFDisplay


STATIC = Path(__file__).resolve().parents[2] / "potato" / "static"
TEMPLATE = (
    Path(__file__).resolve().parents[2] / "potato" / "templates" / "base_template_v2.html"
)

PDF_KEYS = {"pdf_viewer", "pdf_bbox", "pdf_link"}


def _render(mode):
    cfg = {"key": "doc", "type": "pdf", "display_options": {"annotation_mode": mode}}
    return PDFDisplay().render(cfg, "file.pdf")


def _pdf_assets_fired(html):
    return {
        key
        for key in PDF_KEYS
        if any(marker in html for marker in FRONTEND_ASSET_MARKERS[key])
    }


class TestPdfModeAssetMapping:
    """Each PDF mode must light up exactly one asset bundle."""

    @pytest.mark.parametrize(
        "mode,expected",
        [
            ("span", "pdf_viewer"),          # the default, and the one that was dead
            ("bounding_box", "pdf_bbox"),
            ("link", "pdf_link"),
        ],
    )
    def test_mode_fires_exactly_one_asset(self, mode, expected):
        fired = _pdf_assets_fired(_render(mode))
        assert fired == {expected}, (
            f"annotation_mode={mode!r} fired {fired or 'nothing'}; expected "
            f"{{{expected!r}}}. Firing nothing means the container renders with "
            f"no script to drive it; firing more than one means two scripts "
            f"will fight over the same canvas."
        )

    def test_default_mode_is_span(self):
        """The mode that was broken is the one you get by not choosing."""
        cfg = {"key": "doc", "type": "pdf"}
        assert _pdf_assets_fired(PDFDisplay().render(cfg, "file.pdf")) == {"pdf_viewer"}


class TestPdfJsLoadedOffline:
    """PDF.js is vendored; nothing may reach for the CDN on its own."""

    def test_only_the_shared_loader_names_the_cdn(self):
        offenders = []
        for js in STATIC.rglob("*.js"):
            if js.name == "pdfjs-loader.js" or "vendor" in js.parts:
                continue
            text = js.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"cdnjs\.cloudflare\.com/ajax/libs/pdf\.js", text):
                offenders.append(str(js.relative_to(STATIC)))
        assert not offenders, (
            "These files load PDF.js from a CDN instead of going through "
            f"window.PotatoPDFJS.load(): {offenders}. A second copy of the "
            "loader is what broke offline PDF support the first time."
        )

    def test_vendored_pdfjs_is_present(self):
        for name in ("pdf.min.js", "pdf.worker.min.js"):
            assert (STATIC / "vendor" / "pdfjs" / name).is_file(), (
                f"vendor/pdfjs/{name} is missing, so the loader's local-first "
                f"path always falls through to the CDN."
            )

    def test_loader_precedes_its_consumers_in_template(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        loader = text.find("js/pdfjs-loader.js")
        assert loader != -1, "base_template_v2.html never includes js/pdfjs-loader.js"
        for consumer in ("pdf-link-mode.js", "js/pdf-viewer.js"):
            at = text.find(consumer)
            assert at != -1, f"base_template_v2.html never includes {consumer}"
            assert loader < at, (
                f"{consumer} is included before js/pdfjs-loader.js; "
                f"window.PotatoPDFJS would be undefined when it runs."
            )


class TestTemplateScriptsExist:
    """A template may not point at a static file that is not there."""

    def test_every_referenced_static_js_exists(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        refs = re.findall(r"filename='([^']+\.js)'", text)
        missing = [r for r in refs if not (STATIC / r).is_file()]
        assert not missing, f"base_template_v2.html references missing files: {missing}"
