"""
Reading snapshots: listing, resolving a reference, tags, integrity checks.

Snapshot folders never change after they are written. Tags are the one mutable
part, kept in ``snapshots/tags.json`` beside them, like a git tag pointing at a
commit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

from potato.snapshots.build import SNAPSHOT_DIR, project_paths

TAGS_FILE = "tags.json"
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _manifest(folder: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(folder, "manifest.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _tags(snapshot_root: str) -> Dict[str, str]:
    path = os.path.join(snapshot_root, TAGS_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def list_snapshots_in(snapshot_root: str) -> List[Dict[str, Any]]:
    """Every finished snapshot, newest first, each with its ``tags``."""
    if not os.path.isdir(snapshot_root):
        return []
    tags = _tags(snapshot_root)
    from potato.snapshots.deposit import read_deposits
    deposits = read_deposits(snapshot_root)
    by_id: Dict[str, List[str]] = {}
    for name, snapshot_id in tags.items():
        by_id.setdefault(snapshot_id, []).append(name)
    out = []
    for name in os.listdir(snapshot_root):
        folder = os.path.join(snapshot_root, name)
        if not os.path.isdir(folder) or name.endswith(".partial"):
            continue
        manifest = _manifest(folder)
        if manifest and manifest.get("id") == name:
            out.append({**manifest, "tags": sorted(by_id.get(name, [])),
                        "deposits": deposits.get(name, [])})
    return sorted(out, key=lambda m: (int(m.get("sequence") or 0), m.get("created_at", ""), m["id"]),
                  reverse=True)


def list_snapshots(config_path: str) -> List[Dict[str, Any]]:
    return list_snapshots_in(project_paths(config_path)["snapshot_root"])


def resolve(config_path: str, ref: str) -> Dict[str, Any]:
    """A snapshot by id, unique id prefix, tag, or ``latest``."""
    snapshots = list_snapshots(config_path)
    if not snapshots:
        raise LookupError("This project has no snapshots yet; run `potato snapshot create` first.")
    if ref == "latest":
        return snapshots[0]
    for snapshot in snapshots:
        if snapshot["id"] == ref or ref in snapshot["tags"]:
            return snapshot
    matches = [s for s in snapshots if s["id"].startswith(ref) or s["content_hash"].startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise LookupError(f"{ref!r} matches {len(matches)} snapshots: "
                          + ", ".join(s["id"] for s in matches))
    raise LookupError(f"No snapshot, tag or id prefix {ref!r}. "
                      f"`potato snapshot list` shows what there is.")


def snapshot_folder(config_path: str, snapshot_id: str) -> str:
    return os.path.join(project_paths(config_path)["snapshot_root"], snapshot_id)


def load_snapshot(config_path: str, ref: str) -> Dict[str, Any]:
    """The manifest plus ``records`` (annotation rows) and ``items``."""
    manifest = resolve(config_path, ref)
    folder = snapshot_folder(config_path, manifest["id"])
    with open(os.path.join(folder, "annotations.jsonl"), "r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    with open(os.path.join(folder, "items.json"), "r", encoding="utf-8") as handle:
        items = json.load(handle)
    return {**manifest, "records": records, "items": items}


def validate_tag(name: str) -> None:
    if not _TAG_RE.match(name or "") or name == "latest":
        raise ValueError(f"Tag {name!r} must be 1-64 letters, digits, '.', '_' or '-', "
                         f"and not 'latest'")


def tag_snapshot(config_path: str, ref: str, name: str) -> Dict[str, Any]:
    """Point tag ``name`` at a snapshot, moving it if it pointed elsewhere."""
    validate_tag(name)
    manifest = resolve(config_path, ref)
    root = project_paths(config_path)["snapshot_root"]
    tags = _tags(root)
    tags[name] = manifest["id"]
    path = os.path.join(root, TAGS_FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(dict(sorted(tags.items())), handle, indent=2)
    os.replace(path + ".tmp", path)
    return manifest


def verify_snapshot(config_path: str, ref: str) -> Dict[str, Any]:
    """Re-hash a snapshot's files against its manifest.

    Returns ``{"id", "ok", "problems": [...], "content_hash"}``. The content
    hash is recomputed
    from the stored annotation rows and the config and data files inside the
    bundle, so a reader holding only the snapshot folder can confirm it is the
    one a paper cites.
    """
    manifest = resolve(config_path, ref)
    return verify_folder(snapshot_folder(config_path, manifest["id"]), manifest)


def verify_folder(folder: str, manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Re-hash a folder holding a snapshot's files: one in the project, or a
    copy downloaded from a deposit (manifest.json, bundle.tar.gz,
    annotations.jsonl, items.json). The manifest is read from the folder
    when not given."""
    import tarfile

    from potato.snapshots.build import content_hash

    if manifest is None:
        manifest = _manifest(folder)
        if manifest is None:
            raise FileNotFoundError(f"{folder} has no readable manifest.json")
    problems = []
    missing = [name for name in ("bundle.tar.gz", "annotations.jsonl", "items.json")
               if not os.path.isfile(os.path.join(folder, name))]
    if missing:
        return {"id": manifest.get("id"), "ok": False,
                "problems": [f"{name} is missing" for name in missing]}

    def sha(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    bundle = os.path.join(folder, "bundle.tar.gz")
    if sha(bundle) != manifest.get("bundle_sha256"):
        problems.append("bundle.tar.gz does not match bundle_sha256")
    annotations = os.path.join(folder, "annotations.jsonl")
    if sha(annotations) != manifest.get("annotations_sha256"):
        problems.append("annotations.jsonl does not match annotations_sha256")

    if not problems:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="potato-verify-") as staging:
            with tarfile.open(bundle, "r:gz") as archive:
                wanted = [m for m in archive.getmembers() if m.isfile() and m.name.startswith("project/")]
                safe = [m for m in wanted if ".." not in m.name.split("/")]
                archive.extractall(staging, members=safe)
            config_path_in = os.path.join(staging, "project", manifest["config_file"])
            paths = project_paths(config_path_in,
                                  external_dir=os.path.join(staging, "project", "external"))
            with open(annotations, "r", encoding="utf-8") as handle:
                records = [json.loads(line) for line in handle if line.strip()]
            with open(os.path.join(folder, "items.json"), "r", encoding="utf-8") as handle:
                items = json.load(handle)
            if content_hash(paths, records, items) != manifest.get("content_hash"):
                problems.append("the config, data and annotations do not hash to content_hash")
    return {"id": manifest["id"], "ok": not problems, "problems": problems,
            "content_hash": manifest.get("content_hash")}
