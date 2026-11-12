"""
Server-side places where item data, crowd parameters or media reached a page
as live markup.

Each test feeds the real renderer or route a hostile value and parses what it
produced. The display container is emitted with ``{{ display_html | safe }}``,
so anything a display writes unescaped runs on every annotator's page.
"""

import json
import os
from html.parser import HTMLParser
from unittest.mock import patch

import pytest

from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

ATTR_BREAK = 'x" onmouseover="window.__pwned=1'
TAG = '<img src=x onerror="window.__pwned=1">'


class _Elements(HTMLParser):
    """Every start tag and its attributes, as a browser would split them."""

    def __init__(self):
        super().__init__()
        self.tags = []

        self.script_text = ""
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        self._in_script = tag == "script"

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.script_text += data


def _elements(markup):
    p = _Elements()
    p.feed(markup)
    p.close()
    return p.tags


def _script_text(markup):
    p = _Elements()
    p.feed(markup)
    p.close()
    return p.script_text


def _handler_attrs(markup):
    return [(tag, name) for tag, attrs in _elements(markup)
            for name in attrs if name.lower().startswith("on")]


def _render(field_type, field, data):
    from potato.server_utils.displays.registry import display_registry
    return display_registry.render(field_type, field, data)


# ---------------------------------------------------------------------------
# Display container data-* attributes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field_type", ["image", "video", "audio"])
def test_media_url_in_container_attribute_is_escaped(field_type):
    url = "https://example.org/a.png" + '" onmouseover="window.__pwned=1'
    page = _render(field_type, {"key": "m", "type": field_type}, url)
    assert _handler_attrs(page) == []
    containers = [a for t, a in _elements(page) if "data-source-url" in a]
    assert containers and containers[0]["data-source-url"] == url


def test_code_language_from_config_cannot_leave_its_attribute():
    page = _render("code", {"key": "c", "type": "code",
                            "display_options": {"language": 'x"><svg onload="window.__pwned=1">'}},
                   "print(1)")
    assert _handler_attrs(page) == []


def test_code_language_from_item_cannot_leave_its_attribute():
    data = {"text": "print(1)", "metadata": {"language": 'py" onmouseover="window.__pwned=1'}}
    page = _render("code", {"key": "c", "type": "code"}, data)
    assert _handler_attrs(page) == []


# ---------------------------------------------------------------------------
# rendered_html supplied by an item
# ---------------------------------------------------------------------------

HOSTILE_RENDERED = ('<div class="row" data-line="3">ok</div>'
                    '<img src=x onerror="window.__pwned=1">'
                    '<script>window.__pwned=1</script>'
                    '<a href="java\tscript:alert(1)">l</a>'
                    '<svg onload="window.__pwned=1"></svg>')


@pytest.mark.parametrize("field_type", ["code", "spreadsheet", "pdf"])
def test_item_rendered_html_loses_active_content_keeps_structure(field_type):
    page = _render(field_type, {"key": "f", "type": field_type},
                   {"rendered_html": HOSTILE_RENDERED, "text": "ok"})
    assert _handler_attrs(page) == []
    # The display's own copy-button SVG may be there; the item's script not.
    assert "__pwned" not in _script_text(page)
    assert not any("javascript" in a.get("href", "").replace("\t", "")
                   for t, a in _elements(page))
    # Structure and the data-* attributes these displays position by survive.
    assert any(a.get("data-line") == "3" for t, a in _elements(page))


def test_pdf_page_metadata_is_escaped():
    from potato.server_utils.displays.pdf_display import PDFDisplay
    page = PDFDisplay()._render_extracted(
        {"text": "t", "metadata": {"total_pages": TAG}}, {"key": "p"}, {})
    assert ("img", {"src": "x", "onerror": "window.__pwned=1"}) not in _elements(page)
    assert _handler_attrs(page) == []


def test_document_metadata_footer_is_escaped():
    page = _render("document", {"key": "d", "type": "document",
                                "display_options": {"show_metadata": True}},
                   {"rendered_html": "<p>x</p>",
                    "metadata": {"line_count": TAG, "format": TAG, "char_count": TAG}})
    assert _handler_attrs(page) == []


# ---------------------------------------------------------------------------
# strip_active_content and sanitize_html
# ---------------------------------------------------------------------------

def test_strip_active_content():
    from potato.server_utils.html_sanitizer import strip_active_content
    out = strip_active_content(HOSTILE_RENDERED + '<iframe srcdoc="x"></iframe>'
                               '<p style="color:red" onclick="1">p</p>')
    tags = [t for t, _ in _elements(out)]
    assert _handler_attrs(out) == []
    assert not {"script", "svg", "iframe"} & set(tags)
    assert '<div class="row" data-line="3">ok</div>' in out
    assert "<p" in out and "p</p>" in out


@pytest.mark.parametrize("href", [
    "java\tscript:alert(1)", "java\nscript:alert(1)", "java\rscript:alert(1)",
    "\x01javascript:alert(1)", " javascript:alert(1)",
])
def test_sanitizer_blocks_scheme_split_by_whitespace(href):
    from potato.server_utils.html_sanitizer import sanitize_html
    out = str(sanitize_html(f'<a href="{href}">x</a>'))
    hrefs = [a.get("href", "") for t, a in _elements(out) if t == "a"]
    assert all("script" not in "".join(h.split()).lower() for h in hrefs), out


def test_sanitizer_keeps_ordinary_links():
    from potato.server_utils.html_sanitizer import sanitize_html
    out = str(sanitize_html('<a href="https://example.org/x">x</a><a href="/rel">y</a>'))
    hrefs = [a.get("href") for t, a in _elements(out) if t == "a"]
    assert hrefs == ["https://example.org/x", "/rel"]


# ---------------------------------------------------------------------------
# Instance display error text and protein insertion codes
# ---------------------------------------------------------------------------

def test_display_error_message_is_escaped():
    from potato.server_utils.displays.registry import display_registry
    from potato.server_utils.instance_display import InstanceDisplayRenderer

    config = {"instance_display": {"fields": [{"key": "t", "type": "text"}]}}
    renderer = InstanceDisplayRenderer(config)
    with patch.object(display_registry, "render", side_effect=ValueError(TAG)):
        page = renderer.render({"t": "hello"})
    assert _handler_attrs(page) == []
    assert "&lt;img" in page


def test_protein_insertion_code_is_escaped():
    from potato.server_utils.displays.registry import display_registry
    root = create_test_directory("untrusted_markup_protein")
    try:
        os.makedirs(os.path.join(root, "media"), exist_ok=True)
        with open(os.path.join(root, "media", "x.cif"), "w") as f:
            f.write("data_x\nloop_\n_atom_site.group_PDB\n_atom_site.label_atom_id\n"
                    "_atom_site.label_comp_id\n_atom_site.auth_asym_id\n"
                    "_atom_site.auth_seq_id\n_atom_site.pdbx_PDB_ins_code\n"
                    "_atom_site.B_iso_or_equiv\n_atom_site.pdbx_PDB_model_num\n"
                    'ATOM CA GLY A 5 \'"><img/src=x/onerror=window.__pwned=1>\' 80 1\n#\n')
        cfg = {"task_dir": root, "media_directory": "media"}
        with patch.dict("potato.server_utils.config_module.config", cfg, clear=False):
            page = display_registry.render(
                "protein_structure", {"key": "s", "type": "protein_structure"}, "x.cif")
        assert "pv-res" in page                    # the residue table rendered
        assert _handler_attrs(page) == []
        assert not any(t == "img" for t, _ in _elements(page))
    finally:
        cleanup_test_directory(root)


# ---------------------------------------------------------------------------
# MTurk turkSubmitTo becomes a form action
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "javascript:alert(document.domain)//", "JavaScript:alert(1)", "data:text/html,x",
    "//evil.example", "not a url",
    # Only MTurk's own hosts: anything else is an open redirect for the worker.
    "https://evil.example", "http://www.mturk.com", "https://www.mturk.com.evil.example",
    "https://user@www.mturk.com", "https://www.mturk.com:8443",
])
def test_turk_submit_to_must_be_an_mturk_host(value):
    from potato.crowdsourcing.providers.mturk import normalize_submit_url
    assert normalize_submit_url(value) is None


def test_turk_submit_to_real_values_still_work():
    from potato.crowdsourcing.providers.mturk import normalize_submit_url
    assert normalize_submit_url("https://www.mturk.com") == "https://www.mturk.com/mturk/externalSubmit"
    assert (normalize_submit_url("https://workersandbox.mturk.com/mturk/externalSubmit")
            == "https://workersandbox.mturk.com/mturk/externalSubmit")


def test_mturk_completion_with_hostile_submit_url_offers_no_form():
    from potato.crowdsourcing.base import ParticipantIdentity
    from potato.crowdsourcing.providers.mturk import MTurkProvider
    provider = MTurkProvider.__new__(MTurkProvider)
    provider.config = {"completion": {"code": "ABC"}}
    identity = ParticipantIdentity(worker_id="w", session_id="A1",
                                   extra={"turkSubmitTo": "javascript:alert(1)//"})
    with patch.object(MTurkProvider, "platform_label", return_value="MTurk"), \
            patch.object(MTurkProvider, "_code_for_outcome", return_value="ABC"):
        action = provider.completion_action(identity, "complete")
    assert action.kind != "post_form"
    assert not action.form_action


# ---------------------------------------------------------------------------
# /media/proxy passthrough of an SVG
# ---------------------------------------------------------------------------

def test_media_proxy_svg_is_sandboxed():
    from flask import Flask
    from potato.media import routes as media_routes

    root = create_test_directory("untrusted_markup_media_proxy")
    saved = media_routes._registered_config
    try:
        os.makedirs(os.path.join(root, "media"), exist_ok=True)
        with open(os.path.join(root, "media", "x.svg"), "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        app = Flask(__name__)
        media_routes.register_media_routes(app, {"task_dir": root, "media_directory": "media"})
        resp = app.test_client().get("/media/proxy/x.svg")
        assert resp.status_code == 200
        assert resp.headers.get("Content-Security-Policy") == "sandbox"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        resp.close()
    finally:
        media_routes._registered_config = saved
        cleanup_test_directory(root)


# ---------------------------------------------------------------------------
# Solo-mode label buttons: a label inside an inline handler
# ---------------------------------------------------------------------------

def test_solo_label_buttons_pass_the_label_as_a_js_string():
    from flask import Flask, render_template
    from potato.solo_mode.routes import solo_mode_bp

    label = "it's\"); window.__pwned=1; //"
    templates = os.path.join(os.path.dirname(__file__), "..", "..", "potato", "templates")
    app = Flask(__name__, template_folder=os.path.abspath(templates))
    app.register_blueprint(solo_mode_bp)
    with app.test_request_context():
        page = render_template("solo/review.html", current_instance={
            "id": "1", "text": "t", "llm_label": "a", "confidence": 0.4},
            labels=[label], phase="review", instances=[])
    buttons = [a for t, a in _elements(page)
               if t == "button" and a.get("onclick", "").startswith("selectCorrection(")]
    assert len(buttons) == 1
    handler = buttons[0]["onclick"]
    assert handler.startswith("selectCorrection(") and handler.endswith(")")
    assert json.loads(handler[len("selectCorrection("):-1]) == label


def test_solo_disagreement_labels_are_js_strings():
    import re
    from flask import Flask, render_template
    from potato.solo_mode.routes import solo_mode_bp

    llm_label = "x'; window.__pwned=1; //\\"
    other = "it's\"); window.__pwned=1; //"
    templates = os.path.join(os.path.dirname(__file__), "..", "..", "potato", "templates")
    app = Flask(__name__, template_folder=os.path.abspath(templates))
    app.register_blueprint(solo_mode_bp)
    with app.test_request_context():
        page = render_template("solo/disagreement.html", disagreement={
            "id": "d1", "text": "t", "human_label": "a", "llm_label": llm_label,
            "pending_count": 1}, labels=["a", llm_label, other], phase="review")
    # The two server-filled assignments (a third assigns a JS variable).
    assigned = re.findall(r"getElementById\('resolution-value'\)\.value = (.*);",
                          _script_text(page))
    assert [json.loads(v) for v in assigned if v != "label"] == ["a", llm_label]
    buttons = [a["onclick"] for t, a in _elements(page)
               if t == "button" and a.get("onclick", "").startswith("selectOtherLabel(")]
    assert [json.loads(h[len("selectOtherLabel("):-1]) for h in buttons] == [other]
