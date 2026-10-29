"""Opening signal files named in item data, with caching and path checks.

An item field for a ``time_series`` display holds either

* a **file reference**, resolved like other media: first inside
  ``media_directory`` (``media/`` and ``/media/`` prefixes accepted), then
  relative to ``task_dir`` through ``validate_path_security``. Absolute
  paths, ``..`` escapes and URLs are refused. The extension picks the
  reader (:data:`READERS`); or
* an **inline object** ``{sampling_rate, start_time, channels: [{name, unit,
  data}]}`` for small signals (see :func:`potato.science.signals.from_inline`),
  or a JSON file holding that object.

Opened recordings are kept in a small LRU keyed by the file's real path,
size and modification time, so the min/max pyramid is built once per file and
an edited file is reopened. Window responses have their own LRU.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Callable, Dict, Optional, Tuple

from potato.science.signals import (LRU, SignalError, SignalRecording, from_inline,
                                    normalize_annotations, window)

logger = logging.getLogger(__name__)

#: Largest JSON signal file read (inline shape).
MAX_JSON_BYTES = 50 * 1024 * 1024

_RECORDINGS = LRU(8)
_WINDOWS = LRU(256)


def _read_edf(path, opts):
    from potato.science.converters.edf import read_edf
    return read_edf(path, max_bytes=opts["max_bytes"])


def _read_wfdb(path, opts):
    from potato.science.converters.wfdb_record import read_wfdb
    return read_wfdb(path, annotation_extension=opts.get("annotation_extension") or None,
                     max_bytes=opts["max_bytes"])


def _read_csv(path, opts):
    from potato.science.converters.tabular_signal import read_csv_signal
    return read_csv_signal(path, time_column=opts.get("time_column"),
                           max_bytes=min(opts["max_bytes"], 256 * 1024 ** 2))


def _read_parquet(path, opts):
    from potato.science.converters.tabular_signal import read_parquet_signal
    return read_parquet_signal(path, time_column=opts.get("time_column"),
                               max_bytes=min(opts["max_bytes"], 256 * 1024 ** 2))


def _read_json(path, opts):
    size = os.path.getsize(path)
    if size > MAX_JSON_BYTES:
        raise SignalError(f"{os.path.basename(path)} is {size / 1e6:.0f} MB, over the "
                          f"{MAX_JSON_BYTES / 1e6:.0f} MB limit for JSON signals")
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
    except ValueError as e:
        raise SignalError(f"{os.path.basename(path)} is not valid JSON: {e}")
    rec = from_inline(value)
    rec.format = "json"
    return rec


#: extension -> reader(path, options). EDF and BDF need no library; WFDB
#: needs ``wfdb`` and Parquet ``pyarrow`` (the ``signals`` extra).
READERS: Dict[str, Callable[[str, Dict[str, Any]], SignalRecording]] = {
    ".edf": _read_edf, ".bdf": _read_edf,
    ".hea": _read_wfdb,
    ".csv": _read_csv, ".tsv": _read_csv,
    ".parquet": _read_parquet, ".pq": _read_parquet,
    ".json": _read_json,
}


def reader_options(options: Dict[str, Any]) -> Dict[str, Any]:
    mb = options.get("max_file_mb") or 2048
    return {
        "max_bytes": int(float(mb) * 1024 * 1024),
        "time_column": options.get("time_column"),
        "annotation_extension": options.get("annotation_extension", "atr"),
    }


def resolve_signal_path(config: Dict[str, Any], ref: Any) -> str:
    """The file a reference names, inside media_directory or task_dir."""
    from potato.media.paths import resolve_media_url
    text = str(ref or "").strip()
    if not text:
        raise SignalError("this item has no signal file")
    if text.startswith(("http://", "https://", "//", "data:")):
        raise SignalError("signal files must be local; download the file into the "
                          "media directory and name it relative to that")
    path = resolve_media_url(config, text, context="Signal file")
    if path is not None:
        return path
    if os.path.isabs(text):
        raise SignalError(f"'{text}' is an absolute path; name the signal file relative "
                          f"to media_directory or the task directory")
    from potato.server_utils.config_module import ConfigSecurityError, validate_path_security
    task_dir = config.get("task_dir") or "."
    try:
        path = validate_path_security(os.path.join(task_dir, text), task_dir)
    except ConfigSecurityError:
        raise SignalError(f"'{text}' is outside the task directory; refused")
    if not os.path.isfile(path):
        raise SignalError(f"signal file '{text}' was not found in media_directory "
                          f"or the task directory")
    return path


def _ext(path: str) -> str:
    return os.path.splitext(path.lower())[1]


def open_signal(config: Dict[str, Any], value: Any,
                options: Optional[Dict[str, Any]] = None) -> Tuple[str, SignalRecording]:
    """``(cache key, recording)`` for an item field's value."""
    opts = reader_options(options or {})
    if isinstance(value, dict):
        blob = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
        key = "inline:" + hashlib.sha1(blob).hexdigest()
        rec = _RECORDINGS.get(key)
        if rec is None:
            rec = from_inline(value)
            _RECORDINGS.put(key, rec)
        return key, rec
    if isinstance(value, list):
        raise SignalError("a signal field holds a file name or an object with a channels list, "
                          "not a list")
    path = resolve_signal_path(config, value)
    reader = READERS.get(_ext(path))
    if reader is None:
        raise SignalError(f"cannot read '{os.path.basename(path)}' as a signal; supported: "
                          f"{', '.join(sorted(READERS))}")
    st = os.stat(path)
    key = f"{os.path.realpath(path)}|{st.st_size}|{st.st_mtime_ns}|" + json.dumps(opts, sort_keys=True)
    rec = _RECORDINGS.get(key)
    if rec is None:
        rec = reader(path, opts)
        _RECORDINGS.put(key, rec)
    return key, rec


def channel_indices(rec: SignalRecording, wanted) -> list:
    """Indices for ``wanted`` (names), in that order; all channels if None."""
    if not wanted:
        return list(range(len(rec.channels)))
    out = []
    for name in wanted:
        try:
            out.append(rec.channel_index(name))
        except KeyError:
            known = ", ".join(c.name for c in rec.channels)
            raise SignalError(f"channel '{name}' is not in this recording (channels: {known})")
    return out


def cached_window(key: str, rec: SignalRecording, start: float, end: float, px: int,
                  chans) -> Dict[str, Any]:
    wkey = (key, tuple(chans), round(start, 6), round(end, 6), int(px))
    hit = _WINDOWS.get(wkey)
    if hit is not None:
        return hit
    out = window(rec, start, end, px, chans)
    _WINDOWS.put(wkey, out)
    return out


def ranges(rec: SignalRecording, chans) -> Dict[str, list]:
    return {rec.channels[c].name: [round(v, 6) for v in rec.value_range(c)] for c in chans}


def clear_caches() -> None:
    _RECORDINGS.clear()
    _WINDOWS.clear()


# ---------------------------------------------------------------------------
# Pre-annotations
# ---------------------------------------------------------------------------

def preannotations(config: Dict[str, Any], scheme: Dict[str, Any], item: Dict[str, Any],
                   rec: SignalRecording) -> Dict[str, Any]:
    """The pre-annotations an interval_label scheme starts from.

    The file's own annotations (EDF+ TALs, WFDB ``.atr``, inline
    ``annotations``) when ``pre_annotations`` is on (the default), plus
    whatever ``preannotation_field`` names: a BIDS ``*_events.tsv`` file, or
    the stored shape inline. Labels are renamed through
    ``preannotation_labels`` (a label mapped to null is dropped), then kept
    only if the scheme declares it as that kind; a channel the recording does
    not have becomes null (all channels).
    """
    out = {"intervals": [], "events": []}
    if scheme.get("pre_annotations", True):
        out["intervals"].extend(dict(a) for a in rec.annotations.get("intervals") or [])
        out["events"].extend(dict(a) for a in rec.annotations.get("events") or [])
    field = scheme.get("preannotation_field")
    if field and item.get(field) not in (None, ""):
        value = item[field]
        if isinstance(value, (dict, list)):
            extra = normalize_annotations(value, where=field, strict=False)
        else:
            from potato.science.converters.bids_events import read_bids_events
            extra = read_bids_events(resolve_signal_path(config, value))
        out["intervals"].extend(extra["intervals"])
        out["events"].extend(extra["events"])
    rename = scheme.get("preannotation_labels") or {}
    names = {c.name for c in rec.channels}
    # Only labels the scheme declares, as the kind it declares them. A second
    # scheme on the same recording was otherwise handed the file's sleep
    # stages, which it has no button for, and they reached the export.
    declared = None
    if scheme.get("labels"):
        from potato.server_utils.schemas.interval_label import labels_of
        declared = {"intervals": set(), "events": set()}
        for lab in labels_of(scheme):
            declared["events" if lab["kind"] == "event" else "intervals"].add(lab["name"])
    for kind in ("intervals", "events"):
        kept = []
        for a in out[kind]:
            if a["label"] in rename and rename[a["label"]] is None:
                continue        # mapped to null: dropped
            a["label"] = str(rename.get(a["label"], a["label"]))
            if declared is not None and a["label"] not in declared[kind]:
                continue
            a["source"] = "file"
            if a.get("channel") and a["channel"] not in names:
                a["channel"] = None
            kept.append(a)
        out[kind] = kept
    out = normalize_annotations(out, strict=False)
    return out
