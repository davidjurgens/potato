"""
Fetching ConvoKit corpora by name.

ConvoKit publishes a manifest on GitHub mapping corpus names to zip URLs on
Cornell's server, and its own ``convokit.download()`` reads exactly that. This
module does the same with the standard library, so ``potato convokit
friends-corpus`` works without the ``convokit`` package installed.

Cache interoperability
----------------------

Corpora are cached where ConvoKit itself caches them — ``~/.convokit/saved-corpora``,
or whatever ``data_directory`` is set to in ``~/.convokit/config.yml`` — so a user
who already has ConvoKit installed does not download anything twice, in either
direction.

What this module refuses to do
------------------------------

* **Fetch over plain HTTP.** Several manifest URLs are ``http://``; every one is
  rewritten to ``https://`` before use.
* **Fetch from an unexpected host.** The manifest is fetched from GitHub and is
  therefore only as trustworthy as that file; an allowlist keeps a compromised or
  mistaken entry from turning into a request to somewhere arbitrary.
* **Download unbounded data.** ``reddit-corpus`` is tens of gigabytes. The size is
  checked against ``Content-Length`` up front *and* enforced while streaming,
  since ``Content-Length`` is a claim, not a guarantee.
* **Guess at dynamic corpus names.** ``subreddit-<name>``, ``wikiconv-<lang>-<year>``
  and ``supreme-<year>`` are not in the manifest — upstream computes their URLs
  from sharded index files. Rather than reimplement that and get it subtly wrong,
  these raise with instructions to fetch via ``convokit`` and point Potato at the
  extracted directory.

Upstream publishes no checksums, so downloads cannot be integrity-verified beyond
HTTPS. That is stated in the docs rather than papered over.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from .reader import ConvoKitReadError, resolve_corpus_dir

logger = logging.getLogger(__name__)

__all__ = [
    "ALLOWED_HOSTS",
    "MANIFEST_URL",
    "ConvoKitDownloadError",
    "default_data_dir",
    "download_corpus",
    "fetch_manifest",
    "list_corpora",
    "resolve",
]

MANIFEST_URL = (
    "https://raw.githubusercontent.com/CornellNLP/ConvoKit/master/download_config.json"
)

#: Hosts we will fetch from. Cornell's corpus server and GitHub raw.
ALLOWED_HOSTS = frozenset(
    {"zissou.infosci.cornell.edu", "raw.githubusercontent.com", "github.com"}
)

#: Default ceiling on a single corpus download. reddit-corpus is far larger than
#: this; that is deliberate, and ``--max-download-bytes`` raises it.
DEFAULT_MAX_BYTES = 4 * 1024 * 1024 * 1024

#: How long a cached copy of the manifest stays fresh.
MANIFEST_TTL_SECONDS = 24 * 60 * 60

#: Name prefixes upstream resolves dynamically rather than through the manifest.
_DYNAMIC_PREFIXES = ("subreddit-", "wikiconv-", "supreme-")


class ConvoKitDownloadError(Exception):
    """Raised when a corpus cannot be fetched."""


def default_data_dir() -> str:
    """Where corpora are cached.

    ``$CONVOKIT_DATA_DIR`` wins; then ``data_directory`` from ConvoKit's own
    ``~/.convokit/config.yml``; then ConvoKit's default. Reading their config is
    what makes the cache genuinely shared rather than merely co-located.
    """
    env = os.environ.get("CONVOKIT_DATA_DIR")
    if env:
        return os.path.expanduser(env)

    config_path = os.path.expanduser("~/.convokit/config.yml")
    if os.path.isfile(config_path):
        try:
            import yaml

            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            configured = config.get("data_directory")
            if configured:
                return os.path.expanduser(str(configured))
        except Exception as exc:  # noqa: BLE001 - a broken config is not fatal
            logger.debug("Could not read %s (%s); using the default", config_path, exc)

    return os.path.expanduser("~/.convokit/saved-corpora")


def _force_https(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme in ("http", ""):
        parsed = parsed._replace(scheme="https")
    return urllib.parse.urlunsplit(parsed)


def _check_host(url: str, extra_hosts: Tuple[str, ...] = ()) -> str:
    """Rewrite to HTTPS and reject hosts outside the allowlist."""
    url = _force_https(url)
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in ALLOWED_HOSTS and host not in extra_hosts:
        raise ConvoKitDownloadError(
            f"Refusing to fetch from unexpected host '{host}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_HOSTS))}. "
            "Pass --allow-host to override."
        )
    return url


def _manifest_cache_path(data_dir: str) -> str:
    return os.path.join(data_dir, ".potato-convokit-manifest.json")


def fetch_manifest(
    *,
    data_dir: Optional[str] = None,
    refresh: bool = False,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Return ConvoKit's ``download_config.json``, cached for a day.

    A stale cached copy is preferred over a hard failure when the network is
    unavailable — being able to read an already-downloaded corpus matters more
    than having today's manifest.
    """
    data_dir = data_dir or default_data_dir()
    cache_path = _manifest_cache_path(data_dir)

    if not refresh and os.path.isfile(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < MANIFEST_TTL_SECONDS:
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass   # fall through and refetch

    url = _check_host(MANIFEST_URL)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as exc:
        if os.path.isfile(cache_path):
            logger.warning(
                "Could not refresh the ConvoKit manifest (%s); using the cached copy.",
                exc,
            )
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        raise ConvoKitDownloadError(
            f"Could not fetch the ConvoKit corpus manifest from {url}: {exc}"
        ) from exc

    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError as exc:
        logger.debug("Could not cache the manifest: %s", exc)

    return payload


def list_corpora(
    *, data_dir: Optional[str] = None, refresh: bool = False
) -> Dict[str, str]:
    """Corpus name -> download URL, from the manifest."""
    manifest = fetch_manifest(data_dir=data_dir, refresh=refresh)
    urls = manifest.get("DatasetURLs") or {}
    out: Dict[str, str] = {}
    for name, url in urls.items():
        # A few entries are lists of shard URLs; show the first.
        if isinstance(url, list):
            url = url[0] if url else ""
        out[str(name)] = _force_https(str(url))
    return out


def corpus_versions(*, data_dir: Optional[str] = None) -> Dict[str, int]:
    manifest = fetch_manifest(data_dir=data_dir)
    versions = manifest.get("cur_version") or {}
    return {str(k): v for k, v in versions.items() if isinstance(v, int)}


def _reject_dynamic(name: str) -> None:
    for prefix in _DYNAMIC_PREFIXES:
        if name.startswith(prefix):
            raise ConvoKitDownloadError(
                f"'{name}' is one of ConvoKit's dynamically-resolved corpora "
                f"('{prefix}*'), whose download URL is computed from sharded index "
                "files rather than listed in the manifest. Potato does not "
                "reimplement that. Fetch it with ConvoKit itself:\n"
                f"    python -c \"from convokit import download; "
                f"print(download('{name}'))\"\n"
                "then point Potato at the printed directory:\n"
                f"    potato convokit /path/to/{name} -o data/{name}.jsonl"
            )


def _installed_version(corpus_dir: str) -> Optional[int]:
    index_path = os.path.join(corpus_dir, "index.json")
    if not os.path.isfile(index_path):
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            version = json.load(f).get("version")
    except (OSError, ValueError):
        return None
    return version if isinstance(version, int) else None


def download_corpus(
    name: str,
    *,
    data_dir: Optional[str] = None,
    force: bool = False,
    refresh: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: int = 300,
    allow_hosts: Tuple[str, ...] = (),
    quiet: bool = False,
) -> str:
    """Download ``name`` if needed and return the extracted corpus directory."""
    _reject_dynamic(name)

    data_dir = data_dir or default_data_dir()
    target = os.path.join(data_dir, name)

    if os.path.isdir(target) and not force:
        try:
            corpus_dir = resolve_corpus_dir(target)
        except ConvoKitReadError:
            corpus_dir = None
        if corpus_dir:
            _warn_on_version_drift(name, corpus_dir, data_dir)
            if not quiet:
                logger.info("Using cached corpus at %s", corpus_dir)
            return corpus_dir

    urls = list_corpora(data_dir=data_dir, refresh=refresh)
    if name not in urls:
        close = sorted(n for n in urls if name.lower() in n.lower())
        hint = f" Did you mean: {', '.join(close[:5])}?" if close else ""
        raise ConvoKitDownloadError(
            f"Unknown corpus '{name}'. Run 'potato convokit --list-corpora' to see "
            f"the {len(urls)} available names.{hint}"
        )

    url = _check_host(urls[name], allow_hosts)
    os.makedirs(data_dir, exist_ok=True)
    zip_path = os.path.join(data_dir, f"{name}.zip")
    part_path = zip_path + ".part"

    if not quiet:
        logger.info("Downloading %s from %s", name, url)
    _stream_download(url, part_path, max_bytes=max_bytes, timeout=timeout, quiet=quiet)
    os.replace(part_path, zip_path)

    if os.path.isdir(target) and force:
        shutil.rmtree(target)

    try:
        corpus_dir = resolve_corpus_dir(zip_path, extract_to=target)
    except ConvoKitReadError as exc:
        raise ConvoKitDownloadError(
            f"Downloaded '{name}' but it does not contain a ConvoKit corpus: {exc}"
        ) from exc

    _warn_on_version_drift(name, corpus_dir, data_dir)
    return corpus_dir


def _warn_on_version_drift(name: str, corpus_dir: str, data_dir: str) -> None:
    installed = _installed_version(corpus_dir)
    if installed is None:
        return
    try:
        latest = corpus_versions(data_dir=data_dir).get(name)
    except ConvoKitDownloadError:
        return
    if latest is not None and installed < latest:
        logger.warning(
            "Cached copy of '%s' is version %s but %s is current. "
            "Pass --force-download to replace it.",
            name,
            installed,
            latest,
        )


def _stream_download(
    url: str, dest: str, *, max_bytes: int, timeout: int, quiet: bool
) -> None:
    """Stream ``url`` to ``dest``, enforcing ``max_bytes`` as it goes."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > max_bytes:
                        raise ConvoKitDownloadError(
                            f"'{url}' is {int(declared)} bytes, over the "
                            f"{max_bytes}-byte limit. Raise --max-download-bytes "
                            "if that is genuinely what you want."
                        )
                except ValueError:
                    pass

            written = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    written += len(chunk)
                    # Content-Length is a claim; enforce the cap for real too.
                    if written > max_bytes:
                        f.close()
                        _unlink(dest)
                        raise ConvoKitDownloadError(
                            f"Download from '{url}' exceeded the {max_bytes}-byte "
                            "limit and was aborted."
                        )
                    f.write(chunk)
    except ConvoKitDownloadError:
        _unlink(dest)
        raise
    except (urllib.error.URLError, OSError) as exc:
        _unlink(dest)
        raise ConvoKitDownloadError(f"Could not download '{url}': {exc}") from exc

    if not quiet:
        logger.info("Downloaded %s bytes", written)


def _unlink(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def resolve(
    spec: str,
    *,
    data_dir: Optional[str] = None,
    allow_download: bool = True,
    **download_kwargs: Any,
) -> str:
    """Turn a corpus name, directory, or zip into a corpus directory.

    A path that exists on disk always wins over a manifest name, so a local
    directory that happens to share a corpus name is never shadowed by a download.
    """
    expanded = os.path.expanduser(spec)
    if os.path.exists(expanded):
        return resolve_corpus_dir(expanded)

    if os.sep in spec or spec.endswith(".zip"):
        raise ConvoKitReadError(f"No such corpus path: '{spec}'")

    if not allow_download:
        raise ConvoKitDownloadError(
            f"'{spec}' is not a local path and --no-download was given. "
            "Remove --no-download, or pass the path to an extracted corpus."
        )

    return download_corpus(spec, data_dir=data_dir, **download_kwargs)
