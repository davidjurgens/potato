"""Getting the annotations back down.

Three transports, in order of preference:

1. **SSH/SFTP** where the host has a shell — a droplet, later a Lightsail box.
   Fetches the files directly and snapshots the SQLite databases on the far end.
2. **The backup Dataset** on HuggingFace, where the Space's own filesystem is
   temporary and the Dataset is the real store.
3. **HTTPS**, over the admin data-archive endpoint. Needs nothing but the URL
   and the admin key, which `potato deploy` already holds, so it works on every
   provider including the ones with no shell at all.

The third is the reason this module exists. Render and anything serverless have
no SSH, and they are also the hosts most likely to lose their disk, so "no
transport available" was not an acceptable answer for them.

Whatever the transport, the result has to be checkable. A pull that quietly
returns nothing looks identical to a pull from a task nobody has annotated yet,
and the difference matters enormously.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import tarfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from potato.deploy.providers.base import ProviderError, PullResult

logger = logging.getLogger(__name__)

MANIFEST_PATH = "/admin/api/data/manifest"
ARCHIVE_PATH = "/admin/api/data/archive"

# Generous: the server snapshots its databases and walks the output directory
# before the first byte arrives, and a free instance may be starting from cold.
CONNECT_TIMEOUT = 30
READ_TIMEOUT = 900


@dataclass
class PullVerification:
    """What actually landed, checked rather than assumed."""

    files: int = 0
    bytes: int = 0
    annotators: int = 0
    databases: List[str] = field(default_factory=list)
    corrupt: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.files > 0 and not self.corrupt


def fetch_manifest(url: str, admin_key: str) -> Optional[Dict]:
    """Ask the server what it would send. None when the endpoint is absent."""
    import requests

    try:
        response = requests.get(f"{url.rstrip('/')}{MANIFEST_PATH}",
                                headers={"X-API-Key": admin_key},
                                timeout=(CONNECT_TIMEOUT, 60))
    except requests.RequestException as exc:
        raise ProviderError(f"Could not reach {url}: {exc}") from exc

    if response.status_code == 404:
        return None
    _raise_for_auth(response, url)
    try:
        return response.json()
    except ValueError:
        return None


def pull_over_https(url: str, admin_key: str, dest: str,
                    console=None) -> PullResult:
    """Download and unpack the admin data archive.

    Streamed to disk rather than held in memory: the archive is the whole study,
    and the machine running this is often a laptop with the browser open.
    """
    import requests

    console = console or logger.info
    base = url.rstrip("/")
    os.makedirs(dest, exist_ok=True)

    manifest = fetch_manifest(base, admin_key)
    if manifest is None:
        raise ProviderError(
            f"{base} has no admin data-archive endpoint. It is running a Potato "
            "older than the one that added it, so there is no way to pull over "
            "HTTPS. Redeploy with the current version, or use the provider's own "
            "transport if it has one.")
    if manifest.get("files"):
        console(f"Server reports {manifest['files']} file(s), "
                f"{_human(manifest.get('bytes', 0))}")

    try:
        response = requests.get(f"{base}{ARCHIVE_PATH}",
                                headers={"X-API-Key": admin_key},
                                stream=True,
                                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except requests.RequestException as exc:
        raise ProviderError(f"Could not download the archive: {exc}") from exc
    _raise_for_auth(response, base)

    archive_path = os.path.join(dest, ".potato-archive.tar.gz")
    downloaded = 0
    try:
        with open(archive_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if chunk:
                    handle.write(chunk)
                    downloaded += len(chunk)
        console(f"Downloaded {_human(downloaded)}")

        result = PullResult(dest=dest, bytes=downloaded)
        extracted = _safe_extract(archive_path, dest)
        result.files = len(extracted)
        result.notes.append(f"downloaded over HTTPS from {base}")
        for database in [name for name in extracted if name.endswith(".sqlite")]:
            result.notes.append(f"{database} snapshotted server-side with the "
                                "SQLite backup API")
    finally:
        try:
            os.unlink(archive_path)
        except OSError:
            pass
    return result


def _raise_for_auth(response, url: str) -> None:
    if response.status_code == 403:
        raise ProviderError(
            f"{url} rejected the admin API key. It is stored in "
            ".potato/secrets.json; if that file was lost or the deployment was "
            "recreated, the key on the server no longer matches.")
    if response.status_code >= 400:
        raise ProviderError(
            f"{url} returned {response.status_code} for the data archive.")


def _safe_extract(archive_path: str, dest: str) -> List[str]:
    """Unpack a tar, refusing any member that would escape the destination.

    The archive comes from a server the caller chose, but `..` in a member name
    writes outside `dest` — and this runs on the researcher's own laptop with
    their own privileges. Python only made `tarfile` refuse this by default in
    3.12, and Potato supports older versions.
    """
    dest = os.path.abspath(dest)
    written: List[str] = []
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = os.path.abspath(os.path.join(dest, member.name))
            if not target.startswith(dest + os.sep) and target != dest:
                raise ProviderError(
                    f"The archive contains a path that would write outside the "
                    f"destination: {member.name!r}. Refusing to extract it.")
            if member.issym() or member.islnk():
                raise ProviderError(
                    f"The archive contains a link ({member.name!r}); refusing "
                    "to extract it.")
            archive.extract(member, dest)
            if member.isfile():
                written.append(member.name)
    return written


def verify_pull(dest: str) -> PullVerification:
    """Check what landed, rather than trusting that it did.

    An empty result and a genuinely empty study look the same from the outside,
    and `destroy` will accept either as "already pulled". So the numbers get
    reported, and a database that will not open is called out rather than left
    to be discovered later.
    """
    verification = PullVerification()
    if not os.path.isdir(dest):
        verification.warnings.append(f"{dest} does not exist")
        return verification

    annotators = set()
    for dirpath, dirnames, filenames in os.walk(dest):
        dirnames[:] = [d for d in dirnames if d != ".cache"]
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            verification.files += 1
            try:
                verification.bytes += os.path.getsize(path)
            except OSError:
                continue
            if filename == "user_state.json":
                annotators.add(os.path.basename(dirpath))
            elif filename.endswith(".sqlite"):
                verification.databases.append(filename)
                if not _database_opens(path):
                    verification.corrupt.append(filename)

    verification.annotators = len(annotators)
    if verification.files == 0:
        verification.warnings.append(
            "Nothing was downloaded. Either nobody has annotated yet, or the "
            "output directory on the server is not where the config says.")
    elif verification.annotators == 0:
        verification.warnings.append(
            "No user_state.json anywhere in the result, so no annotator's work "
            "came back. Files arrived, so the transport worked — check "
            "output_annotation_dir in the config.")
    return verification


def _database_opens(path: str) -> bool:
    """Whether a pulled SQLite file is a usable database.

    The point of the whole snapshot-rather-than-copy rule is that a broken one
    looks fine until someone opens it, so open it here.

    ``immutable=1`` rather than plain ``mode=ro``: a read-only connection to a
    WAL-mode database still builds a shared-memory index, so checking the
    snapshot left ``project.sqlite-wal`` and ``project.sqlite-shm`` sitting
    beside it. Those are the live sidecars this whole path exists to avoid
    copying, and finding them in a directory labelled as the safe copy is
    exactly the wrong signal. A snapshot has no WAL to replay, so promising
    SQLite the file cannot change costs nothing.
    """
    try:
        connection = sqlite3.connect(
            f"file:{path}?mode=ro&immutable=1", uri=True, timeout=10)
        try:
            return connection.execute(
                "PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def render_verification(verification: PullVerification) -> str:
    lines = [
        f"  files      {verification.files}",
        f"  size       {_human(verification.bytes)}",
        f"  annotators {verification.annotators}",
    ]
    if verification.databases:
        lines.append(f"  databases  {', '.join(sorted(set(verification.databases)))}")
    for name in verification.corrupt:
        lines.append(f"  CORRUPT    {name} did not pass a SQLite integrity check")
    for warning in verification.warnings:
        lines.append(f"  WARNING    {warning}")
    return "\n".join(lines)


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"
