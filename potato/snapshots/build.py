"""
Freeze a project into a snapshot.

Everything is read from disk (or the MySQL state store), never from a running
server's memory, so a snapshot can be taken with the server up or down. The
annotation files a running server writes are each written whole, so a snapshot
taken mid-study holds every save that had finished.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

SNAPSHOT_DIR = "snapshots"
FORMAT_VERSION = 1


class SnapshotUnchanged(Exception):
    """The project's content matches its latest snapshot."""

    def __init__(self, existing: Dict[str, Any]):
        super().__init__(f"Nothing has changed since snapshot {existing['id']}")
        self.existing = existing


# ---------------------------------------------------------------------------
# Locating the project
# ---------------------------------------------------------------------------

def project_paths(config_path: str, external_dir: Optional[str] = None) -> Dict[str, Any]:
    """The config, task dir, output dir and data files of a project.

    ``external_dir`` is for a project unpacked from a bundle: files that lived
    outside the task directory were stored under ``external/``, and are read
    from there rather than from wherever the original machine kept them.
    """
    config_path = os.path.abspath(config_path)
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    config_dir = os.path.dirname(config_path)
    task_dir = config.get("task_dir", ".") or "."
    if not os.path.isabs(task_dir):
        task_dir = os.path.normpath(os.path.join(config_dir, task_dir))
    output_dir = config.get("output_annotation_dir", "annotation_output") or "annotation_output"
    if not os.path.isabs(output_dir):
        output_dir = os.path.normpath(os.path.join(task_dir, output_dir))
    data_files = []
    for rel in config.get("data_files") or []:
        path = rel if os.path.isabs(rel) else os.path.join(task_dir, rel)
        data_files.append(_external(os.path.normpath(path), task_dir, external_dir))
    return {"config": config, "config_path": config_path, "task_dir": task_dir,
            "config_dir": config_dir, "output_dir": output_dir,
            "data_files": data_files, "external_dir": external_dir,
            "snapshot_root": os.path.join(task_dir, SNAPSHOT_DIR)}


def _inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def _external(path: str, task_dir: str, external_dir: Optional[str]) -> str:
    if external_dir and not _inside(path, task_dir):
        return os.path.join(external_dir, os.path.basename(path))
    return path


# ---------------------------------------------------------------------------
# Every file the study is made of
# ---------------------------------------------------------------------------

#: Never part of the study's definition: the server's own state, and secrets.
_NOT_PROJECT_FILES = ("admin_api_key.txt",)
_NOT_PROJECT_SUFFIXES = (".sqlite", ".sqlite-wal", ".sqlite-shm", ".pyc")
_MAX_REFERENCE_LENGTH = 1024


#: A file reached through one of these keys holds secrets, whatever it is called.
_SECRET_KEY = re.compile(r"password|secret|token|credential|api_key|apikey|user_config_path", re.I)


def _strings(value: Any, keys: Tuple[str, ...] = ()):
    """Every string in a document, with the keys on the way to it."""
    if isinstance(value, str):
        yield value, keys
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, keys + (str(key),))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item, keys)


def credential_files(paths: Dict[str, Any]) -> List[str]:
    """The account roster (usernames and password hashes), wherever it is.

    The configured ``authentication.user_config_path``, else the server's
    default, ``user_config.json`` beside the output directory
    (``dirname(output_annotation_dir)``, so inside it when the setting ends in
    a slash). Snapshots are made to be cited and handed on; these never go in.
    """
    config, task_dir = paths["config"], paths["task_dir"]
    found = []
    explicit = (config.get("authentication") or {}).get("user_config_path")
    if explicit:
        for base in (task_dir, paths["config_dir"]):
            found.append(os.path.normpath(explicit if os.path.isabs(explicit)
                                          else os.path.join(base, explicit)))
    raw_output = str(config.get("output_annotation_dir") or "annotation_output")
    if not os.path.isabs(raw_output):
        raw_output = os.path.join(task_dir, raw_output)
    found.append(os.path.normpath(os.path.join(os.path.dirname(raw_output), "user_config.json")))
    found.append(os.path.join(paths["output_dir"], "user_config.json"))
    return sorted({os.path.realpath(p) for p in found})


def project_files(paths: Dict[str, Any],
                  omitted: Optional[List[str]] = None) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
    """The files a study is made of, beyond its config.

    Data files, then every other file a string anywhere in the config resolves
    to: phase and survey files, attention-check and gold item files, consent
    and instruction pages, custom layouts. Referenced YAML files are read for
    references of their own. Anything inside the output directory or the
    snapshots folder, the databases and the API key are left out; those are
    state, not definition. So are credentials: the account roster, and any
    file named under a key that mentions a password, secret, token,
    credential or API key. Each one left out is appended to ``omitted``.

    Returns ``(files, directories, warnings)``: ``files`` as ``(name in the
    bundle, path on disk)`` sorted by name; ``directories`` that the config
    names (media folders and the like), which are not copied; and warnings
    about files outside the task directory, which Potato refuses to serve.
    """
    task_dir, external_dir = paths["task_dir"], paths.get("external_dir")
    excluded_roots = [paths["output_dir"], paths["snapshot_root"]]
    found: Dict[str, str] = {}
    directories: List[str] = []
    warnings: List[str] = []
    omitted = omitted if omitted is not None else []
    secrets = set(credential_files(paths))

    def leave_out(path: str, why: str) -> None:
        note = f"{path}: {why}"
        if note not in omitted:
            omitted.append(note)

    def name_for(path: str) -> str:
        if _inside(path, task_dir):
            return os.path.relpath(os.path.realpath(path), os.path.realpath(task_dir)).replace(os.sep, "/")
        return "external/" + os.path.basename(path)

    def add(path: str) -> bool:
        if os.path.realpath(path) in secrets:
            leave_out(path, "the account roster (password hashes)")
            return False
        if (os.path.basename(path) in _NOT_PROJECT_FILES or path.endswith(_NOT_PROJECT_SUFFIXES)
                or any(_inside(path, root) for root in excluded_roots)
                or os.path.realpath(path) == os.path.realpath(paths["config_path"])):
            return False
        name = name_for(path)
        if name in found:
            return False
        found[name] = path
        if name.startswith("external/") and not external_dir:
            warnings.append(
                f"{path} is outside the task directory {task_dir}; it is in the snapshot "
                f"as {name}, but Potato refuses to serve a config that points outside "
                f"its project, so this study cannot be started as written.")
        return True

    for path in paths["data_files"]:
        if os.path.isfile(path):
            add(path)

    def walk(document: Any, bases: List[str], depth: int) -> None:
        for text, keys in _strings(document):
            text = text.strip()
            if (not text or len(text) > _MAX_REFERENCE_LENGTH or "\n" in text
                    or text.startswith(("http://", "https://", "data:")) or text in (".", "./")):
                continue
            candidates = [text] if os.path.isabs(text) else [os.path.join(b, text) for b in bases]
            secret_key = next((k for k in keys if _SECRET_KEY.search(k)), None)
            if secret_key:
                for candidate in candidates:
                    if os.path.isfile(candidate):
                        leave_out(os.path.normpath(candidate),
                                  f"named under `{secret_key}`, so treated as a credential")
                        break
                continue
            for candidate in candidates:
                candidate = os.path.normpath(candidate)
                if os.path.isfile(candidate) or (external_dir and not _inside(candidate, task_dir)):
                    resolved = _external(candidate, task_dir, external_dir)
                    if os.path.isfile(resolved) and add(resolved) and depth < 3 \
                            and resolved.endswith((".yaml", ".yml")):
                        try:
                            with open(resolved, "r", encoding="utf-8") as handle:
                                nested = yaml.safe_load(handle)
                        except (OSError, yaml.YAMLError):
                            nested = None
                        walk(nested, [os.path.dirname(resolved), task_dir], depth + 1)
                    break
                if os.path.isdir(candidate):
                    if (not any(_inside(candidate, root) or _inside(root, candidate)
                                for root in excluded_roots)
                            and not _inside(task_dir, candidate)  # the task dir or above it
                            and candidate not in directories):
                        directories.append(candidate)
                    break

    walk(paths["config"], [task_dir, paths["config_dir"]], 0)
    return sorted(found.items()), sorted(directories), warnings


# ---------------------------------------------------------------------------
# What a snapshot records
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def item_ids(paths: Dict[str, Any]) -> List[str]:
    """Item ids from the data files, in file order."""
    id_key = ((paths["config"].get("item_properties") or {}).get("id_key")) or "id"
    ids: List[str] = []
    for path in paths["data_files"]:
        if not os.path.isfile(path):
            continue
        if path.endswith((".csv", ".tsv")):
            with open(path, "r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t" if path.endswith(".tsv") else ",")
                ids.extend(str(row.get(id_key)) for row in reader if row.get(id_key) is not None)
            continue
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
        if not text:
            continue
        rows: Iterable[Any]
        if text.startswith("["):
            rows = json.loads(text)
        else:
            rows = (json.loads(line) for line in text.splitlines() if line.strip())
        ids.extend(str(row[id_key]) for row in rows
                   if isinstance(row, dict) and id_key in row)
    return ids


def _canonical(value: Any) -> Any:
    """JSON-stable form of a stored value (sorted, strings for odd types)."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def annotation_records(paths: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One record per (annotator, item, scheme), sorted.

    The value is every label entry (name and stored value) and span the
    annotator saved for that scheme, sorted, so two snapshots of the same
    answers produce identical records whatever order the saves happened in.
    """
    from potato.server_utils.stored_states import iter_stored_states

    grouped: Dict[Tuple[str, str, str], Dict[str, list]] = {}
    for entry, state in iter_stored_states(paths["output_dir"], paths["config"],
                                           skip_unreadable=True):
        user = str(state.get("user_id") or entry)
        for iid, labels in (state.get("instance_id_to_label_to_value") or {}).items():
            for pair in labels or []:
                if not (isinstance(pair, (list, tuple)) and len(pair) == 2
                        and isinstance(pair[0], dict)):
                    continue
                label, value = pair
                key = (user, str(iid), str(label.get("schema")))
                grouped.setdefault(key, {"labels": [], "spans": []})["labels"].append(
                    [str(label.get("name")), _canonical(value)])
        for iid, spans in (state.get("instance_id_to_span_to_value") or {}).items():
            for pair in spans or []:
                if not (isinstance(pair, (list, tuple)) and len(pair) == 2
                        and isinstance(pair[0], dict)):
                    continue
                span = pair[0]
                key = (user, str(iid), str(span.get("schema")))
                grouped.setdefault(key, {"labels": [], "spans": []})["spans"].append(
                    [str(span.get("name")), span.get("start"), span.get("end")])
    records = []
    for (user, iid, schema), value in sorted(grouped.items()):
        value = {k: sorted(v, key=lambda x: json.dumps(x, sort_keys=True))
                 for k, v in value.items() if v}
        records.append({"annotator": user, "item": iid, "schema": schema, "value": value})
    return records


def agreement_summary(config_path: str) -> Dict[str, Any]:
    """Per-scheme agreement as Paper Mode computes it, without the label tables."""
    from potato.paper.collect import collect_project
    from potato.paper.metrics import compute_metrics

    metrics = compute_metrics(collect_project(config_path))
    keep = ("name", "annotation_type", "alpha", "alpha_interpretation", "n_units",
            "n_multi_annotated", "mean_kappa", "percent_agreement")
    schemes = [{k: s.get(k) for k in keep if k in s} for s in metrics.get("schemes") or []]
    return {"schemes": schemes,
            "num_annotators": metrics.get("num_annotators"),
            "num_annotations": metrics.get("num_annotations")}


def content_hash(paths: Dict[str, Any], records: List[dict], ids: List[str],
                 files: Optional[List[Tuple[str, str]]] = None) -> str:
    """sha256 over what a citation is about: config, the study's files, answers.

    "The study's files" are :func:`project_files`: data, phase and survey
    files, item lists, pages and layouts, each under its name in the bundle.
    The SQLite databases are in the bundle but not in this hash: they are
    rewritten by the server as it runs, so their bytes change when nothing a
    reader would care about has.
    """
    if files is None:
        files = project_files(paths)[0]
    digest = hashlib.sha256()
    digest.update(b"config\0")
    digest.update(open(paths["config_path"], "rb").read())
    for name, path in files:
        digest.update(b"\0file\0" + name.encode() + b"\0")
        digest.update(open(path, "rb").read())
    digest.update(b"\0items\0" + json.dumps(ids).encode())
    digest.update(b"\0annotations\0")
    for record in records:
        digest.update(json.dumps(record, sort_keys=True).encode() + b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _write_bundle(paths: Dict[str, Any], destination: str,
                  files: List[Tuple[str, str]], omitted: List[str]) -> List[str]:
    """config + the study's files + output dir + databases, as one tar.gz.

    The output directory comes from ``data_archive.build_archive`` (the
    `deploy pull` archive), which keeps the roster because pulling your own
    study back needs it. A snapshot is for handing on, so the roster is
    dropped here and noted in ``omitted``.
    """
    import tarfile

    from potato.server_utils.data_archive import build_archive

    with tempfile.TemporaryDirectory(prefix="potato-snapshot-") as staging:
        inner = os.path.join(staging, "annotations.tar.gz")
        with open(inner, "wb") as handle:
            summary = build_archive(paths["output_dir"], paths["task_dir"], handle,
                                    config=paths["config"])
        names = ["project/" + os.path.basename(paths["config_path"])]
        with tarfile.open(destination, "w:gz") as bundle:
            bundle.add(paths["config_path"], arcname=names[0])
            for name, path in files:
                bundle.add(path, arcname="project/" + name)
                names.append("project/" + name)
            base = os.path.basename(os.path.normpath(paths["output_dir"])) or "annotation_output"
            roster_names = {
                f"{base}/{os.path.relpath(p, os.path.realpath(paths['output_dir']))}".replace(os.sep, "/")
                for p in credential_files(paths)
                if _inside(p, paths["output_dir"])}
            with tarfile.open(inner, "r:gz") as annotations:
                for member in annotations.getmembers():
                    if member.name in roster_names:
                        omitted.append(f"{os.path.join(os.path.dirname(paths['output_dir']), member.name)}: "
                                       f"the account roster (password hashes)")
                        continue
                    extracted = annotations.extractfile(member)
                    if extracted is None:
                        continue
                    member.name = "project/" + member.name
                    bundle.addfile(member, extracted)
                    names.append(member.name)
        return names + [f"(skipped) {s}" for s in summary.get("skipped", [])]


def _read_only(path: str) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def latest_manifest(snapshot_root: str) -> Optional[Dict[str, Any]]:
    from potato.snapshots.store import list_snapshots_in
    snapshots = list_snapshots_in(snapshot_root)
    return snapshots[0] if snapshots else None


def create_snapshot(config_path: str, note: str = "", tag: Optional[str] = None,
                    force: bool = False, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Freeze the project at ``config_path``. Returns the manifest.

    Raises:
        SnapshotUnchanged: the content hash equals the latest snapshot's and
            ``force`` is False. The exception carries that manifest.
    """
    # Not `from potato import __version__`: run as `python potato/flask_server.py`
    # the package is a namespace with no __version__, and the import fails.
    from potato.version_info import source_version
    from potato.snapshots.store import tag_snapshot, validate_tag

    if tag:
        validate_tag(tag)  # before anything is written
    paths = project_paths(config_path)
    omitted: List[str] = []
    files, directories, warnings = project_files(paths, omitted)
    records = annotation_records(paths)
    ids = item_ids(paths)
    digest = content_hash(paths, records, ids, files)
    latest = latest_manifest(paths["snapshot_root"])
    if latest and latest.get("content_hash") == digest and not force:
        if tag:
            tag_snapshot(config_path, latest["id"], tag)
        raise SnapshotUnchanged(latest)

    now = now or datetime.now(timezone.utc)
    snapshot_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{digest[:8]}"
    folder = os.path.join(paths["snapshot_root"], snapshot_id)
    if os.path.exists(folder):
        raise FileExistsError(f"Snapshot {snapshot_id} already exists; snapshots are never overwritten")
    os.makedirs(paths["snapshot_root"], exist_ok=True)
    partial = folder + ".partial"
    try:
        os.makedirs(partial)
    except FileExistsError:
        raise FileExistsError(
            f"Another `snapshot create` is writing {snapshot_id} right now. "
            f"Run `potato snapshot list` once it finishes.") from None
    try:
        bundle_path = os.path.join(partial, "bundle.tar.gz")
        contents = _write_bundle(paths, bundle_path, files, omitted)
        with open(os.path.join(partial, "annotations.jsonl"), "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        with open(os.path.join(partial, "items.json"), "w", encoding="utf-8") as handle:
            json.dump(ids, handle)
        manifest = {
            "format": FORMAT_VERSION,
            "id": snapshot_id,
            "created_at": now.isoformat(timespec="seconds"),
            "note": note,
            "task_name": paths["config"].get("annotation_task_name", ""),
            "config_file": os.path.basename(paths["config_path"]),
            "potato_version": source_version(),
            "content_hash": digest,
            "config_sha256": _sha256_file(paths["config_path"]),
            "bundle_sha256": _sha256_file(bundle_path),
            "annotations_sha256": _sha256_file(os.path.join(partial, "annotations.jsonl")),
            "counts": {
                "items": len(ids),
                "annotators": len({r["annotator"] for r in records}),
                "annotated_items": len({r["item"] for r in records}),
                "annotations": len(records),
            },
            "agreement": agreement_summary(paths["config_path"]),
            "bundle_contents": contents,
            "project_files": [name for name, _path in files],
            #: Folders the config names (media and the like). Not copied: they
            #: can be any size. Their files are not in the content hash.
            "referenced_directories": directories,
            "warnings": warnings,
            #: Credentials found and deliberately left out of the bundle.
            "omitted": sorted(set(omitted)),
            "previous": latest["id"] if latest else None,
            # Order of creation. Ids and created_at carry whole seconds, so
            # two snapshots in one second would otherwise sort by their hash.
            "sequence": (int(latest.get("sequence") or 0) + 1) if latest else 1,
        }
        with open(os.path.join(partial, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
        for name in os.listdir(partial):
            _read_only(os.path.join(partial, name))
        # Renamed into place last, so a crash leaves a .partial folder that no
        # listing reads rather than a snapshot missing its manifest.
        os.rename(partial, folder)
    except BaseException:
        import shutil
        for name in os.listdir(partial) if os.path.isdir(partial) else []:
            os.chmod(os.path.join(partial, name), stat.S_IWUSR | stat.S_IRUSR)
        shutil.rmtree(partial, ignore_errors=True)
        raise
    if tag:
        tag_snapshot(config_path, snapshot_id, tag)
    return manifest

