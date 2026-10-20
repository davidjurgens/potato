"""
Depositing a snapshot itself on Zenodo, so the frozen files a paper cites can
be downloaded and checked, not only named.

A published dataset (``potato.publish``) is a processed release: annotator
ids mapped to A1..An, internal fields stripped. A snapshot deposit is the
opposite: the four files of the snapshot exactly as frozen, so that
``potato snapshot verify --dir`` on a downloaded copy reproduces the content
hash. That means two things go out as they are, and both are checked first:

* **the config file and the study's other config files** (YAML, JSON, .env,
  TOML; not the data files), inside the bundle. A literal credential in them
  (the deploy preflight's test, ``literal_secrets``), a value shaped like a
  provider's key in any other file (a layout's HTML or JS), a PEM private key
  in any file, or a config file that cannot be read to check it stops the
  deposit;
  nothing overrides it. Move the value to ``${ENV_VAR}`` and take a new
  snapshot.
* **annotator ids**, in ``annotations.jsonl`` and in the bundle's output
  directory, where every annotator's saved state goes, answers or not. They
  are listed and the deposit stops unless the caller says they may be public
  (``annotator_ids_public``). Ids that look like email addresses are named
  separately in the refusal.

Deposits default to the Zenodo sandbox and an unpublished draft, as
``potato.publish`` does. Each one is recorded in ``snapshots/deposits.json``
beside the snapshots (the snapshot folders themselves never change).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tarfile
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from potato.snapshots.build import project_paths

#: The snapshot's files, uploaded under these names. Together they are what
#: verify_folder needs.
DEPOSIT_FILES = ("manifest.json", "bundle.tar.gz", "annotations.jsonl", "items.json")
DEPOSITS_FILE = "deposits.json"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
#: Files in the bundle read for credentials besides the config. Data files
#: and annotation output are not configuration and are not parsed (a data
#: item's `token` field is not a credential).
_CONFIG_SUFFIXES = (".yaml", ".yml", ".env", ".toml", ".json")
#: A config file larger than this is not read, and stops the deposit: a file
#: that cannot be checked cannot be published.
_MAX_SCANNED_BYTES = 8_000_000
#: A PEM private key (TLS, SAML signing), in any file under any name.
_PRIVATE_KEY = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_CHUNK = 1 << 20


class DepositRefused(Exception):
    """The snapshot cannot go out as it is; ``reasons`` says why."""

    def __init__(self, reasons: List[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _parse_config_text(name: str, text: str) -> Any:
    if name.endswith(".env"):
        pairs = {}
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                pairs[key.strip().lower()] = value.strip().strip("'\"")
        return pairs
    if name.endswith(".toml"):
        try:
            import tomllib
        except ImportError:  # Python < 3.11
            import tomli as tomllib  # type: ignore
        return tomllib.loads(text)
    if name.endswith(".json"):
        try:
            return json.loads(text)
        except ValueError:
            # JSON Lines under a .json name, which Potato reads as data.
            return [json.loads(line) for line in text.splitlines() if line.strip()]
    import yaml
    return yaml.safe_load(text)


def _raw_findings(handle, provider_keys: bool) -> Tuple[bool, bool]:
    """(holds a PEM private key, holds a provider-shaped key), by reading the
    raw bytes, so a file of any type is covered."""
    from potato.deploy.preflight import SECRET_VALUE_SEARCH

    tail, pem, shaped = b"", False, False
    while not (pem and (shaped or not provider_keys)):
        chunk = handle.read(_CHUNK)
        if not chunk:
            break
        window = tail + chunk
        pem = pem or bool(_PRIVATE_KEY.search(window))
        shaped = shaped or (provider_keys and bool(SECRET_VALUE_SEARCH.search(window)))
        tail = chunk[-128:]
    return pem, shaped


def _project_layout(archive: tarfile.TarFile, config_file: str) -> Tuple[set, str]:
    """(bundle names of the data files, bundle prefix of the output dir), from
    the frozen config. Names are ``project/`` + the path under the task dir."""
    import posixpath

    import yaml
    data_names, output = set(), "annotation_output"
    try:
        handle = archive.extractfile("project/" + config_file)
        config = yaml.safe_load(handle.read().decode("utf-8")) if handle else {}
    except (KeyError, ValueError, yaml.YAMLError):
        config = {}
    config = config if isinstance(config, dict) else {}
    listed = config.get("data_files") or []
    for path in [listed] if isinstance(listed, str) else listed:
        if isinstance(path, str) and not posixpath.isabs(path):
            data_names.add("project/" + posixpath.normpath(path.replace("\\", "/")))
    raw = str(config.get("output_annotation_dir") or "annotation_output")
    output = posixpath.basename(posixpath.normpath(raw.replace("\\", "/"))) or output
    return data_names, f"project/{output}/"


def scan_bundle(bundle_path: str, config_file: str) -> Dict[str, Any]:
    """What in the bundle must not be published blind.

    ``secrets``: ``file: key.path`` for every literal credential in a config
    file (the deploy preflight's test). ``private_keys``: files holding a PEM
    private key. ``unreadable``: config files that could not be parsed or are
    too large to read, which therefore cannot be cleared. ``state_users``:
    every annotator with a saved state in the output directory, whether or
    not they answered anything (their state holds consent and survey answers).
    ``provider_keys``: files of any other type (a layout's HTML or JS, an .ini)
    holding a value shaped like a known provider's key.
    """
    from potato.deploy.preflight import literal_secrets

    found = {"secrets": [], "private_keys": [], "unreadable": [], "provider_keys": [],
             "state_users": set()}
    with tarfile.open(bundle_path, "r:gz") as archive:
        data_names, output_prefix = _project_layout(archive, config_file)
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name
            handle = archive.extractfile(member)
            if handle is None:
                continue
            # Data files and annotation output hold annotators' and items'
            # text, which is not searched for key shapes; a PEM key is never
            # anyone's answer.
            content = name.startswith(output_prefix) or name in data_names
            pem, shaped = _raw_findings(handle, provider_keys=not content)
            if pem:
                found["private_keys"].append(name)
            if shaped:
                found["provider_keys"].append(name)
            if name.startswith(output_prefix):
                parts = name[len(output_prefix):].split("/")
                if len(parts) >= 2 and parts[-1] == "user_state.json":
                    found["state_users"].add(parts[0])
                    try:
                        state = json.loads(archive.extractfile(member).read().decode("utf-8"))
                        if isinstance(state, dict) and state.get("user_id"):
                            found["state_users"].add(str(state["user_id"]))
                    except (ValueError, UnicodeDecodeError, AttributeError):
                        pass
                continue
            if name in data_names or not name.lower().endswith(_CONFIG_SUFFIXES):
                continue
            if member.size > _MAX_SCANNED_BYTES:
                found["unreadable"].append(f"{name} (over {_MAX_SCANNED_BYTES // 1_000_000} MB)")
                continue
            try:
                text = archive.extractfile(member).read().decode("utf-8")
                parsed = _parse_config_text(name.lower(), text)
            except Exception as exc:  # noqa: BLE001 - unreadable is a refusal, not a pass
                found["unreadable"].append(f"{name} ({type(exc).__name__})")
                continue
            found["secrets"].extend(f"{name}: {path}" for path in literal_secrets(parsed))
    # A config file whose parsed check already named the key is reported
    # there; the raw search is for what parsing cannot see (a key inside a
    # longer string, or in a file that is not parsed at all).
    named = {entry.split(": ", 1)[0] for entry in found["secrets"]}
    found["provider_keys"] = [n for n in found["provider_keys"] if n not in named]
    return found


def bundle_secrets(bundle_path: str, config_file: str = "") -> List[str]:
    """``file: key.path`` for every literal credential in the bundle's config files."""
    return scan_bundle(bundle_path, config_file)["secrets"]


def check_snapshot(config_path: str, ref: str = "latest") -> Dict[str, Any]:
    """What a deposit of this snapshot would publish, before anything is sent.

    Returns ``snapshot`` (the manifest), ``folder``, ``files`` (name, path,
    bytes), ``secrets``, ``private_keys``, ``unreadable``, ``annotators``
    (from the answers and from every saved state in the bundle) and
    ``email_like_annotators``.
    """
    from potato.snapshots.store import resolve, snapshot_folder

    manifest = resolve(config_path, ref)
    folder = snapshot_folder(config_path, manifest["id"])
    files = []
    for name in DEPOSIT_FILES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{manifest['id']} has no {name}; the snapshot is incomplete")
        files.append({"name": name, "path": path, "bytes": os.path.getsize(path)})
    annotators = set()
    with open(os.path.join(folder, "annotations.jsonl"), "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                annotators.add(str(json.loads(line).get("annotator", "")))
    scan = scan_bundle(os.path.join(folder, "bundle.tar.gz"), manifest.get("config_file") or "")
    # An annotator with a saved state and no answers is still in the bundle,
    # with whatever their consent and survey pages collected.
    annotators |= scan["state_users"]
    annotators.discard("")
    return {
        "snapshot": manifest,
        "folder": folder,
        "files": files,
        "secrets": scan["secrets"],
        "private_keys": scan["private_keys"],
        "provider_keys": scan["provider_keys"],
        "unreadable": scan["unreadable"],
        "annotators": sorted(annotators),
        "email_like_annotators": sorted(a for a in annotators if _EMAIL.match(a)),
    }


def refusals(check: Dict[str, Any], annotator_ids_public: bool) -> List[str]:
    reasons = []
    if check["secrets"]:
        reasons.append(
            "the bundle holds what look like literal credentials ("
            + ", ".join(check["secrets"]) + "). Replace each with ${ENV_VAR} in the "
            "config, take a new snapshot, and deposit that one")
    if check.get("private_keys"):
        reasons.append(
            "the bundle holds a private key (" + ", ".join(check["private_keys"]) + "). "
            "Move it out of the project, or name it under a key ending in `key_file`, "
            "which snapshots leave out, take a new snapshot, and deposit that one")
    if check.get("provider_keys"):
        reasons.append(
            "these files hold a value shaped like a provider's API key ("
            + ", ".join(check["provider_keys"]) + "). Remove it, take a new snapshot, "
            "and deposit that one")
    if check.get("unreadable"):
        reasons.append(
            "these config files could not be read to check them for credentials ("
            + ", ".join(check["unreadable"]) + "). Fix or remove them, take a new "
            "snapshot, and deposit that one")
    if check["annotators"] and not annotator_ids_public:
        sample = ", ".join(check["annotators"][:5]) + (" ..." if len(check["annotators"]) > 5 else "")
        reason = (f"the deposit publishes {len(check['annotators'])} annotator id(s) as "
                  f"stored, with each one's saved state, including consent and survey "
                  f"answers ({sample})")
        if check["email_like_annotators"]:
            reason += (f", {len(check['email_like_annotators'])} of them email addresses "
                       f"({', '.join(check['email_like_annotators'][:3])})")
        reasons.append(reason + ". Pass --annotator-ids-public if that is intended; "
                       "otherwise publish the anonymized dataset with `potato publish` instead")
    return reasons


def _description(manifest: Dict[str, Any], dataset_description: str) -> str:
    counts = manifest.get("counts") or {}
    lines = []
    if dataset_description:
        lines.append(f"<p>{dataset_description}</p>")
    lines.append(
        f"<p>Potato snapshot <code>{manifest['id']}</code>, frozen {manifest.get('created_at')} "
        f"with Potato {manifest.get('potato_version')}: {counts.get('items', 0)} items, "
        f"{counts.get('annotators', 0)} annotators, {counts.get('annotations', 0)} answers. "
        f"Content hash <code>{manifest.get('content_hash')}</code>.</p>")
    lines.append(
        "<p>To check a downloaded copy, put the four files in one folder and run "
        "<code>potato snapshot verify --dir &lt;folder&gt;</code>; it re-hashes the files "
        "against manifest.json and recomputes the content hash.</p>")
    return "\n".join(lines)


@contextlib.contextmanager
def _locked(path: str):
    """An exclusive lock on ``path`` where the platform has flock."""
    with open(path, "a", encoding="utf-8") as handle:
        try:
            import fcntl
        except ImportError:  # Windows: no lock; deposits there are one at a time
            yield
            return
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _record(config_path: str, snapshot_id: str, entry: Dict[str, Any]) -> None:
    """Append to deposits.json. Locked and written through a unique temp
    file, so two deposits finishing together both land; with a fixed temp
    name one was lost, or its os.replace failed after the upload succeeded."""
    root = project_paths(config_path)["snapshot_root"]
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, DEPOSITS_FILE)
    with _locked(path + ".lock"):
        data = read_deposits(root)
        data.setdefault(snapshot_id, []).append(entry)
        fd, temp = tempfile.mkstemp(dir=root, prefix=".deposits-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            os.replace(temp, path)
        except BaseException:
            if os.path.exists(temp):
                os.remove(temp)
            raise


def read_deposits(snapshot_root: str) -> Dict[str, List[Dict[str, Any]]]:
    path = os.path.join(snapshot_root, DEPOSITS_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def deposit_snapshot(config_path: str, ref: str = "latest", token: Optional[str] = None,
                     sandbox: bool = True, publish: bool = False,
                     annotator_ids_public: bool = False) -> Dict[str, Any]:
    """Upload a snapshot's files to a new Zenodo deposition.

    Raises:
        DepositRefused: a literal credential in the bundle, or annotator ids
            without ``annotator_ids_public``. Nothing has been sent.
    """
    from potato.publish.config import PublishConfig
    from potato.publish.targets import zenodo_deposit_files, zenodo_metadata_for

    check = check_snapshot(config_path, ref)
    reasons = refusals(check, annotator_ids_public)
    if reasons:
        raise DepositRefused(reasons)
    manifest = check["snapshot"]
    metadata = PublishConfig.from_config(project_paths(config_path)["config"]).metadata
    zenodo = zenodo_metadata_for(metadata)
    meta = zenodo["metadata"]
    meta["title"] = f"{meta['title']} (Potato snapshot {manifest['id']})"
    meta["description"] = _description(manifest, metadata.description)
    meta["version"] = manifest["id"]

    with tempfile.TemporaryDirectory(prefix="potato-deposit-") as staging:
        readme = os.path.join(staging, "README.md")
        with open(readme, "w", encoding="utf-8") as handle:
            handle.write(f"# {meta['title']}\n\n"
                         f"Content hash: `{manifest.get('content_hash')}`\n\n"
                         "Check a downloaded copy with:\n\n"
                         "    potato snapshot verify --dir <folder holding these files>\n")
        files = [(f["name"], f["path"]) for f in check["files"]] + [("README.md", readme)]
        result = zenodo_deposit_files(files, zenodo, token=token, sandbox=sandbox, publish=publish)

    entry = {
        "deposition_id": result.get("deposition_id"),
        "sandbox": bool(sandbox),
        "published": bool(result.get("published")),
        "doi": result.get("doi", ""),
        "url": result.get("url") or result.get("draft_url", ""),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "annotator_ids_public": bool(annotator_ids_public),
    }
    _record(config_path, manifest["id"], entry)
    return {"snapshot": manifest["id"], **entry}
