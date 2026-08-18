"""
Every asset a template references must exist locally.

The existing CDN guard (``test_no_new_cdn_assets.py``) answers "does this page
reach out to the internet". This file answers the other half — "is what it
reaches for actually here" — because the two failure modes are different and
only the first was covered.

A `url_for('static', filename='deepzoom-viewer.js')` naming a file that is not
in the tree does not fail at render. It emits a URL, the browser requests it,
gets a 404, and the feature is silently absent. Air-gapped or not, that is a
broken page; on an air-gapped machine it is indistinguishable from the CDN
problem, which is how a missing vendored file gets misdiagnosed for a week.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "potato" / "templates"
STATIC_DIR = REPO_ROOT / "potato" / "static"

#: `{{ url_for('static', filename='x/y.js') }}`, in either quote style.
STATIC_REF = re.compile(
    r"url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]")

#: A src/href pointing straight at /static/... without url_for.
LITERAL_STATIC = re.compile(r"""(?:src|href)\s*=\s*["']/static/([^"'?#]+)""")

#: Referenced with a Jinja expression inside the filename, so the concrete path
#: is only known at render time and cannot be checked statically. Each entry is
#: a deliberate exemption, not an oversight.
DYNAMIC_EXEMPT = ("{{", "{%")


def _templates():
    """
    Source templates only.

    `potato/templates/generated/` holds per-project build output — it is
    gitignored, regenerated on demand, and currently ~1200 files carrying
    references to assets deleted in Wave 0.1. Auditing build output for the
    state of the source tree would make this test a report on how stale
    somebody's local cache is.
    """
    return [t for t in sorted(TEMPLATE_DIR.rglob("*.html"))
            if "generated" not in t.parts]


def _referenced_static(text):
    """Every static path a template names, excluding computed ones."""
    found = set(STATIC_REF.findall(text)) | set(LITERAL_STATIC.findall(text))
    return {p for p in found if not any(marker in p for marker in DYNAMIC_EXEMPT)}


class TestEveryReferencedAssetExists:
    def test_no_template_references_a_missing_static_file(self):
        missing = []
        for template in _templates():
            text = template.read_text(encoding="utf-8")
            for path in sorted(_referenced_static(text)):
                if not (STATIC_DIR / path).exists():
                    missing.append(
                        f"{template.relative_to(REPO_ROOT)} -> static/{path}")
        assert not missing, (
            "Template(s) reference static files that are not in the tree. The "
            "browser gets a 404 and the feature is silently absent:\n  "
            + "\n  ".join(missing))

    def test_the_check_actually_finds_references(self):
        """
        A regex that matched nothing would make the test above vacuous. The
        main template loads dozens of assets; if this drops to zero, the
        pattern has stopped matching and the guard is off.
        """
        text = (TEMPLATE_DIR / "base_template_v2.html").read_text(encoding="utf-8")
        assert len(_referenced_static(text)) > 20

    def test_a_fabricated_reference_would_be_caught(self):
        """Proof the guard is load-bearing rather than always-green."""
        fake = "<script src=\"{{ url_for('static', filename='not-a-file.js') }}\">"
        assert _referenced_static(fake) == {"not-a-file.js"}
        assert not (STATIC_DIR / "not-a-file.js").exists()


class TestVendoredLibrariesAreWhole:
    """
    A truncated download or a saved error page passes an existence check and
    fails only in the browser. These files are committed, so a bad one ships.
    """

    VENDOR = STATIC_DIR / "vendor"

    @pytest.mark.parametrize("pattern,minimum,marker", [
        ("fabric-*.min.js", 100_000, b"fabric"),
        ("three-*.min.js", 300_000, b"THREE"),
        ("openseadragon-*.min.js", 100_000, b"OpenSeadragon"),
    ])
    def test_the_bundle_is_plausible(self, pattern, minimum, marker):
        matches = list(self.VENDOR.glob(pattern))
        assert matches, f"No vendored build matching {pattern} in {self.VENDOR}"
        data = matches[0].read_bytes()
        assert len(data) > minimum, (
            f"{matches[0].name} is implausibly small ({len(data)} bytes) — a "
            f"truncated download or an error page")
        assert marker in data[:4000], (
            f"{matches[0].name} does not look like the library it is named for")


class TestNoNewExternalHostAnywhere:
    """
    The CDN guard covers base_template_v2.html. Every other template is checked
    here, because an external asset added to the adjudication page or an admin
    dashboard breaks that page air-gapped just as thoroughly.
    """

    ASSET = re.compile(
        r'(?:<script[^>]+src|<link[^>]+href)\s*=\s*["\'](https?://[^"\']+)["\']',
        re.IGNORECASE)

    #: Empty. Every asset in every source template is served from
    #: potato/static/vendor/, so an air-gapped deployment loses nothing. An
    #: entry here is tracked work with a named consequence in
    #: docs/deployment/air_gap.md -- never a standing exemption.
    ALLOWED = {}

    def test_no_template_loads_from_an_unlisted_host(self):
        offenders = []
        for template in _templates():
            for url in self.ASSET.findall(template.read_text(encoding="utf-8")):
                host = url.split("//", 1)[1].split("/", 1)[0]
                if host not in self.ALLOWED:
                    offenders.append(f"{template.relative_to(REPO_ROOT)}: {url}")
        assert not offenders, (
            "New external asset host(s). Vendor them with "
            "`python scripts/vendor_assets.py` rather than adding another "
            "air-gap blocker:\n  " + "\n  ".join(offenders))

    def test_the_allowlist_is_not_carrying_dead_entries(self):
        """
        An entry nothing uses silently permits a future dependency on that
        host, which is the opposite of what an allowlist is for.
        """
        used = set()
        for template in _templates():
            for url in self.ASSET.findall(template.read_text(encoding="utf-8")):
                used.add(url.split("//", 1)[1].split("/", 1)[0])
        stale = set(self.ALLOWED) - used
        assert not stale, (
            f"These hosts are allowed but unused: {sorted(stale)}. Remove them.")

    def test_the_login_pages_do_not_call_a_third_party(self):
        """
        `id_login_home.html` and `signup.html` carried a favicon from
        colorlib.com — the site the login template was adapted from. A
        decorative icon is not worth a request to a third party from the page
        where users type their credentials, and it broke air-gapped alongside
        everything else.
        """
        for name in ("id_login_home.html", "signup.html"):
            text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
            assert "colorlib.com" not in text, (
                f"{name} loads an asset from colorlib.com again")
