"""
Keeping a listening test blind.

The page is given opaque slot URLs (:mod:`potato.listening.routes`). Three
other channels would still name a slot's condition, and this module closes
them:

* the item record on the page (``#instance-json-data``) would hold the
  stimulus, reference and condition fields -- :func:`private_item_fields`
  lists them so the page-record strippers drop them;
* ``/media/<file>`` would serve the same files, so a participant could
  hash both and match them -- :func:`is_protected_media` lets that route
  refuse them;
* identical files would give identical bytes, ETags and Last-Modified
  headers, which answers an ABX trial (X is A or B) and finds the hidden
  reference -- :func:`padded_audio` adds a padding block of random length to
  each response, inside the container, so the audio is unchanged.

What this cannot do: the page decodes every slot to play it, so a
participant with the browser's developer tools can still compare the
decoded samples. Remote stimulus URLs are redirected to, which names them
in the network log. Both are documented.
"""

from __future__ import annotations

import logging
import os
import secrets
import struct
from typing import Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

_warned_formats: Set[str] = set()


def _schemes(config: dict) -> List[dict]:
    return [s for s in (config or {}).get("annotation_schemes") or []
            if isinstance(s, dict) and s.get("annotation_type") == "listening_test"]


def private_item_fields(config: dict) -> List[str]:
    """Item fields naming a listening test's files or conditions."""
    out: List[str] = []
    for scheme in _schemes(config):
        for key, default in (("stimuli_field", "stimuli"), ("reference_field", "reference"),
                             ("condition_field", "condition")):
            name = str(scheme.get(key) or default)
            if name not in out:
                out.append(name)
    return out


def _sources(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _sources(v)
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, dict):
                for key in ("url", "src", "file"):
                    if isinstance(v.get(key), str):
                        yield v[key]
            else:
                yield from _sources(v)


_protected_cache: dict = {"key": None, "paths": frozenset()}


def protected_media_paths(config: dict) -> frozenset:
    """Real paths of the local files any listening item names."""
    schemes = _schemes(config)
    if not schemes:
        return frozenset()
    from potato.item_state_management import get_item_state_manager
    from potato.media.paths import resolve_media_url
    try:
        ism = get_item_state_manager()
        ids = list(ism.get_instance_ids())
    except Exception:
        return frozenset()
    key = (id(ism), len(ids))
    if _protected_cache["key"] == key:
        return _protected_cache["paths"]
    fields = [(str(s.get("stimuli_field") or "stimuli"), str(s.get("reference_field") or "reference"))
              for s in schemes]
    paths: Set[str] = set()
    for iid in ids:
        try:
            item = ism.get_item(iid)
            data = item.get_data() if hasattr(item, "get_data") else dict(item)
        except Exception:
            continue
        for stim, ref in fields:
            for src in list(_sources(data.get(stim))) + list(_sources(data.get(ref))):
                path = resolve_media_url(config, src, context="Listening test")
                if path:
                    paths.add(os.path.realpath(path))
    _protected_cache.update(key=key, paths=frozenset(paths))
    return _protected_cache["paths"]


def is_protected_media(config: dict, path: str) -> bool:
    return bool(path) and os.path.realpath(path) in protected_media_paths(config)


def _pad_length() -> int:
    # Even, so a RIFF chunk needs no pad byte; wide enough that two responses
    # rarely share a length.
    return 2 * (32 + secrets.randbelow(4000))


def _pad_wav(data: bytes) -> Optional[bytes]:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos = 12
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"data":
            n = _pad_length()
            # An unknown chunk before `data`; readers skip chunks they do not know.
            chunk = b"potz" + struct.pack("<I", n) + secrets.token_bytes(n)
            out = data[:pos] + chunk + data[pos:]
            return out[:4] + struct.pack("<I", len(out) - 8) + out[8:]
        pos += 8 + size + (size & 1)
    return None


def _pad_flac(data: bytes) -> Optional[bytes]:
    if len(data) < 42 or data[:4] != b"fLaC":
        return None
    header = data[4]
    if header & 0x7F != 0:          # the first block must be STREAMINFO
        return None
    size = int.from_bytes(data[5:8], "big")
    end = 8 + size
    last = bool(header & 0x80)
    n = _pad_length()
    # PADDING block (type 1); it takes over the last-block flag if STREAMINFO had it.
    block = bytes([(0x80 if last else 0) | 1]) + n.to_bytes(3, "big") + b"\0" * n
    return b"fLaC" + bytes([header & 0x7F]) + data[5:end] + block + data[end:]


def _pad_mp3(data: bytes) -> Optional[bytes]:
    if not (data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)):
        return None
    n = _pad_length()
    # An ID3v2.4 tag holding only padding; decoders skip to the first frame.
    syncsafe = bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])
    return b"ID3\x04\x00\x00" + syncsafe + b"\0" * n + data


def padded_audio(path: str) -> bytes:
    """The file's bytes with a padding block of random length added inside the
    container (WAV, FLAC, MP3), so two slots holding the same file differ.
    Other formats are returned unchanged, with one warning per format."""
    with open(path, "rb") as f:
        data = f.read()
    for pad in (_pad_wav, _pad_flac, _pad_mp3):
        out = pad(data)
        if out is not None:
            return out
    ext = os.path.splitext(path)[1].lower() or "(none)"
    if ext not in _warned_formats:
        _warned_formats.add(ext)
        logger.warning("Listening test: %s files are sent unchanged, so two slots with the "
                       "same file have the same bytes. Use WAV, FLAC or MP3 for blind "
                       "comparisons.", ext)
    return data
