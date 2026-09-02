"""The image-annotation bootstrap must not take `data-image-url` on faith.

base_template_v2.html stamps `data-image-url` with the rendered instance whether
or not that instance is a URL. On an annotation page it is one, because
`text_key` points at the image field. On a phase page -- training, consent, a
survey -- `#text-content` is still rendered and can hold the practice question's
prose, and the bootstrap's first discovery method took it, so the canvas fetched
a sentence and then blamed the URL or CORS.

Method 1 now shape-checks its candidate and falls through to the `<img>` and
`source_field` methods that already worked.
"""

import re

import pytest

from potato.server_utils.schemas.image_annotation import (
    generate_image_annotation_layout,
)


SCHEME = {
    "annotation_type": "image_annotation",
    "name": "object_detection",
    "description": "Draw boxes around objects.",
    "tools": ["bbox"],
    "labels": [{"name": "person", "color": "#FF6B6B"}],
}


@pytest.fixture(scope="module")
def bootstrap_js():
    html, _ = generate_image_annotation_layout(dict(SCHEME))
    return html


class TestGuardIsPresent:
    def test_declared_url_goes_through_the_shape_check(self, bootstrap_js):
        assert "function looksLikeImageUrl(value)" in bootstrap_js
        assert "if (looksLikeImageUrl(declaredUrl))" in bootstrap_js

    def test_a_rejected_candidate_is_reported_not_swallowed(self, bootstrap_js):
        assert "Ignoring non-URL data-image-url" in bootstrap_js

    def test_no_url_says_so_on_the_canvas(self, bootstrap_js):
        """A blank canvas reads as a broken tool. Say what happened."""
        assert "_showCanvasMessage" in bootstrap_js
        assert "No image URL for this item" in bootstrap_js

    def test_regex_escapes_survive_the_f_string(self, bootstrap_js):
        """The generator is an f-string, so `\\s` has to be written `\\\\s`."""
        assert r"/\s/.test(v)" in bootstrap_js
        assert r"https?:\/\/" in bootstrap_js


class TestShapeCheckSemantics:
    """Run the emitted predicate's rules against real candidates.

    The function itself is JavaScript; these mirror its three branches so a
    change to either side shows up as a disagreement rather than as a silent
    behaviour change in the browser.
    """

    SCHEME_PREFIXES = re.compile(r"^(https?://|data:image/|blob:|file://)", re.I)
    EXTENSION = re.compile(
        r"^[./]?[^?#]*\.(jpg|jpeg|png|gif|webp|svg|bmp|tif|tiff|avif)(\?|#|$)", re.I
    )

    def _accepts(self, value):
        if not value:
            return False
        v = str(value).strip()
        if not v or re.search(r"\s", v) or "<" in v:
            return False
        if self.SCHEME_PREFIXES.match(v):
            return True
        return bool(self.EXTENSION.match(v))

    @pytest.mark.parametrize("value", [
        "https://picsum.photos/id/237/800/600",
        "http://example.com/a.png",
        "data:image/png;base64,iVBORw0KGgo=",
        "blob:http://localhost/abc-123",
        "/static/img/chart.png",
        "./data/images/chart.jpeg",
        "data/images/chart.WEBP",
    ])
    def test_accepted(self, value):
        assert self._accepts(value) is True

    @pytest.mark.parametrize("value", [
        "Unemployment rate, 2019-2024. The y-axis starts at 5.0 rather than zero.",
        "Is this image blurry?",
        "",
        "   ",
        None,
        "<p>Some rendered HTML</p>",
        "chart",
        "a summary of the chart.png contents",  # has whitespace
    ])
    def test_rejected(self, value):
        assert self._accepts(value) is False

    def test_a_url_with_a_query_string_is_accepted(self):
        assert self._accepts("/img/chart.png?v=2") is True
