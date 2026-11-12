"""Audit 97 V12: a vendored bundle ships the licence texts its parts need.

geotiff.js bundles Esri's LERC decoder (Apache-2.0) and igv.js bundles
DOMPurify (Apache-2.0 or MPL-2.0), but the LICENSE beside each held only the
MIT text of the outer project. Apache-2.0 section 4(a) and MPL-2.0 section 3.2
ask for the licence text to travel with the code. Any bundle whose preserved
comments name one of those licences needs the full text in a file beside it.
"""

import re
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parents[2] / "potato" / "static" / "vendor"

#: licence named in a header -> a line only its full text contains
FULL_TEXT = {
    "Apache": "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
    "Mozilla Public License": "Mozilla Public License Version 2.0",
}
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _named_licences(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    named = set()
    for comment in _COMMENT.findall(text):
        if len(comment) > 5000:          # a code chunk between stray /* */, not a header
            continue
        if re.search(r"Apache[ -](License|license|2\.0)", comment):
            named.add("Apache")
        if re.search(r"Mozilla Public License|MPL-2\.0", comment):
            named.add("Mozilla Public License")
    return named


def _bundles():
    return sorted(p for p in VENDOR.rglob("*")
                  if p.is_file() and p.suffix in (".js", ".mjs", ".css") and _named_licences(p))


def test_the_known_bundles_are_found():
    names = {p.relative_to(VENDOR).as_posix() for p in _bundles()}
    assert {"geotiff-3.0.5/geotiff.js", "igv-3.8.9/igv.min.js", "pdfjs/pdf.min.js"} <= names


@pytest.mark.parametrize("bundle", _bundles(), ids=lambda p: p.relative_to(VENDOR).as_posix())
def test_full_licence_text_sits_beside_the_bundle(bundle):
    beside = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                       for p in bundle.parent.iterdir()
                       if p.is_file() and p.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")))
    for licence in sorted(_named_licences(bundle)):
        assert FULL_TEXT[licence] in beside, (
            f"{bundle.relative_to(VENDOR)} names the {licence} licence, but no LICENSE* file "
            "beside it holds the full text")
