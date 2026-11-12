"""Which accelerator a trainer should use.

``model_training.device`` is ``auto``, ``cpu``, ``cuda`` (or ``cuda:N``) or
``mps``. ``auto`` picks CUDA, then Apple's Metal backend, then the CPU.

Only the training child calls :func:`resolve_device`, because answering the
question means importing torch, and the server process must not. When torch is
not installed the answer is ``cpu``: every trainer that can run without torch
runs on the CPU anyway.

A device that was asked for and is not there falls back to the CPU with a
warning instead of failing. The common case is a model fitted on a GPU host
and reused on a laptop, and refusing to load it there would be worse than
running it slowly.
"""

from __future__ import annotations

import importlib.util
from typing import Callable, Optional

__all__ = ["VALID_DEVICES", "resolve_device", "describe_device"]

VALID_DEVICES = ("auto", "cpu", "cuda", "mps")

Log = Optional[Callable[[str, str], None]]


def _torch():
    if importlib.util.find_spec("torch") is None:
        return None
    import torch
    return torch


def _mps_available(torch) -> bool:
    backend = getattr(getattr(torch, "backends", None), "mps", None)
    try:
        return bool(backend and backend.is_available())
    except Exception:
        return False


def resolve_device(requested: Optional[str] = "auto", log: Log = None) -> str:
    """The device string to hand to torch, sentence-transformers or HF."""
    requested = (requested or "auto").strip().lower()
    if requested == "cpu":
        return "cpu"

    def warn(message):
        if log is not None:
            log("warning", message)

    torch = _torch()
    if torch is None:
        if requested != "auto":
            warn("device %r was requested but torch is not installed; "
                 "using the CPU" % requested)
        return "cpu"

    cuda = bool(torch.cuda.is_available())
    mps = _mps_available(torch)

    if requested == "auto":
        if cuda:
            return "cuda"
        if mps:
            return "mps"
        return "cpu"
    if requested.startswith("cuda"):
        if cuda:
            return requested
        warn("device %r was requested but CUDA is not available here; "
             "using %s" % (requested, "mps" if mps else "the CPU"))
        return "mps" if mps else "cpu"
    if requested == "mps":
        if mps:
            return "mps"
        warn("device 'mps' was requested but Metal is not available here; "
             "using %s" % ("cuda" if cuda else "the CPU"))
        return "cuda" if cuda else "cpu"

    warn("Unknown device %r; expected one of %s. Using auto."
         % (requested, ", ".join(VALID_DEVICES)))
    return resolve_device("auto", log)


def describe_device(device: str) -> str:
    """A line for the run log: which device, and which card if it is a GPU."""
    torch = _torch()
    if torch is None or not device.startswith("cuda"):
        return {"mps": "Apple Metal (mps)", "cpu": "CPU"}.get(device, device)
    try:
        index = int(device.split(":", 1)[1]) if ":" in device else 0
        props = torch.cuda.get_device_properties(index)
        free, total = torch.cuda.mem_get_info(index)
        return "%s (%s, %.1f of %.1f GB free)" % (
            device, props.name, free / 1e9, total / 1e9)
    except Exception:
        return device
