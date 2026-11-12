"""
Third-party browser libraries that are fetched per install, not committed.

Small libraries live in ``potato/static/vendor/<lib>-<version>/`` and are
committed (see ``scripts/vendor_assets.py``). Large ones (today only the
Mol* structure viewer, ``molstar``; see :mod:`potato.vendoring.manifest`) are
listed here instead and installed with ``potato vendor fetch <name>``. Each is pinned to one version
and verified against a published hash before anything is written, so a
fetched install serves the same bytes as every other install of that Potato
version.

Bundles land in ``potato/vendor_fetched/<name>-<version>/`` (gitignored and
left out of the wheel), or under ``$POTATO_VENDOR_DIR`` when that is set, which
suits a read-only site-packages or a Docker image built once. The server
serves them from ``/vendor-fetched/<name>-<version>/<path>``.

Two kinds of source:

* ``files``: individual URLs, each with its SHA-256.
* ``tarball``: one npm package tarball with its registry ``integrity``
  (SHA-512). Only the paths under ``include`` are extracted, and each
  extracted file's SHA-256 is recorded so ``potato vendor verify`` can check
  the install later without the network.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

MARKER = ".potato-vendor.json"
USER_AGENT = "potato-annotation-vendor-fetch"
TIMEOUT_S = 120


@dataclass(frozen=True)
class BundleFile:
    url: str
    dest: str          # path inside the bundle directory
    sha256: str        # hex


@dataclass(frozen=True)
class Bundle:
    name: str
    version: str
    license: str
    homepage: str
    description: str
    files: Tuple[BundleFile, ...] = ()
    tarball: Optional[str] = None          # URL of an npm .tgz
    integrity: Optional[str] = None        # "sha512-<base64>" from the npm registry
    include: Tuple[str, ...] = ()          # path prefixes inside the tarball, after strip
    strip: str = "package/"                # npm tarballs put everything under package/
    approx_mb: float = 0.0

    @property
    def dirname(self) -> str:
        return f"{self.name}-{self.version}"


#: Every fetchable bundle, by name. Entries are added by the feature that
#: needs them (runtime adapters, viewer displays).
BUNDLES: Dict[str, Bundle] = {}


def register(bundle: Bundle) -> Bundle:
    BUNDLES[bundle.name] = bundle
    return bundle


def _load_manifest() -> None:
    # Bundle definitions live beside the feature that uses them; importing
    # the manifest module registers them all.
    from potato.vendoring import manifest  # noqa: F401


def get(name: str) -> Optional[Bundle]:
    _load_manifest()
    return BUNDLES.get(name)


def all_bundles() -> List[Bundle]:
    _load_manifest()
    return sorted(BUNDLES.values(), key=lambda b: b.name)


def vendor_dir() -> Path:
    override = os.environ.get("POTATO_VENDOR_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "vendor_fetched"


def bundle_dir(bundle: Bundle) -> Path:
    return vendor_dir() / bundle.dirname


def _marker(bundle: Bundle) -> Optional[dict]:
    path = bundle_dir(bundle) / MARKER
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_installed(name: str) -> bool:
    bundle = get(name)
    if bundle is None:
        return False
    marker = _marker(bundle)
    if not marker or marker.get("version") != bundle.version:
        return False
    root = bundle_dir(bundle)
    return all((root / rel).is_file() for rel in marker.get("files", {}))


def file_path(name: str, rel: str) -> Optional[Path]:
    """Absolute path of one installed file, or None (not installed, or ``rel``
    is not a file the bundle recorded)."""
    bundle = get(name)
    if bundle is None:
        return None
    marker = _marker(bundle)
    if not marker or rel not in marker.get("files", {}):
        return None
    path = bundle_dir(bundle) / rel
    return path if path.is_file() else None


def static_url(name: str, rel: str) -> str:
    """URL the server serves an installed file from."""
    bundle = get(name)
    if bundle is None:
        raise KeyError(name)
    return f"/vendor-fetched/{bundle.dirname}/{rel}"


def missing(names: Iterable[str]) -> List[str]:
    return [n for n in dict.fromkeys(names) if not is_installed(n)]


def fetch_hint(names: Iterable[str]) -> str:
    names = list(dict.fromkeys(names))
    return f"potato vendor fetch {' '.join(names)}"


class FetchError(RuntimeError):
    pass


def _download(url: str) -> bytes:
    if not url.startswith("https://"):
        raise FetchError(f"refusing a non-https URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 (https only)
        return resp.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_integrity(data: bytes, integrity: str) -> None:
    algo, _, expected = integrity.partition("-")
    if algo not in ("sha512", "sha384", "sha256"):
        raise FetchError(f"unsupported integrity algorithm {algo!r}")
    got = base64.b64encode(hashlib.new(algo, data).digest()).decode("ascii")
    if got != expected:
        raise FetchError(f"integrity mismatch: expected {integrity}, got {algo}-{got}")


def _safe_rel(rel: str) -> str:
    norm = os.path.normpath(rel).replace("\\", "/")
    if norm.startswith("../") or norm == ".." or os.path.isabs(norm) or norm.startswith("/"):
        raise FetchError(f"unsafe path in bundle: {rel!r}")
    return norm


def _extract_tarball(bundle: Bundle, data: bytes, dest: Path) -> Dict[str, str]:
    recorded: Dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue  # no links, devices or directories from the archive
            name = member.name
            if not name.startswith(bundle.strip):
                continue
            rel = _safe_rel(name[len(bundle.strip):])
            if bundle.include and not any(rel == p or rel.startswith(p) for p in bundle.include):
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            content = fh.read()
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            recorded[rel] = _sha256(content)
    if not recorded:
        raise FetchError(f"{bundle.name}: the tarball had no files under {bundle.include}")
    return recorded


def fetch(name: str, *, force: bool = False, log=print) -> Path:
    """Download, verify and install one bundle. Returns its directory."""
    bundle = get(name)
    if bundle is None:
        raise FetchError(f"unknown bundle {name!r}; see `potato vendor list`")
    if is_installed(name) and not force:
        log(f"{bundle.dirname}: already installed at {bundle_dir(bundle)}")
        return bundle_dir(bundle)
    root = vendor_dir()
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{bundle.dirname}-", dir=root))
    try:
        recorded: Dict[str, str] = {}
        if bundle.tarball:
            if not bundle.integrity:
                raise FetchError(f"{bundle.name}: tarball has no pinned integrity")
            log(f"{bundle.dirname}: downloading {bundle.tarball}")
            data = _download(bundle.tarball)
            _check_integrity(data, bundle.integrity)
            recorded.update(_extract_tarball(bundle, data, tmp))
        for bf in bundle.files:
            log(f"{bundle.dirname}: downloading {bf.url}")
            data = _download(bf.url)
            got = _sha256(data)
            if got != bf.sha256:
                raise FetchError(f"{bf.url}: SHA-256 mismatch (expected {bf.sha256}, got {got})")
            rel = _safe_rel(bf.dest)
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            recorded[rel] = got
        with open(tmp / MARKER, "w", encoding="utf-8") as f:
            json.dump({"name": bundle.name, "version": bundle.version,
                       "license": bundle.license, "files": recorded}, f, indent=1)
        final = bundle_dir(bundle)
        if final.exists():
            shutil.rmtree(final)
        tmp.rename(final)
        log(f"{bundle.dirname}: installed {len(recorded)} files ({bundle.license})")
        return final
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def verify(name: str) -> List[str]:
    """Problems with an installed bundle (empty when it is intact)."""
    bundle = get(name)
    if bundle is None:
        return [f"unknown bundle {name!r}"]
    marker = _marker(bundle)
    if marker is None:
        return [f"{name} is not installed; run `potato vendor fetch {name}`"]
    if marker.get("version") != bundle.version:
        return [f"{name}: installed {marker.get('version')}, this Potato needs {bundle.version}"]
    problems = []
    root = bundle_dir(bundle)
    for rel, sha in marker.get("files", {}).items():
        path = root / rel
        if not path.is_file():
            problems.append(f"{name}: missing {rel}")
        elif _sha256(path.read_bytes()) != sha:
            problems.append(f"{name}: {rel} changed since it was fetched")
    return problems
