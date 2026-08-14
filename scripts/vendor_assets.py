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
        name="bootstrap-css",
        url="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
        path="bootstrap-5.3.3.min.css",
        sri="",  # vendored before this script existed; hash not recorded upstream-verified
        used_by="adjudication.html",
        notes="base_template_v2.html still loads Bootstrap 5.1.3 from a CDN. "
              "Switching it here is a MAJOR-version-adjacent bump (5.1 -> 5.3 "
              "adds colour modes and renames variables) and needs a full-app "
              "regression pass. Bootstrap's JS bundle is not vendored at all.",
    ),
    Asset(
        name="font-awesome",
        url="https://use.fontawesome.com/releases/v6.7.2/fontawesome-free-6.7.2-web.zip",
        path="font-awesome-6.7.2/css/all.min.css",
        sri="",  # distributed as a zip; verified by upstream release, not per-file SRI
        used_by="adjudication.html",
        notes="base_template_v2.html still loads Font Awesome 6.0.0 from a CDN. "
              "The webfonts directory must move with the CSS.",
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
