"""The trainer interface.

A trainer takes a *bundle* -- a self-contained directory of split files, labels
and media -- and produces an *artifact* directory holding a model. It never
touches Potato's server, its item store or its user states, and that is the
point: the same class runs inside Potato's subprocess worker and inside someone
else's training rig on a GPU box, because it only ever sees files.

Two rules hold this together.

**Nothing here may import a training library.** This module is dataclasses, a
Protocol and an ABC over stdlib types. ``Trainer.available()`` must probe with
``importlib.util.find_spec`` and never with a real import: a module-level
``try: import torch`` reads as deferral but loads eagerly whenever torch
happens to be installed, which is how the boot path gets heavy.

**Capability is declared, not guessed.** A trainer names the ``SchemaKind``
values and modalities it can handle, and the registry matches those against
``iaa.dispatcher.classify_schema``. That table already classifies every
annotation type Potato has and is already tested, so trainers inherit a
taxonomy rather than inventing a second one that drifts from it.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import (Any, ClassVar, Dict, Iterable, Iterator, List, Optional,
                    Sequence, Tuple)

__all__ = [
    "MODALITIES",
    "SchemaSpec",
    "ResourceLimits",
    "TrainingSpec",
    "BundleRef",
    "PredictItem",
    "PredictionRecord",
    "FitResult",
    "ProgressReporter",
    "NullReporter",
    "Trainer",
    "TrainerError",
    "MissingDependency",
]


#: The modality vocabulary, shared with `potato.embedders`. A trainer declares
#: which of these it can consume; the bundle manifest declares which one the
#: project actually is.
MODALITIES = ("text", "image", "audio", "video", "trace", "point_cloud",
              "tabular")


class TrainerError(RuntimeError):
    """A trainer could not do what was asked."""


class MissingDependency(TrainerError):
    """A trainer's package is not installed.

    Carries the install hint verbatim so the parent process can show it
    without knowing anything about the trainer.
    """

    def __init__(self, message: str, install_hint: str = ""):
        super().__init__(message)
        self.install_hint = install_hint


@dataclass(frozen=True)
class SchemaSpec:
    """One annotation scheme, as a trainer sees it."""

    name: str
    annotation_type: str
    #: The ``SchemaKind`` value as a string, so this stays JSON-serializable
    #: and the spec file can be read without importing the enum.
    kind: str
    labels: Tuple[str, ...] = ()
    #: Which item field holds the input (an image path, an audio path). None
    #: means the project's ``text_key``.
    source_field: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "annotation_type": self.annotation_type,
                "kind": self.kind, "labels": list(self.labels),
                "source_field": self.source_field}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SchemaSpec":
        return cls(name=data["name"],
                   annotation_type=data.get("annotation_type", ""),
                   kind=data.get("kind", "unsupported"),
                   labels=tuple(data.get("labels") or ()),
                   source_field=data.get("source_field"))


@dataclass(frozen=True)
class ResourceLimits:
    """What the run is allowed to consume.

    ``max_wall_s`` is enforced by the parent (it cancels), ``max_ram_mb`` by
    the child (``setrlimit``). Splitting it that way means a child that wedges
    without allocating still gets stopped.
    """

    max_wall_s: Optional[int] = None
    max_ram_mb: Optional[int] = None
    device: str = "auto"          # auto | cpu | cuda | mps
    num_threads: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"max_wall_s": self.max_wall_s, "max_ram_mb": self.max_ram_mb,
                "device": self.device, "num_threads": self.num_threads}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResourceLimits":
        data = data or {}
        return cls(max_wall_s=data.get("max_wall_s"),
                   max_ram_mb=data.get("max_ram_mb"),
                   device=data.get("device", "auto"),
                   num_threads=data.get("num_threads"))


@dataclass(frozen=True)
class TrainingSpec:
    """Everything a trainer needs, and nothing about Potato.

    Serialized to ``spec.json`` for the subprocess worker and handed verbatim
    to an external backend. The two must stay byte-identical -- that identity
    is what makes writing an external backend a matter of porting the worker's
    main loop rather than reimplementing a second contract.
    """

    run_id: str
    trainer: str
    schemas: Tuple[SchemaSpec, ...]
    bundle_dir: str
    workdir: str
    params: Dict[str, Any] = field(default_factory=dict)
    seed: int = 0
    limits: ResourceLimits = field(default_factory=ResourceLimits)

    def to_dict(self) -> Dict[str, Any]:
        return {"v": 1, "run_id": self.run_id, "trainer": self.trainer,
                "schemas": [s.to_dict() for s in self.schemas],
                "bundle_dir": self.bundle_dir, "workdir": self.workdir,
                "params": self.params, "seed": self.seed,
                "limits": self.limits.to_dict()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingSpec":
        return cls(
            run_id=data["run_id"], trainer=data["trainer"],
            schemas=tuple(SchemaSpec.from_dict(s)
                          for s in data.get("schemas", [])),
            bundle_dir=data["bundle_dir"], workdir=data["workdir"],
            params=data.get("params") or {}, seed=data.get("seed", 0),
            limits=ResourceLimits.from_dict(data.get("limits")))

    def write(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def read(cls, path: str) -> "TrainingSpec":
        with open(path) as fh:
            return cls.from_dict(json.load(fh))

    @property
    def primary_schema(self) -> Optional[SchemaSpec]:
        return self.schemas[0] if self.schemas else None


@dataclass(frozen=True)
class BundleRef:
    """A built bundle on disk.

    Deliberately thin. The manifest is the contract; this is a typed way to
    read it without every trainer re-deriving the paths.
    """

    root: str
    manifest: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, root: str) -> "BundleRef":
        path = os.path.join(root, "manifest.json")
        if not os.path.isfile(path):
            raise TrainerError("No bundle manifest at %s" % path)
        with open(path) as fh:
            return cls(root=root, manifest=json.load(fh))

    def split_path(self, split: str) -> Optional[str]:
        """Absolute path to one split's file, or ``None`` if it is absent.

        An absent split is normal -- a small project may have no test set --
        so this returns None rather than raising.
        """
        entry = (self.manifest.get("splits") or {}).get(split)
        if not entry:
            return None
        return os.path.join(self.root, entry["path"])

    def split_size(self, split: str) -> int:
        entry = (self.manifest.get("splits") or {}).get(split)
        return int(entry.get("n", 0)) if entry else 0

    def split_format(self, split: str) -> str:
        entry = (self.manifest.get("splits") or {}).get(split)
        return entry.get("format", "") if entry else ""

    def read_split(self, split: str) -> Iterator[Dict[str, Any]]:
        """Yield one record per line from a JSONL split. Empty when absent."""
        path = self.split_path(split)
        if not path or not os.path.isfile(path):
            return
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    @property
    def media_dir(self) -> str:
        return os.path.join(self.root, self.manifest.get("media_dir", "media"))

    def labels(self, schema: str) -> List[str]:
        """The label vocabulary for one schema, in a stable order.

        Order matters: it is what a classifier's output columns mean, and a
        model reloaded against a reshuffled vocabulary predicts confidently
        wrong labels.
        """
        return list((self.manifest.get("labels") or {}).get(schema, []))

    @property
    def digest(self) -> str:
        return self.manifest.get("digest", "")

    @property
    def modality(self) -> str:
        return self.manifest.get("modality", "text")

    def resolve_media(self, reference: str) -> str:
        """Turn a manifest media reference into a path a trainer can open."""
        if os.path.isabs(reference):
            return reference
        return os.path.join(self.media_dir, reference)


@dataclass(frozen=True)
class PredictItem:
    """One thing to predict on."""

    instance_id: str
    text: str = ""
    media: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionRecord:
    """One prediction, in the shape the write-back layer stores.

    ``payload`` must already match what the annotation UI renders for this
    schema kind -- a label dict for a classification scheme, a list of span
    dicts for a span scheme, an objects list for geometry. Converting it is
    the trainer's job, because only the trainer knows what its model emitted.
    """

    instance_id: str
    schema_name: str
    payload: Any
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"instance_id": self.instance_id,
                "schema_name": self.schema_name,
                "payload": self.payload, "confidence": self.confidence}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PredictionRecord":
        return cls(instance_id=data["instance_id"],
                   schema_name=data["schema_name"],
                   payload=data.get("payload"),
                   confidence=data.get("confidence"))


@dataclass
class FitResult:
    """What a fit produced."""

    model_version: str = ""
    artifact_paths: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    label_order: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"model_version": self.model_version,
                "artifact_paths": self.artifact_paths,
                "metrics": self.metrics, "label_order": self.label_order,
                "notes": self.notes}


class ProgressReporter:
    """How a trainer talks back.

    The subprocess implementation writes JSONL to stdout; an external backend
    POSTs the same objects. A trainer sees neither -- it calls these five
    methods and the transport is somebody else's problem.
    """

    def status(self, state: str, step: str = "") -> None:
        """Coarse lifecycle: ``running``, ``evaluating``, and so on."""

    def progress(self, phase: str, current: int, total: int,
                 eta_s: Optional[float] = None) -> None:
        """Fine-grained position within a phase."""

    def metric(self, split: str, name: str, value: float,
               step: int = 0) -> None:
        """One measurement. Called repeatedly to build a curve."""

    def log(self, level: str, msg: str) -> None:
        """A human-readable line."""

    def should_stop(self) -> bool:
        """Whether to abandon the run.

        Poll this inside any loop that runs longer than a second or two.
        A trainer that never checks it can only be stopped by SIGKILL, which
        loses the partial artifacts and the reason.
        """
        return False


class NullReporter(ProgressReporter):
    """Discards everything. For tests and for direct library use."""


class Trainer(ABC):
    """Fit a model on annotations, predict with it, and score it."""

    #: Registry key. Lowercase, hyphenated: ``sklearn-text``.
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""

    #: ``SchemaKind`` values, as strings. Matched against
    #: ``iaa.dispatcher.classify_schema`` by the registry.
    kinds: ClassVar[Tuple[str, ...]] = ()

    #: Which of ``MODALITIES`` this trainer can read.
    modalities: ClassVar[Tuple[str, ...]] = ("text",)

    #: Shown verbatim when ``available()`` is False. Should be a command the
    #: user can paste.
    install_hint: ClassVar[str] = ""

    #: Licence of the training library, not of Potato. ``ultralytics`` is
    #: AGPL-3.0 and a user training with it inherits obligations they should
    #: be told about before the first run, not after.
    licence: ClassVar[str] = "unspecified"
    commercial_use: ClassVar[Optional[bool]] = None
    #: When True, the admin UI requires an explicit acknowledgement before the
    #: first run with this trainer.
    licence_ack: ClassVar[bool] = False
    licence_url: ClassVar[str] = ""

    #: Whether one run can fit several schemas at once.
    multi_schema: ClassVar[bool] = False

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        """``(usable, reason)``.

        **Must not import the training library.** Use
        ``importlib.util.find_spec``. The parent process calls this to decide
        whether to grey out a button, and the parent is the process that must
        stay light.
        """
        return True, ""

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        """JSON Schema for ``params``. Drives the admin form."""
        return {"type": "object", "properties": {},
                "additionalProperties": True}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        """Reasons this run cannot proceed. Empty means go.

        Checked before the expensive work starts, so "you have 3 annotations
        and need 20" arrives in a second rather than after a bundle build.
        """
        return []

    @abstractmethod
    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        """Train, writing artifacts under ``spec.workdir``."""

    @abstractmethod
    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        """Predict on *items* using the model in *artifact_dir*.

        An iterator on purpose: a detection run over a large corpus should
        stream to disk rather than accumulate in memory.
        """

    def evaluate(self, spec: TrainingSpec, artifact_dir: str,
                 bundle: BundleRef, split: str,
                 report: ProgressReporter) -> Dict[str, float]:
        """Score the fitted model on one held-out split.

        The default returns nothing, because Potato scores model-versus-human
        with the same IAA machinery it uses for human-versus-human. Override
        only for a metric that machinery cannot express.
        """
        return {}
