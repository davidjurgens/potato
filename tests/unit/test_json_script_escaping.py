"""
Item data in the annotation page's ``<script type="application/json">`` blocks.

render_page_with_annotations() puts every str/int/float/bool/list field of
the item into ``var_elems["instance_data"]``. It used to emit them with plain
json.dumps, which does not escape ``</script>``: a field holding a closing
script tag ended the element and the rest of the value ran as markup on
every annotator's page. The HTML sanitizer only covers the displayed text.
"""

import json
from html.parser import HTMLParser

import pytest

from potato.server_utils.json import script_safe_json

PAYLOADS = [
    "</script><script>window.__pwned=1</script>",
    "</SCRIPT ><img src=x onerror=window.__pwned=1>",
    "<!--<script>",
    "a & b < c > d",
    "   line separators",
    "plain",
]


class _ScriptCollector(HTMLParser):
    """Collect each <script> element's id and text, as a browser splits them."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.other_tags = []
        self._open = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._open = [dict(attrs).get("id"), ""]
        else:
            self.other_tags.append(tag)

    def handle_data(self, data):
        if self._open is not None:
            self._open[1] += data

    def handle_endtag(self, tag):
        if tag == "script" and self._open is not None:
            self.scripts.append(tuple(self._open))
            self._open = None


def _parse(html):
    p = _ScriptCollector()
    p.feed(html)
    p.close()
    return p


@pytest.mark.parametrize("payload", PAYLOADS)
def test_script_safe_json_has_no_markup_characters(payload):
    out = script_safe_json({"text": payload, "items": [payload]})
    for ch in "<>&  ":
        assert ch not in out
    assert json.loads(out) == {"text": payload, "items": [payload]}


def test_json_script_elements_one_element_per_key_and_round_trips():
    from potato.flask_server import _json_script_elements

    values = {
        "instance": {"text": PAYLOADS[0]},
        "instance_data": {"id": "1", "text": PAYLOADS[0], "alt": PAYLOADS[1],
                          "notes": PAYLOADS[2:], "n": 3, "ok": True},
        "suggestions": [],
    }
    html = _json_script_elements(values)

    # The only closing tags are the ones the helper writes itself.
    assert html.lower().count("</script") == len(values)
    parsed = _parse(html)
    assert parsed.other_tags == []          # the <img> payload stayed text
    assert [sid for sid, _ in parsed.scripts] == list(values)
    for sid, text in parsed.scripts:
        assert json.loads(text) == values[sid]


def test_json_script_elements_escapes_the_id():
    from potato.flask_server import _json_script_elements

    html = _json_script_elements({'x" onload="1': 1})
    parsed = _parse(html)
    assert parsed.scripts == [('x" onload="1', " 1 ")]
