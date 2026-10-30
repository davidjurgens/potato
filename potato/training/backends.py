"""Where a training run executes.

Three kinds of backend, all configured under ``model_training.backends``:

``local``
    The subprocess worker on the machine running Potato. Always present, and
    the default. On a Mac with Apple silicon, ``device: auto`` runs embedding
    models on Metal.

``ssh``
    Another machine Potato can reach over ssh, typically a GPU server. Potato
    starts the agent there itself: it connects, checks the interpreter and the
    GPUs, copies its own source over, and launches the agent with a reverse
    forward back to this server. Nothing has to be installed or started on
    the remote host by hand beyond Python and the trainer's packages.

``agent``
    A machine that cannot be reached from the server, for example a
    workstation behind NAT. Someone starts ``potato training agent`` there,
    and it polls this server for work.

The ``ssh`` and ``agent`` kinds speak the same protocol
(:mod:`potato.training.protocol`); the only difference is who starts the
agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = ["BACKEND_TYPES", "BackendConfig", "load_backends",
           "default_backend_name", "validate_backends_config"]

BACKEND_TYPES = ("local", "ssh", "agent")

#: Keys a backend entry may carry, by type. Anything else is reported by
#: :func:`validate_backends_config`, because a misspelt ``pyhton`` silently
#: running the wrong interpreter would be hard to diagnose from a failed run.
_COMMON_KEYS = {"type", "description", "heartbeat_timeout_s",
                "queue_timeout_s"}
_SSH_KEYS = {"host", "user", "port", "identity_file", "python", "gpus",
             "min_free_gpu_mb", "remote_dir", "fetch_artifacts",
             "max_artifact_mb", "keep_remote", "ssh_options", "env",
             "packages", "connect_timeout_s", "num_threads"}

DEFAULT_REMOTE_DIR = "~/.cache/potato-training"


@dataclass
class BackendConfig:
    name: str
    type: str = "local"
    description: str = ""
    # ssh
    host: str = ""
    user: str = ""
    port: Optional[int] = None
    identity_file: str = ""
    python: str = "python3"
    #: ``auto`` (the GPU with the most free memory), ``none``, or a
    #: comma-separated list of indices.
    gpus: str = "auto"
    min_free_gpu_mb: int = 2000
    remote_dir: str = DEFAULT_REMOTE_DIR
    fetch_artifacts: bool = True
    max_artifact_mb: int = 2048
    keep_remote: bool = False
    ssh_options: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    packages: List[str] = field(default_factory=list)
    connect_timeout_s: int = 15
    num_threads: Optional[int] = None
    # supervision
    heartbeat_timeout_s: int = 120
    queue_timeout_s: Optional[int] = None
    #: Test seam: run the ssh launcher's commands on this machine instead of
    #: over ssh. Not documented; see tests/unit/test_training_launcher.py.
    _transport: str = "ssh"

    @property
    def is_remote(self) -> bool:
        return self.type in ("ssh", "agent")

    @property
    def label(self) -> str:
        if self.type == "ssh":
            return "%s (ssh to %s)" % (self.name, self.host)
        if self.type == "agent":
            return "%s (agent)" % self.name
        return "%s (this machine)" % self.name

    def to_public_dict(self) -> Dict[str, Any]:
        """What the admin page shows. No ssh options or environment."""
        return {"name": self.name, "type": self.type, "label": self.label,
                "host": self.host, "description": self.description}

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "BackendConfig":
        data = dict(data or {})
        backend = cls(name=name, type=str(data.get("type", "local")))
        for key in _COMMON_KEYS | _SSH_KEYS:
            if key in data and key != "type":
                setattr(backend, key, data[key])
        if "_transport" in data:
            backend._transport = str(data["_transport"])
        backend.gpus = str(backend.gpus).strip().lower() \
            if backend.gpus is not None else "none"
        backend.ssh_options = [str(o) for o in (backend.ssh_options or [])]
        backend.env = {str(k): str(v) for k, v in (backend.env or {}).items()}
        backend.packages = [str(p) for p in (backend.packages or [])]
        return backend


def _training(config: Dict[str, Any]) -> Dict[str, Any]:
    return (config or {}).get("model_training", {}) or {}


def load_backends(config: Dict[str, Any]) -> Dict[str, BackendConfig]:
    """Every configured backend, keyed by name. ``local`` is always there."""
    out = {"local": BackendConfig(name="local", type="local")}
    for name, data in (_training(config).get("backends") or {}).items():
        if not isinstance(data, dict):
            continue
        out[str(name)] = BackendConfig.from_dict(str(name), data)
    return out


def default_backend_name(config: Dict[str, Any]) -> str:
    return str(_training(config).get("backend") or "local")


def validate_backends_config(config: Dict[str, Any]) -> List[str]:
    """Problems with ``model_training.backend``/``backends``, as messages."""
    training = _training(config)
    problems: List[str] = []
    raw = training.get("backends")
    if raw is not None and not isinstance(raw, dict):
        return ["model_training.backends must be a mapping of name to "
                "settings"]

    for name, data in (raw or {}).items():
        where = "model_training.backends.%s" % name
        if not isinstance(data, dict):
            problems.append("%s must be a mapping" % where)
            continue
        kind = data.get("type")
        if kind not in BACKEND_TYPES:
            problems.append("%s.type must be one of %s (got %r)"
                            % (where, ", ".join(BACKEND_TYPES), kind))
            continue
        if name == "local" and kind != "local":
            problems.append("%s: the name 'local' is reserved for this "
                            "machine" % where)
        allowed = _COMMON_KEYS | (_SSH_KEYS if kind == "ssh" else set())
        allowed.add("_transport")
        for key in data:
            if key not in allowed:
                problems.append("%s.%s is not a setting for a type: %s backend"
                                % (where, key, kind))
        if kind == "ssh" and not data.get("host"):
            problems.append("%s.host is required for an ssh backend" % where)
        gpus = str(data.get("gpus", "auto")).strip().lower()
        if kind == "ssh" and gpus not in ("auto", "none") and not all(
                part.strip().isdigit() for part in gpus.split(",")):
            problems.append("%s.gpus must be auto, none, or GPU indices such "
                            "as \"0\" or \"0,1\" (got %r)" % (where, gpus))
        for key in ("env",):
            if key in data and not isinstance(data[key], dict):
                problems.append("%s.%s must be a mapping" % (where, key))
        for key in ("ssh_options", "packages"):
            if key in data and not isinstance(data[key], list):
                problems.append("%s.%s must be a list" % (where, key))

    chosen = training.get("backend")
    if chosen and chosen != "local" and chosen not in (raw or {}):
        problems.append("model_training.backend is %r, which is not "
                        "defined under model_training.backends" % chosen)
    return problems
