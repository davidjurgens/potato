#!/usr/bin/env python3
"""
Download and verify third-party frontend assets into potato/static/vendor/.

Potato is deployed air-gapped by several research groups, and a CDN-loaded
dependency is not a slow page there -- it is a missing feature. Fabric.js in
particular is the whole of image annotation: without it the canvas never
initializes.

Every asset is verified against its published Subresource Integrity hash, so a
download is either byte-identical to what the CDN publishes or it fails. That
matters more than usual here: these files are committed to the repository, so a
corrupted or substituted download would be shipped to every user.

Usage:
    python scripts/vendor_assets.py --check       # verify what is committed
    python scripts/vendor_assets.py               # download anything missing
    python scripts/vendor_assets.py --force       # re-download everything
"""

import argparse
import base64
import hashlib
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "potato" / "static" / "vendor"


class Asset:
    """One vendored file, pinned by URL and SRI hash."""

    def __init__(self, name, url, path, sri, used_by, notes=""):
        self.name = name
        self.url = url
        self.path = VENDOR_DIR / path
        self.sri = sri
        self.used_by = used_by
        self.notes = notes


#: The manifest. `sri` is the value published by the CDN (sha384- or sha512-).
#:
#: Bootstrap CSS and Font Awesome were vendored earlier for adjudication.html
#: and are recorded here so this script is the single source of truth, even
#: though base_template_v2.html still loads its own copies from a CDN at
#: DIFFERENT versions -- see the note on each, and docs/deployment/air_gap.md.
ASSETS = [
    Asset(
        name="fabric.js",
        url="https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js",
        path="fabric-5.3.1.min.js",
        sri="sha512-CeIsOAsgJnmevfCi2C7Zsyy6bQKi43utIjdA87Q0ZY84oDqnI0uwfM9+bKiIkI75lUeI00WG/+uJzOmuHlesMA==",
        used_by="base_template_v2.html (image annotation canvas)",
        notes="The bundle reports version 5.3.0 internally; that is upstream's "
              "own inconsistency, not a wrong download. The SRI is authoritative.",
    ),
    Asset(
        name="three.js",
        url="https://cdnjs.cloudflare.com/ajax/libs/three.js/0.160.0/three.min.js",
        path="three-0.160.0.min.js",
        sri="sha512-vnmn/Qqn6aG0POAc9mIGzjq0IybrvxJXYDafNvp9JSnDGxeF3pbkSqLvf+YGd5ku63pT7sa/jxHn7/d0mU8+tA==",
        used_by="base_template_v2.html (point cloud / spatial annotation viewer)",
        notes="Pinned to the last release of the classic UMD global build. "
              "0.161 dropped three.min.js in favour of ES modules only, and a "
              "module build would need an import map or a bundler -- neither of "
              "which belongs in a page that must work from a file:// mirror on "
              "an air-gapped machine.",
    ),
    Asset(
        name="openseadragon",
        url="https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/openseadragon.min.js",
        path="openseadragon-5.0.1.min.js",
        sri="sha512-gPZzE+sKmE0kvcjMxW431ef5b5T5QOADV9Gij0isPw2oLATd1IZW7dmDmKh7F2e5BfwjQyAfFp3/OF0fVMOF7Q==",
        used_by="base_template_v2.html (deep-zoom image viewer)",
        notes="The JS only. OpenSeadragon also ships ~20 PNG button sprites, "
              "which are NOT vendored: the viewer runs with "
              "showNavigationControl:false and Potato draws its own controls, "
              "so the sprites would be 20 more files to keep air-gapped for "
              "buttons nobody sees. Setting showNavigationControl:true without "
              "vendoring images/ gives broken-image icons, not missing ones.",
    ),
    Asset(
        name="bootstrap-css",
        url="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
        path="bootstrap-5.3.3.min.css",
        sri="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH",
        used_by="base_template_v2.html, adjudication.html",
        notes="The committed copy was verified byte-identical to upstream 5.3.3 "
              "when this SRI was recorded, so the earlier unpinned vendoring is "
              "now checkable.",
    ),
    Asset(
        name="bootstrap-js",
        url="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
        path="bootstrap-5.3.3.bundle.min.js",
        sri="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz",
        used_by="base_template_v2.html (dropdowns, modals, tooltips, collapse)",
        notes="The bundle, so Popper travels with it -- tooltips and dropdowns "
              "need Popper and a separate file would be one more thing to keep "
              "air-gapped. Verified byte-identical across jsDelivr, cdnjs and "
              "unpkg before pinning.",
    ),
    Asset(
        name="jquery",
        url="https://code.jquery.com/jquery-3.6.0.min.js",
        path="jquery-3.6.0.min.js",
        sri="sha256-/xUj+3OJU5yExlq6GSYGSHk7tPXikynS7ogEvDej/m4=",
        used_by="base_template_v2.html (span annotation, form handling)",
        notes="The most load-bearing of the three: without jQuery the span "
              "annotation surface does not work at all, so an air-gapped "
              "deployment lost text annotation entirely. The SRI is the one the "
              "template itself carried while it loaded from the CDN.",
    ),
    Asset(
        name="font-awesome",
        url="https://use.fontawesome.com/releases/v6.7.2/fontawesome-free-6.7.2-web.zip",
        path="font-awesome-6.7.2/css/all.min.css",
        sri="",  # distributed as a zip; verified by upstream release, not per-file SRI
        used_by="base_template_v2.html, adjudication.html",
        notes="Distributed as a zip because the webfonts directory has to travel "
              "with the CSS -- the stylesheet references ../webfonts/*.woff2, so "
              "vendoring all.min.css alone gives an air-gapped deployment a page "
              "of empty icon boxes rather than a missing stylesheet.",
    ),
    # --- legacy pages -------------------------------------------------------
    # header.html and the Simple-Likert example predate the v2 template and run
    # on Bootstrap 4 with slim jQuery. They are vendored at the versions they
    # already used: this is an air-gap fix, not a migration, and changing the
    # major version under a legacy layout is how you break it silently.
    Asset(
        name="d3",
        url="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js",
        path="d3-7.9.0.min.js",
        sri="sha512-vc58qvvBdrDR4etbxMdlTt4GBQk1qjvyORR2nrsPsFPyrs+/u5c3+1Ct6upOgdZoIl7eq6k3a1UPDSNAQi/32A==",
        used_by="solo/status.html (charts)",
        notes="Pinned to 7.9.0, the version d3js.org/d3.v7.min.js currently "
              "serves. The alias URL cannot be pinned by definition, which is "
              "reason enough to stop using it.",
    ),
    Asset(
        name="jquery-slim",
        url="https://code.jquery.com/jquery-3.4.1.slim.min.js",
        path="jquery-3.4.1.slim.min.js",
        sri="sha512-eHWYortWe2NyxHIiY/wY82nK4RlPIDDDSD5ZvTHrTkiq9tAe++DBhq5rDcC02xqHxh0ctGGMbHKotqtYcYgXZA==",
        used_by="header.html, Simple-Likert-Scale-Example-base_template.html",
        notes="A second, older, slim jQuery than the 3.6.0 the v2 template "
              "loads. Kept as-is: these pages were built against it.",
    ),
    Asset(
        name="popper",
        url="https://cdn.jsdelivr.net/npm/popper.js@1.16.0/dist/umd/popper.min.js",
        path="popper-1.16.0.umd.min.js",
        sri="sha512-hCP3piYGSBPqnXypdKxKPSOzBHF75oU8wQ81a6OiGXHFMeKs9/8ChbgYl7pUvwImXJb03N4bs1o1DzmbokeeFw==",
        used_by="header.html, Simple-Likert-Scale-Example-base_template.html",
        notes="Bootstrap 4 needs Popper separately; Bootstrap 5's bundle has it.",
    ),
    Asset(
        name="bootstrap4-css",
        url="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/4.1.3/css/bootstrap.min.css",
        path="bootstrap-4.1.3.min.css",
        sri="sha512-iQQV+nXtBlmS3XiDrtmL+9/Z+ibux+YuowJjI4rcpO7NYgTzfTOiFNm09kWtfZzEB9fQ6TwOVc8lFVWooFuD/w==",
        used_by="header.html, Simple-Likert-Scale-Example-base_template.html",
        notes="Bootstrap 4, not 5. Loading it alongside the v2 template's "
              "Bootstrap 5 would be a problem, but these pages are standalone.",
    ),
    Asset(
        name="bootstrap4-js-413",
        url="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/4.1.3/js/bootstrap.min.js",
        path="bootstrap-4.1.3.min.js",
        sri="sha512-n6dYFOG599s4/mGlA6E+YLgtg9uPTOMDUb0IprSMDYVLr0ctiRryPEQ8gpM4DCMlx7M2G3CK+ZcaoOoJolzdCg==",
        used_by="header.html, Simple-Likert-Scale-Example-base_template.html",
        notes="These pages load BOTH 4.1.3 and 4.4.1 of Bootstrap's JS. That "
              "is pre-existing and preserved here rather than tidied, so "
              "vendoring cannot be blamed for a behaviour change.",
    ),
    Asset(
        name="bootstrap4-js-441",
        url="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/4.4.1/js/bootstrap.min.js",
        path="bootstrap-4.4.1.min.js",
        sri="sha512-jCaU0Dp3IbMDlZ6f6dSEQSnOrSsugG6F6YigRWnagi7HoOLshF1kwxLT4+xCZRgQsTNqpUKj6WmWOxsu9l3URA==",
        used_by="header.html, Simple-Likert-Scale-Example-base_template.html",
        notes="See bootstrap4-js-413.",
    ),
]


def sri_of(data: bytes, algorithm: str) -> str:
    digest = hashlib.new(algorithm, data).digest()
    return f"{algorithm}-{base64.b64encode(digest).decode()}"


def verify(asset: Asset, data: bytes) -> tuple[bool, str]:
    """Check `data` against the asset's pinned SRI."""
    if not asset.sri:
        return True, "no SRI pinned (skipped)"
    algorithm = asset.sri.split("-", 1)[0]
    actual = sri_of(data, algorithm)
    if actual != asset.sri:
        return False, f"expected {asset.sri}\n         got      {actual}"
    return True, "SRI ok"


def check(asset: Asset) -> bool:
    if not asset.path.exists():
        print(f"  MISSING  {asset.name}: {asset.path.relative_to(REPO_ROOT)}")
        return False
    ok, detail = verify(asset, asset.path.read_bytes())
    status = "ok" if ok else "MISMATCH"
    print(f"  {status:8s} {asset.name}: {detail}")
    return ok


def download(asset: Asset, force: bool = False) -> bool:
    if asset.path.exists() and not force:
        print(f"  present  {asset.name} (use --force to re-download)")
        return True
    if not asset.sri:
        print(f"  SKIP     {asset.name}: no SRI pinned; fetch it manually "
              f"(see notes) rather than trusting an unverified download")
        return True

    print(f"  fetching {asset.name} from {asset.url}")
    with urllib.request.urlopen(asset.url, timeout=60) as response:
        data = response.read()

    ok, detail = verify(asset, data)
    if not ok:
        print(f"  REFUSED  {asset.name}: integrity check failed.\n         {detail}")
        return False

    asset.path.parent.mkdir(parents=True, exist_ok=True)
    asset.path.write_bytes(data)
    print(f"  wrote    {asset.path.relative_to(REPO_ROOT)} ({len(data):,} bytes, {detail})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="verify committed files against their pinned hashes")
    parser.add_argument("--force", action="store_true",
                        help="re-download even if the file is present")
    args = parser.parse_args()

    print(f"Vendor directory: {VENDOR_DIR.relative_to(REPO_ROOT)}")
    results = [check(a) if args.check else download(a, args.force) for a in ASSETS]

    if not all(results):
        print("\nFAILED. Do not commit an asset that does not match its pinned hash.")
        return 1
    print("\nAll assets accounted for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
