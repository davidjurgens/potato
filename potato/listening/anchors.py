"""
Low-pass anchors for MUSHRA, cut from the reference.

BS.1534-3 asks for a low anchor (the reference low-pass filtered at 3.5 kHz)
and recommends a mid anchor at 7 kHz. They are made here from a PCM WAV
reference with a brick-wall filter in the frequency domain (a short cosine
taper at the edge keeps it from ringing audibly), written at the reference's
own sample rate and width, and cached under the task directory so each is
made once.

Only PCM WAV references are supported; for anything else put the anchor
files in the data as ordinary stimuli.
"""

from __future__ import annotations

import hashlib
import os
import wave

import numpy as np

TAPER_HZ = 200.0


def _read(path: str):
    with wave.open(path, "rb") as w:
        n_ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        data = v.astype(np.float64) / 8388608.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {width}")
    return data.reshape(-1, n_ch), rate, width


def _write(path: str, data, rate: int, width: int) -> None:
    data = np.clip(data, -1.0, 1.0 - 1e-9)
    if width == 1:
        raw = (data * 128.0 + 128.0).astype(np.uint8).tobytes()
    elif width == 2:
        raw = (data * 32768.0).astype("<i2").tobytes()
    elif width == 3:
        v = (data * 8388608.0).astype(np.int32).reshape(-1)
        v = np.where(v < 0, v + 0x1000000, v)
        raw = np.stack([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF], axis=1).astype(np.uint8).tobytes()
    else:
        raw = (data * 2147483648.0).astype("<i4").tobytes()
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(raw)
    os.replace(tmp, path)


def lowpass(data, rate: int, cutoff_hz: float):
    n = data.shape[0]
    spectrum = np.fft.rfft(data, axis=0)
    freqs = np.fft.rfftfreq(n, d=1.0 / rate)
    gain = np.ones_like(freqs)
    edge = (freqs > cutoff_hz - TAPER_HZ) & (freqs < cutoff_hz)
    gain[edge] = 0.5 * (1 + np.cos(np.pi * (freqs[edge] - (cutoff_hz - TAPER_HZ)) / TAPER_HZ))
    gain[freqs >= cutoff_hz] = 0.0
    return np.fft.irfft(spectrum * gain[:, None], n=n, axis=0)


def anchor_path(task_dir: str, reference_path: str, cutoff_hz: int) -> str:
    """The cached anchor for one reference file, made on first request."""
    st = os.stat(reference_path)
    key = hashlib.sha256(f"{os.path.realpath(reference_path)}|{st.st_size}|{st.st_mtime_ns}|{cutoff_hz}"
                         .encode()).hexdigest()[:24]
    cache = os.path.join(task_dir, ".potato_cache", "listening")
    os.makedirs(cache, exist_ok=True)
    out = os.path.join(cache, f"{key}-lp{cutoff_hz}.wav")
    if not os.path.exists(out):
        data, rate, width = _read(reference_path)
        if cutoff_hz >= rate / 2:
            raise ValueError(f"anchor cut-off {cutoff_hz} Hz is at or above the Nyquist "
                             f"frequency of a {rate} Hz reference")
        _write(out, lowpass(data, rate, cutoff_hz), rate, width)
    return out
