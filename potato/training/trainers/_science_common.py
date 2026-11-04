"""What peak-cnn, signal-cnn and episode-model share: reading a bundle row's
spectrum, signal or episode the way the annotation page read it, turning it
into a fixed-rate array, and the 1D convolutional blocks all three use.

Every reader is Potato's own (:mod:`potato.science.spectra`,
:mod:`potato.science.signal_store`, :mod:`potato.episodes`), so a file the
page could show is a file a model can train on, and one it could not is
refused with the same message.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.training.base import TrainerError


def _local(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.exists(str(path))


def science_of(row: Dict[str, Any]) -> Dict[str, Any]:
    value = row.get("science")
    return value if isinstance(value, dict) else {}


def has_input(row: Dict[str, Any], media: Optional[str]) -> bool:
    """Whether a row has a spectrum, signal or episode to read."""
    return "inline" in science_of(row) or _local(media)


# ---------------------------------------------------------------- spectra

def spectrum_of(row: Dict[str, Any], media: Optional[str]):
    """The row's spectrum: inline, or the linked file with the item's scan,
    index or block."""
    from potato.science.spectra import from_inline, read_file
    science = science_of(row)
    options = science.get("options") or {}
    if "inline" in science:
        return from_inline(science["inline"])
    if not _local(media):
        raise TrainerError("no spectrum file")
    selector = {k: options.get(k) for k in ("scan", "index", "block")}
    return read_file(media, selector, max_file_mb=1024, max_points=2_000_000)


def peak_direction(spectrum, options: Dict[str, Any]) -> str:
    """``max`` for peaks that point up, ``min`` for transmittance dips; the
    display's rule."""
    from potato.science.spectra import peaks_point_down
    direction = (options or {}).get("peak_direction") or "auto"
    if direction == "auto":
        return "min" if peaks_point_down(spectrum.y_units) else "max"
    return direction


def resample_spectrum(spectrum, length: int, direction: str):
    """``(grid x, y in 0..1 with peaks up)`` on *length* evenly spaced x."""
    import numpy
    x = numpy.asarray(spectrum.x, dtype="float64")
    y = numpy.asarray(spectrum.y, dtype="float64")
    if direction == "min":
        y = -y
    grid = numpy.linspace(float(x[0]), float(x[-1]), length) if len(x) > 1 else \
        numpy.full(length, float(x[0]))
    values = numpy.interp(grid, x, y) if len(x) > 1 else numpy.full(length, float(y[0]))
    if spectrum.sticks and len(x) > 1:
        # A stick spectrum is zero between its lines; interpolating drew
        # ramps between neighbours. Each line goes to its nearest grid point.
        values = numpy.full(length, float(y.min()))
        index = numpy.clip(numpy.round((x - grid[0]) / (grid[-1] - grid[0]) * (length - 1)
                                       ).astype(int), 0, length - 1)
        numpy.maximum.at(values, index, y)
    low, high = float(values.min()), float(values.max())
    values = (values - low) / (high - low) if high > low else numpy.zeros_like(values)
    return grid, values.astype("float32")


# ---------------------------------------------------------------- signals

def signal_of(row: Dict[str, Any], media: Optional[str]):
    """The row's recording: inline, or the linked file through the reader
    its extension picks."""
    from potato.science.signal_store import READERS, reader_options
    from potato.science.signals import from_inline
    science = science_of(row)
    options = science.get("options") or {}
    if "inline" in science:
        return from_inline(science["inline"])
    if not _local(media):
        raise TrainerError("no signal file")
    reader = READERS.get(os.path.splitext(str(media).lower())[1])
    if reader is None:
        raise TrainerError("cannot read %s as a signal" % os.path.basename(str(media)))
    return reader(media, reader_options(options))


def signal_channels(rec, wanted: Optional[Sequence[str]], limit: int) -> List[int]:
    """Indices of the channels to read: the display's, else every regular
    channel, at most *limit*."""
    if wanted:
        # The display lists a channel by name, or as {name, color}.
        wanted = [w.get("name") if isinstance(w, dict) else w for w in wanted]
        names = {c.name: i for i, c in enumerate(rec.channels)}
        chosen = [names[n] for n in wanted if isinstance(n, str) and n in names]
    else:
        chosen = [i for i, c in enumerate(rec.channels) if c.n_samples and c.sampling_rate]
    return chosen[:limit]


def signal_array(rec, channels: Sequence[int], rate: float):
    """``(times, array of channels x samples)`` resampled to *rate* Hz over
    the recording, each channel standardized. A gap (EDF+D) is filled by
    interpolation; the model sees a flat stretch."""
    import numpy
    start, end = rec.t_start, rec.t_end
    n = max(1, int((end - start) * rate))
    times = start + numpy.arange(n, dtype="float64") / rate
    out = numpy.zeros((len(channels), n), dtype="float32")
    for row, ch in enumerate(channels):
        count = rec.channels[ch].n_samples
        if not count:
            continue
        values = rec.read(ch, 0, count)
        stamps = rec.sample_times(ch, 0, count)
        if len(values) < 2:
            continue
        series = numpy.interp(times, stamps, values)
        series = (series - series.mean()) / (series.std() or 1.0)
        out[row] = numpy.clip(series, -20, 20)
    return times, out


# --------------------------------------------------------------- episodes

def episode_of(row: Dict[str, Any], media: Optional[str]):
    """The row's episode, read by the format its file is."""
    from potato.episodes.registry import read_episode
    science = science_of(row)
    options = science.get("options") or {}
    if not _local(media):
        raise TrainerError("no episode file")
    return read_episode(media, episode=options.get("episode", 0), fps=30.0)


def episode_array(episode, names: Optional[Sequence[str]] = None):
    """``(series names, frames x series array)``: each series standardized,
    non-finite samples 0. With *names*, those series in that order (a
    missing one is a column of zeros), so a model sees the columns it was
    trained on."""
    import numpy
    by_name = {s.name: s for s in episode.series}
    names = list(names) if names is not None else [s.name for s in episode.series]
    frames = max(int(episode.num_frames or 0),
                 max((len(s.values) for s in episode.series), default=0))
    out = numpy.zeros((max(frames, 1), len(names)), dtype="float32")
    for column, name in enumerate(names):
        series = by_name.get(name)
        if series is None:
            continue
        values = numpy.asarray([v if v is not None else numpy.nan for v in series.values],
                               dtype="float64")[:frames]
        finite = numpy.isfinite(values)
        if finite.any():
            mean, std = values[finite].mean(), values[finite].std() or 1.0
            values = numpy.where(finite, (values - mean) / std, 0.0)
        else:
            values = numpy.zeros_like(values)
        out[:len(values), column] = numpy.clip(values, -20, 20)
    return names, out


# ------------------------------------------------------------- intervals

def runs(labels: Sequence[Optional[str]], times: Sequence[float], step: float,
         confidences: Optional[Sequence[float]] = None) -> List[Dict[str, Any]]:
    """Per-frame labels as intervals: each run of one label from its first
    frame's time to its last frame's end. None is no label."""
    out: List[Dict[str, Any]] = []
    start = None
    for n, label in enumerate(list(labels) + [None]):
        if start is not None and (label != labels[start] or n == len(labels)):
            entry = {"start": round(float(times[start]), 6),
                     "end": round(float(times[n - 1]) + step, 6),
                     "label": labels[start]}
            if confidences is not None:
                entry["confidence"] = round(float(sum(confidences[start:n]) / (n - start)), 4)
            out.append(entry)
            start = None
        if start is None and n < len(labels) and label is not None:
            start = n
    return out


# ----------------------------------------------------------------- models

def inception_net(channels_in: int, width: int, depth: int, out: int,
                  kernels: Tuple[int, ...] = (9, 19, 39)):
    """InceptionTime, small: *depth* blocks of parallel convolutions with
    three kernel sizes and a max-pool branch, a residual every three blocks,
    and a per-step linear head (B x C x T in, B x out x T out)."""
    import torch
    from torch import nn

    class Block(nn.Module):
        def __init__(self, cin):
            super().__init__()
            bottleneck = width if cin > 1 else cin
            self.squeeze = nn.Conv1d(cin, bottleneck, 1, bias=False)
            self.convs = nn.ModuleList(nn.Conv1d(bottleneck, width, k, padding=k // 2,
                                                 bias=False) for k in kernels)
            self.pool = nn.Sequential(nn.MaxPool1d(3, stride=1, padding=1),
                                      nn.Conv1d(cin, width, 1, bias=False))
            self.norm = nn.BatchNorm1d(width * (len(kernels) + 1))

        def forward(self, x):
            z = self.squeeze(x)
            branches = [conv(z) for conv in self.convs] + [self.pool(x)]
            return torch.relu(self.norm(torch.cat(branches, dim=1)))

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            features = width * (len(kernels) + 1)
            self.blocks = nn.ModuleList()
            self.shortcuts = nn.ModuleList()
            cin = channels_in
            residual_in = channels_in
            for n in range(depth):
                self.blocks.append(Block(cin))
                cin = features
                if n % 3 == 2:
                    self.shortcuts.append(nn.Sequential(
                        nn.Conv1d(residual_in, features, 1, bias=False),
                        nn.BatchNorm1d(features)))
                    residual_in = features
            self.head = nn.Conv1d(features, out, 1)

        def forward(self, x):
            residual = x
            shortcut = iter(self.shortcuts)
            for n, block in enumerate(self.blocks):
                x = block(x)
                if n % 3 == 2:
                    x = torch.relu(x + next(shortcut)(residual))
                    residual = x
            return self.head(x)

    return Net()
