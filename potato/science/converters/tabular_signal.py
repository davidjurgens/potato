"""Sensor data in CSV or Parquet: a time column and one column per channel.

* **Time column**: ``time_column`` when given; otherwise the first column
  named ``time``, ``t``, ``timestamp``, ``seconds``, ``sec``, ``time_s``,
  ``datetime``, ``mjd`` or ``jd`` (any case); otherwise the first column.
  Numbers are used as they are (seconds, or whatever unit the file uses).
  Date-time text (ISO 8601) becomes seconds since the first row, and that
  first time becomes the recording's ``start_time``.
* **Channels**: every other numeric column, or the ``channels`` list. A unit
  in the header (``ax (m/s^2)`` or ``ax [g]``) becomes the channel's unit.
  Empty cells and ``NaN`` are missing samples.
* **Regular or not**: when every time step is within 0.1% of the median step,
  the channel is regular with ``sampling_rate = 1 / step``; otherwise each
  sample keeps its own time (light curves, event-driven sensors). Rows must
  be in time order.

Not registered in the shared converter table under ``.csv`` / ``.parquet``,
which are too generic for every display to treat as a signal: the
``time_series`` display calls :func:`read_csv_signal` and
:func:`read_parquet_signal` itself. Parquet needs ``pyarrow``
(``pip install 'potato-annotation[signals]'``).

The whole table is loaded into memory, so files are limited to
``max_bytes`` (256 MB by default).
"""

from __future__ import annotations

import os
import re
from typing import Any, List, Optional, Sequence

from potato.science.signals import InMemoryRecording, SignalError

DEFAULT_MAX_BYTES = 256 * 1024 * 1024
_TIME_NAMES = ("time", "t", "timestamp", "seconds", "sec", "time_s", "datetime", "mjd", "jd")
_UNIT = re.compile(r"^\s*(.*?)\s*[\(\[]\s*([^\)\]]*?)\s*[\)\]]\s*$")


def _split_unit(header: str):
    m = _UNIT.match(str(header))
    if m and m.group(1):
        return m.group(1), m.group(2)
    return str(header).strip(), ""


def _check_size(path: str, max_bytes: int) -> None:
    size = os.path.getsize(path)
    if size > max_bytes:
        raise SignalError(f"{os.path.basename(path)} is {size / 1e6:.0f} MB, over the "
                          f"{max_bytes / 1e6:.0f} MB limit for CSV/Parquet signals; "
                          f"convert it to EDF, which is read a window at a time")


def from_frame(df, fmt: str, time_column: Optional[str] = None,
               channels: Optional[Sequence[str]] = None) -> InMemoryRecording:
    """A recording from a pandas DataFrame (CSV and Parquet share this)."""
    import numpy as np
    import pandas as pd
    if df.shape[0] == 0 or df.shape[1] < 2:
        raise SignalError("the table needs a time column, at least one channel column "
                          "and at least one row")
    cols = [str(c) for c in df.columns]
    df.columns = cols
    if time_column:
        if time_column not in cols:
            raise SignalError(f"time_column '{time_column}' is not a column "
                              f"(columns: {', '.join(cols)})")
        tcol = time_column
    else:
        by_name = {_split_unit(c)[0].lower(): c for c in cols}
        tcol = next((by_name[n] for n in _TIME_NAMES if n in by_name), cols[0])
    raw_t = df[tcol]
    start_time = None
    if pd.api.types.is_numeric_dtype(raw_t):
        t = raw_t.to_numpy(dtype=np.float64)
    else:
        parsed = pd.to_datetime(raw_t, errors="coerce", utc=False)
        if parsed.isna().any():
            bad = raw_t[parsed.isna()].iloc[0]
            raise SignalError(f"time column '{tcol}': {bad!r} is neither a number nor a date-time")
        start_time = parsed.iloc[0].isoformat()
        t = (parsed - parsed.iloc[0]).dt.total_seconds().to_numpy(dtype=np.float64)
    if not np.all(np.isfinite(t)):
        raise SignalError(f"time column '{tcol}' has empty or non-numeric cells")
    if t.size > 1 and np.any(np.diff(t) < 0):
        raise SignalError(f"time column '{tcol}' is not in ascending order; sort the rows by time")
    if channels:
        missing = [c for c in channels if c not in cols]
        if missing:
            raise SignalError(f"channel column(s) {', '.join(missing)} not found "
                              f"(columns: {', '.join(cols)})")
        chan_cols = list(channels)
    else:
        chan_cols = [c for c in cols if c != tcol and pd.api.types.is_numeric_dtype(df[c])]
    if not chan_cols:
        raise SignalError("no numeric channel columns besides the time column")
    regular_fs = None
    if t.size > 2:
        steps = np.diff(t)
        med = float(np.median(steps))
        if med > 0 and np.all(np.abs(steps - med) <= 1e-3 * med):
            regular_fs = 1.0 / med
    rec = InMemoryRecording(fmt)
    rec.start_time = start_time
    for c in chan_cols:
        try:
            v = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=np.float64)
        except (TypeError, ValueError):
            raise SignalError(f"column '{c}' is not numeric")
        name, unit = _split_unit(c)
        if regular_fs:
            rec.add_channel(name, v, unit=unit, sampling_rate=regular_fs, t0=float(t[0]))
        else:
            rec.add_channel(name, v, unit=unit, times=t)
    return rec


def read_csv_signal(path: str, time_column: Optional[str] = None,
                    channels: Optional[Sequence[str]] = None,
                    max_bytes: int = DEFAULT_MAX_BYTES) -> InMemoryRecording:
    """Read a CSV (or TSV, by extension) of sensor data."""
    import pandas as pd
    _check_size(path, max_bytes)
    sep = "\t" if path.lower().endswith((".tsv", ".tab")) else ","
    try:
        df = pd.read_csv(path, sep=sep, comment="#")
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as e:
        raise SignalError(f"could not parse {os.path.basename(path)} as CSV: {e}")
    return from_frame(df, "csv", time_column=time_column, channels=channels)


def read_parquet_signal(path: str, time_column: Optional[str] = None,
                        channels: Optional[Sequence[str]] = None,
                        max_bytes: int = DEFAULT_MAX_BYTES) -> InMemoryRecording:
    """Read a Parquet table of sensor data (needs pyarrow)."""
    _check_size(path, max_bytes)
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        from potato.science.converters import ConverterUnavailable
        raise ConverterUnavailable(
            "Reading Parquet needs pyarrow, which is not installed. "
            "Install it with: pip install 'potato-annotation[signals]'") from e
    try:
        table = pq.read_table(path)
    except Exception as e:     # pyarrow raises ArrowInvalid and OSError subclasses
        raise SignalError(f"could not read {os.path.basename(path)} as Parquet: {e}")
    return from_frame(table.to_pandas(), "parquet", time_column=time_column, channels=channels)
