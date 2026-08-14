"""
Third-party frontend assets must be vendored, not loaded from a CDN.

Several research groups deploy Potato air-gapped. A CDN dependency is not a slow
page there -- it is a missing feature, and for fabric.js it was the *whole* of
image annotation, since the canvas never initializes without it.

This test does not pretend the migration is finished. It pins the assets that
are still external in an explicit allowlist, so each remaining one is a known,
named gap rather than an invisible one, and blocks any NEW external dependency
from appearing.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "potato" / "templates"
MAIN_TEMPLATE = TEMPLATE_DIR / "base_template_v2.html"
VENDOR_DIR = REPO_ROOT / "potato" / "static" / "vendor"

#: External assets base_template_v2.html is still allowed to load.
#:
#: Every entry is tracked work, not an exemption. Bootstrap's CSS and Font
#: Awesome are ALREADY vendored (for adjudication.html) but at different
#: versions than the CDN copies here, so switching is a version bump needing a
#: full-app regression pass -- and Bootstrap's JS bundle is not vendored at all.
#: See docs/deployment/air_gap.md.
ALLOWED_EXTERNAL = {
    "code.jquery.com": "jQuery 3.6.0 — used by span annotation; not yet vendored",
    "cdn.jsdelivr.net": "Bootstrap 5.1.3 CSS+JS — vendored copy is 5.3.3, needs a version bump",
    "cdnjs.cloudflare.com": "Font Awesome 6.0.0 — vendored copy is 6.7.2, needs the webfonts moved",
}

ASSET_PATTERN = re.compile(
    r'(?:<script[^>]+src|<link[^>]+href)\s*=\s*["\'](https?://[^"\']+)["\']',
    re.IGNORECASE,
)


def _external_assets(text: str):
    return ASSET_PATTERN.findall(text)


def _host(url: str) -> str:
    return url.split("//", 1)[1].split("/", 1)[0]


class TestNoNewExternalAssets:
    @pytest.fixture(scope="class")
    def template_text(self):
        return MAIN_TEMPLATE.read_text(encoding="utf-8")

    def test_every_external_asset_is_explicitly_allowed(self, template_text):
        """
        A new CDN dependency fails here. Vendor it with
        `python scripts/vendor_assets.py`, or add it to ALLOWED_EXTERNAL with a
        note saying why it cannot be vendored yet.
        """
        unexpected = [
            url for url in _external_assets(template_text)
            if _host(url) not in ALLOWED_EXTERNAL
        ]
        assert not unexpected, (
            f"New external asset(s) in base_template_v2.html: {unexpected}. "
            f"Vendor them into potato/static/vendor/ (see scripts/vendor_assets.py) "
            f"rather than adding another air-gap blocker."
        )

    def test_the_allowlist_does_not_rot(self, template_text):
        """
        An allowlist entry that no longer matches anything is stale and should
        be deleted, or it quietly permits a future dependency on that host.
        """
        hosts_in_use = {_host(url) for url in _external_assets(template_text)}
        stale = set(ALLOWED_EXTERNAL) - hosts_in_use
        assert not stale, (
            f"ALLOWED_EXTERNAL lists host(s) the template no longer loads: {stale}. "
            f"Remove them so the allowlist keeps meaning something."
        )


class TestFabricIsVendored:
    """
    Fabric is the vision-critical case: no fabric, no image annotation at all.
    """

    @pytest.fixture(scope="class")
    def template_text(self):
        return MAIN_TEMPLATE.read_text(encoding="utf-8")

    def test_fabric_is_not_loaded_from_a_cdn(self, template_text):
        external = [u for u in _external_assets(template_text) if "fabric" in u.lower()]
        assert not external, f"fabric.js is still loaded externally: {external}"

    def test_fabric_is_referenced_from_vendor(self, template_text):
        assert "vendor/fabric-" in template_text, (
            "base_template_v2.html should load fabric from static/vendor/")

    def test_the_vendored_file_exists_and_is_plausible(self):
        matches = list(VENDOR_DIR.glob("fabric-*.min.js"))
        assert matches, f"No vendored fabric build in {VENDOR_DIR}"

        data = matches[0].read_bytes()
        # A truncated or error-page download would sail past a mere existence
        # check and fail only in the browser.
        assert len(data) > 100_000, f"{matches[0].name} is implausibly small ({len(data)} bytes)"
        assert b"fabric" in data[:200], f"{matches[0].name} does not look like a fabric bundle"

    def test_the_template_points_at_a_file_that_exists(self, template_text):
        referenced = re.findall(r"vendor/(fabric-[^'\"]+\.js)", template_text)
        assert referenced, "Could not find the vendored fabric reference"
        for name in referenced:
            assert (VENDOR_DIR / name).exists(), (
                f"base_template_v2.html loads vendor/{name}, which does not exist")


class TestVendorManifest:
    """scripts/vendor_assets.py is the record of what is vendored and why."""

    def test_every_vendored_asset_the_manifest_pins_is_present(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "vendor_assets", REPO_ROOT / "scripts" / "vendor_assets.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        missing = [a.name for a in module.ASSETS if not a.path.exists()]
        assert not missing, (
            f"Manifest pins assets that are not committed: {missing}. "
            f"Run: python scripts/vendor_assets.py")

    def test_pinned_hashes_match_the_committed_bytes(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "vendor_assets", REPO_ROOT / "scripts" / "vendor_assets.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        bad = []
        for asset in module.ASSETS:
            if not asset.sri or not asset.path.exists():
                continue
            ok, detail = module.verify(asset, asset.path.read_bytes())
            if not ok:
                bad.append(f"{asset.name}: {detail}")

        assert not bad, (
            "Committed vendor file(s) do not match their pinned SRI:\n" + "\n".join(bad))
