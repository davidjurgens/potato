"""
Selenium tests for multi-page PDF anchors + cross-page linking.

Exercises the `annotation_mode: link` PDF display end to end against the bundled
examples (examples/advanced/pdf-link-scroll and pdf-link-paginated):
  * all PDF pages render into per-page containers (vendored PDF.js, offline-safe)
  * text-span and region (bbox) anchors are created and rendered over the canvas
  * anchors on different pages are linked, drawing an SVG arc across the stack
  * anchors + links persist through /updateinstance and restore on reload

Anchor creation is driven through the module's public API (window-attached
instance) for determinism; the underlying save/load/render pipeline is the real
one (fetch to /updateinstance, /api/spans, /api/links).
"""

import os
import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(REPO_ROOT, "examples/advanced/pdf-link-scroll/config.yaml")
PAGINATED_CONFIG = os.path.join(REPO_ROOT, "examples/advanced/pdf-link-paginated/config.yaml")


class TestPdfLinkAnnotation:
    @classmethod
    def setup_class(cls):
        port = find_free_port(preferred_port=9495)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=CONFIG)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        opts = ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1500,2000")
        cls.chrome_options = opts

    @classmethod
    def teardown_class(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()

    def setup_method(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)

    def teardown_method(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login_and_open_annotate(self):
        """Register + authenticate a fresh user, then open the annotate page.

        The config has no consent/instructions gate, so /annotate renders the
        PDF link display directly once authenticated.
        """
        user = f"pdflink_{int(time.time() * 1000)}"
        self.driver.get(f"{self.server.base_url}/")
        self.driver.execute_async_script(
            """
            const [base, user, done] = arguments;
            const form = (d) => Object.entries(d).map(([k,v]) =>
                encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');
            const opt = (body) => ({method:'POST', headers:
                {'Content-Type':'application/x-www-form-urlencoded'}, body});
            (async () => {
                await fetch(base+'/register', opt(form({email:user, pass:'pw123'})));
                await fetch(base+'/auth', opt(form({email:user, pass:'pw123'})));
                done(true);
            })();
            """,
            self.server.base_url, user,
        )
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1.5)

    def _wait_pages(self, n=3, timeout=25):
        end = time.time() + timeout
        while time.time() < end:
            if self.driver.execute_script(
                "return document.querySelectorAll('.pdf-page-canvas').length"
            ) >= n:
                return True
            time.sleep(0.5)
        return False

    def test_pages_render(self):
        self._login_and_open_annotate()
        assert self._wait_pages(3), "expected all 3 PDF pages to render"
        # text layer should be populated for text-span selection
        spans = self.driver.execute_script(
            "return document.querySelectorAll('.pdf-text-layer span').length"
        )
        assert spans > 0, "PDF text layer not populated"
        assert self.driver.execute_script("return !!window.pdfjsLib"), "PDF.js not loaded"

    def test_cross_page_anchor_link_persists_on_reload(self):
        self._login_and_open_annotate()
        assert self._wait_pages(3)

        # Create a region anchor on page 3 and a text anchor on page 1, then link.
        self.driver.execute_script(
            """
            const m = document.querySelector('.pdf-link-mode')._pdfLinkMode;
            m.currentLabel = 'figure';
            m.addAnchor({id:'sel_r3', kind:'region', page:3, label:'figure',
                         start:0, end:0, bbox:[0.15,0.30,0.4,0.2]}, true);
            m.currentLabel = 'claim';
            m.addAnchor({id:'sel_t1', kind:'text', page:1, label:'claim',
                         start:10, end:30, bbox:[0.12,0.24,0.5,0.05]}, true);
            m.currentLinkType = 'refers_to';
            m.linkModeOn = true;
            m.selectedForLink = ['sel_t1','sel_r3'];
            m.createLink();
            """
        )
        time.sleep(1.5)

        anchors = self.driver.execute_script(
            "return document.querySelectorAll('.pdf-anchor').length")
        arcs = self.driver.execute_script(
            "return document.querySelectorAll('.pdf-link-overlay .pdf-arc').length")
        assert anchors >= 2, f"expected >=2 anchor elements, got {anchors}"
        assert arcs >= 1, f"expected a cross-page arc, got {arcs}"

        # Verify server-side persistence via the APIs.
        data = self.driver.execute_async_script(
            """
            const done = arguments[arguments.length-1];
            const inst = document.getElementById('instance_id').value;
            const s = await (await fetch('/api/spans/'+inst)).json();
            const l = await (await fetch('/api/links/'+inst)).json();
            done({spans: s.spans||[], links: l.links||[]});
            """
        )
        pdf_anchors = [s for s in data["spans"]
                       if (s.get("format_coords") or {}).get("format") == "pdf"]
        kinds = sorted((a["format_coords"]["anchor_kind"], a["format_coords"]["page"])
                       for a in pdf_anchors)
        assert ("region", 3) in kinds and ("text", 1) in kinds, kinds
        assert any(set(l["span_ids"]) == {"sel_t1", "sel_r3"} for l in data["links"])

        # Reload and confirm anchors + link + arc restore.
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)
        assert self._wait_pages(3)
        time.sleep(2.5)  # allow loadAnchors/loadLinks + arc render
        restored = self.driver.execute_script(
            """
            const m = document.querySelector('.pdf-link-mode')._pdfLinkMode;
            return {anchors: m.anchors.size, links: m.links.length,
                    arcs: document.querySelectorAll('.pdf-link-overlay .pdf-arc').length};
            """
        )
        assert restored["anchors"] >= 2, restored
        assert restored["links"] >= 1, restored
        assert restored["arcs"] >= 1, restored

    def test_ocr_text_layer_from_words_is_selectable(self):
        """Scanned-PDF path: a text layer built from OCR words is selectable and
        yields a text anchor with the words' char offsets."""
        self._login_and_open_annotate()
        assert self._wait_pages(3)

        made = self.driver.execute_script(
            """
            const m = document.querySelector('.pdf-link-mode')._pdfLinkMode;
            // Simulate server-provided OCR words for page 1 (bbox in PDF points).
            m.ocrPages['1'] = [
                {text:'Hello', start:0, end:5, bbox:[50,60,120,80]},
                {text:'World', start:6, end:11, bbox:[125,60,200,80]},
            ];
            const rec = m.pages[1];
            rec.textLayer.innerHTML = '';
            m._buildOcrTextLayer(rec, 1);
            const spans = rec.textLayer.querySelectorAll('.pdf-ocr-word');
            // Select across both OCR words -> should create a text anchor.
            const sel = window.getSelection(); sel.removeAllRanges();
            const range = document.createRange();
            range.setStart(spans[0].firstChild, 0);
            range.setEnd(spans[1].firstChild, spans[1].firstChild.length);
            sel.addRange(range);
            m._createTextAnchorFromSelection(1, rec);
            const text = [...m.anchors.values()].find(a => a.kind === 'text');
            return {spanCount: spans.length,
                    hasOffsets: !!(spans[0].dataset.wordStart !== undefined),
                    anchorStart: text && text.start, anchorEnd: text && text.end};
            """
        )
        assert made["spanCount"] == 2, made
        assert made["hasOffsets"], made
        assert made["anchorStart"] == 0 and made["anchorEnd"] == 11, made

    def test_link_label_constraints_enforced(self):
        """Directed refers_to requires source=claim, target=figure. A figure-first
        click is rejected; claim->figure succeeds."""
        self._login_and_open_annotate()
        assert self._wait_pages(3)

        result = self.driver.execute_script(
            """
            const m = document.querySelector('.pdf-link-mode')._pdfLinkMode;
            m.addAnchor({id:'c1', kind:'text', page:1, label:'claim',
                         start:5, end:20, bbox:[0.1,0.2,0.4,0.05]}, false);
            m.addAnchor({id:'f1', kind:'region', page:1, label:'figure',
                         start:0, end:0, bbox:[0.1,0.5,0.4,0.2]}, false);
            m.currentLinkType = 'refers_to';   // directed, claim -> figure
            m.linkModeOn = true;

            // Violation: figure as source must be rejected.
            m._onAnchorClick('f1');
            const afterViolation = m.selectedForLink.length;

            // Valid: claim (source) then figure (target) -> auto-creates link.
            m._onAnchorClick('c1');
            m._onAnchorClick('f1');
            return {afterViolation, links: m.links.length,
                    linkIds: m.links[0] && m.links[0].span_ids};
            """
        )
        assert result["afterViolation"] == 0, "figure-as-source should be rejected"
        assert result["links"] == 1, result
        assert set(result["linkIds"]) == {"c1", "f1"}, result


class TestPdfLinkPaginated:
    """Paginated view: thumbnail navigation + pin-navigate cross-page linking."""

    @classmethod
    def setup_class(cls):
        port = find_free_port(preferred_port=9496)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=PAGINATED_CONFIG)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        opts = ChromeOptions()
        for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--window-size=1500,2000"):
            opts.add_argument(a)
        cls.chrome_options = opts

    @classmethod
    def teardown_class(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()

    def setup_method(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)

    def teardown_method(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login_and_open_annotate(self):
        user = f"pdfpag_{int(time.time() * 1000)}"
        self.driver.get(f"{self.server.base_url}/")
        self.driver.execute_async_script(
            """
            const [base, user, done] = arguments;
            const form = (d) => Object.entries(d).map(([k,v]) =>
                encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');
            const opt = (b) => ({method:'POST', headers:
                {'Content-Type':'application/x-www-form-urlencoded'}, body:b});
            (async () => {
                await fetch(base+'/register', opt(form({email:user, pass:'pw123'})));
                await fetch(base+'/auth', opt(form({email:user, pass:'pw123'})));
                done(true);
            })();
            """,
            self.server.base_url, user,
        )
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1.5)

    def _wait_page(self, timeout=25):
        end = time.time() + timeout
        while time.time() < end:
            if self.driver.execute_script(
                "return document.querySelectorAll('.pdf-page-canvas').length") >= 1:
                return True
            time.sleep(0.5)
        return False

    def test_paginated_thumbnail_navigation(self):
        self._login_and_open_annotate()
        assert self._wait_page()
        info = self.driver.execute_script(
            """return {thumbs: document.querySelectorAll('.pdf-thumb').length,
                       sidebar: !!document.querySelector('.pdf-thumbnail-sidebar')};""")
        assert info["sidebar"] and info["thumbs"] == 3, info
        # Navigate to page 3 via its thumbnail.
        self.driver.execute_script(
            "document.querySelector('.pdf-thumb[data-page=\"3\"]').click();")
        time.sleep(1.2)
        cur = self.driver.execute_script(
            "return document.querySelector('.pdf-page-container').dataset.page")
        assert cur == "3", cur

    def test_pin_navigate_cross_page_link_with_offpage_stub(self):
        self._login_and_open_annotate()
        assert self._wait_page()

        result = self.driver.execute_async_script(
            """
            const done = arguments[arguments.length-1];
            const m = document.querySelector('.pdf-link-mode')._pdfLinkMode;
            // Anchors on different pages; page 3 isn't rendered yet.
            m.addAnchor({id:'src1', kind:'text', page:1, label:'claim',
                         start:5, end:20, bbox:[0.1,0.2,0.4,0.05]}, false);
            m.addAnchor({id:'tgt3', kind:'region', page:3, label:'figure',
                         start:0, end:0, bbox:[0.1,0.4,0.4,0.2]}, false);
            m.currentLinkType = 'same_as';   // undirected, no label constraints
            m.linkModeOn = true;
            // Pin source on page 1.
            m._onAnchorClick('src1');
            // Navigate to page 3, then select the target there.
            (async () => {
                await m.goToPage(3);
                m._onAnchorClick('tgt3');
                // give arcs a tick
                setTimeout(() => {
                    done({links: m.links.length,
                          linkIds: m.links[0] && m.links[0].span_ids,
                          stubs: document.querySelectorAll('.pdf-arc-stub').length,
                          renderedPage: document.querySelector('.pdf-page-container').dataset.page});
                }, 300);
            })();
            """
        )
        assert result["links"] == 1, result
        assert set(result["linkIds"]) == {"src1", "tgt3"}, result
        assert result["renderedPage"] == "3", result
        # Source (page 1) is off-page -> an off-page stub is drawn.
        assert result["stubs"] >= 1, result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
