"""Spectrogram boxes as image boxes, for the detection trainers.

A ``spectrogram_annotation`` answer is boxes in seconds and hertz. At bundle
time each recording is rendered as a spectrogram image the way the widget
draws it: a linear frequency axis from the scheme's ``min_freq`` (bottom) to
``max_freq`` or the Nyquist frequency (top), ``fft_size`` samples per frame,
log magnitude, and time across at ``pixels_per_second``. Each box becomes an
image box on it (a time-only box spans the band), so the detectors train on
calls as on any objects. A long recording is a wide image, which tiling
(``training/tiling.py``) cuts into windows and stitches back.

Predicted image boxes are turned back into ``start_s``, ``end_s``,
``low_hz`` and ``high_hz`` for the widget's prefill.

numpy and Pillow, on the machine that builds the bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Sequence

__all__ = ["render", "boxes_to_objects", "objects_to_boxes", "spectrogram_rows",
           "finalize_file", "PIXELS_PER_SECOND"]

PIXELS_PER_SECOND = 100
HEIGHT = 256


def render(audio_path: str, dest: str, scheme: Dict[str, Any],
           pixels_per_second: int = PIXELS_PER_SECOND, height: int = HEIGHT) -> Dict[str, Any]:
    """Write the spectrogram PNG; returns ``{duration_s, min_hz, max_hz,
    width, height}``, what maps pixels to time and frequency."""
    import numpy
    import soundfile
    from PIL import Image
    samples, rate = soundfile.read(audio_path, dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    duration = len(samples) / float(rate)
    fft = int(scheme.get("fft_size", 1024))
    nyquist = rate / 2.0
    max_hz = min(float(scheme["max_freq"]), nyquist) if scheme.get("max_freq") else nyquist
    min_hz = max(0.0, min(float(scheme.get("min_freq") or 0), max_hz - 1))
    width = max(1, int(round(duration * pixels_per_second)))
    hop = max(1, len(samples) // width)
    window = numpy.hanning(fft).astype("float32")
    padded = numpy.pad(samples, (fft // 2, fft + hop * width))
    frames = numpy.lib.stride_tricks.sliding_window_view(padded, fft)[::hop][:width]
    spectrum = numpy.abs(numpy.fft.rfft(frames * window, axis=1)).T   # bins x width
    freqs = numpy.fft.rfftfreq(fft, 1.0 / rate)
    rows = numpy.linspace(max_hz, min_hz, height)               # top is high
    # Linear in frequency, as the widget draws it: each image row is the
    # nearest FFT bin's magnitude, interpolated.
    positions = numpy.interp(rows, freqs, numpy.arange(len(freqs)))
    lower = numpy.floor(positions).astype(int)
    upper = numpy.minimum(lower + 1, len(freqs) - 1)
    weight = (positions - lower)[:, None]
    image = spectrum[lower] * (1 - weight) + spectrum[upper] * weight
    image = 20 * numpy.log10(image + 1e-6)
    low, high = numpy.percentile(image, (5, 99.5))
    scaled = (numpy.clip((image - low) / ((high - low) or 1.0), 0, 1) * 255).astype("uint8")
    Image.fromarray(scaled).convert("RGB").save(dest)
    return {"duration_s": duration, "min_hz": min_hz, "max_hz": max_hz,
            "width": width, "height": height}


def boxes_to_objects(boxes: Sequence[Dict[str, Any]], meta: Dict[str, Any]
                     ) -> List[Dict[str, Any]]:
    """Boxes in seconds and hertz as normalized image boxes, clipped to the
    recording and its band; a box wholly outside either is left out."""
    duration, low, high = meta["duration_s"], meta["min_hz"], meta["max_hz"]
    span = (high - low) or 1.0
    out = []
    for box in boxes:
        try:
            start, end = float(box["start_s"]), float(box["end_s"])
        except (KeyError, TypeError, ValueError):
            continue
        f0 = low if box.get("low_hz") is None else max(low, min(high, float(box["low_hz"])))
        f1 = high if box.get("high_hz") is None else max(low, min(high, float(box["high_hz"])))
        # The recording's own extent: a box past its end (an annotation
        # against a longer copy, or a slip) is cut there, and one wholly
        # outside it is not on this image at all.
        start, end = max(0.0, start), min(float(duration or 0), end)
        if end <= start or not duration or f1 <= f0:
            continue
        out.append({"type": "bbox", "label": box.get("label"), "coordinates": {
            "x": start / duration, "y": (high - f1) / span,
            "width": (end - start) / duration, "height": (f1 - f0) / span}})
    return out


def objects_to_boxes(objects: Sequence[Dict[str, Any]], meta: Dict[str, Any],
                     model_version: str = "") -> List[Dict[str, Any]]:
    """Normalized image boxes as spectrogram boxes, marked as the model's."""
    duration, low, high = meta["duration_s"], meta["min_hz"], meta["max_hz"]
    span = high - low
    out = []
    for obj in objects:
        coords = obj.get("coordinates") or {}
        if obj.get("type") != "bbox":
            continue
        try:
            x, y = float(coords["x"]), float(coords["y"])
            w, h = float(coords["width"]), float(coords["height"])
        except (KeyError, TypeError, ValueError):
            continue
        box = {"start_s": round(x * duration, 4), "end_s": round((x + w) * duration, 4),
               "low_hz": round(high - (y + h) * span, 1), "high_hz": round(high - y * span, 1),
               "label": obj.get("label"), "source": "ai"}
        if model_version:
            box["ai_model"] = model_version
        if isinstance(obj.get("confidence"), (int, float)):
            box["confidence"] = obj["confidence"]
        out.append(box)
    return out


def spectrogram_rows(rows: Sequence[Dict[str, Any]], media_dir: str, schema_name: str,
                     scheme: Dict[str, Any], pixels_per_second: int = PIXELS_PER_SECOND,
                     problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Each row with its recording rendered and its boxes as image boxes;
    the mapping back is on the row as ``spectrogram``."""
    problems = problems if problems is not None else []
    out = []
    for row in rows:
        media = row.get("media")
        path = os.path.join(media_dir, media) if media and not str(media).startswith(
            ("http://", "https://")) else None
        if not path or not os.path.exists(path):
            problems.append("%s: no local audio" % row.get("instance_id"))
            continue
        folder = os.path.join(media_dir, "spectrograms")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, hashlib.sha1(
            os.path.realpath(path).encode()).hexdigest()[:16] + ".png")
        try:
            meta = render(path, dest, scheme, pixels_per_second)
        except Exception as exc:  # noqa: BLE001
            problems.append("%s: %s" % (row.get("instance_id"), exc))
            continue
        converted = dict(row, media=os.path.join("spectrograms", os.path.basename(dest)),
                         spectrogram=meta)
        boxes = (row.get("targets") or {}).get(schema_name)
        if isinstance(boxes, list):
            converted["targets"] = dict(row["targets"], **{
                schema_name: boxes_to_objects(boxes, meta)})
        out.append(converted)
    return out


def finalize_file(bundle, path: str, model_version: str = "") -> int:
    """Rewrite *path* with each spectrogram item's image boxes as boxes in
    seconds and hertz, after scoring (which compares image boxes). Returns
    the number of records written, or 0 when the bundle has none."""
    meta: Dict[str, Dict[str, Any]] = {}
    for split in list((bundle.manifest.get("splits") or {})):
        for row in bundle.read_split(split):
            if row.get("spectrogram") and not row.get("parent_id"):
                meta[str(row["instance_id"])] = row["spectrogram"]
    from potato.training.tiling import _parents
    for parent in _parents(bundle).values():
        if parent.get("spectrogram"):
            meta[str(parent["instance_id"])] = parent["spectrogram"]
    if not meta or not os.path.isfile(path):
        return 0
    records = []
    with open(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            found = meta.get(str(record.get("instance_id")))
            if found is not None and isinstance(record.get("payload"), list):
                record["payload"] = objects_to_boxes(record["payload"], found, model_version)
                if not record["payload"]:
                    continue
            records.append(record)
    with open(path, "w") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)
