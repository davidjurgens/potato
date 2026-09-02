"""
RLDS / TFDS: the Open X-Embodiment layout.

RLDS stores an episode as a nested dataset of *steps*, each a dict of
observation, action, reward and termination flags. It is the format the Open
X-Embodiment collection publishes in, which makes it the widest single source
of robot demonstration data — and the heaviest to read, because it needs
TensorFlow.

That dependency is the design constraint here. TensorFlow is hundreds of
megabytes, pulls CUDA on many platforms, and would triple Potato's install for
a feature most projects never touch. So it is imported **inside** the reader and
never at module scope, and its absence produces a message naming the install
command and the offline alternative rather than an ImportError from four frames
down.

## Shapes vary more than the spec suggests

RLDS says an observation is a dict; it does not say what is in it. One dataset
has `image`, `state`; another has `agentview_image`, `robot0_eef_pos`,
`robot0_gripper_qpos`. So the reader takes whatever numeric per-step fields it
finds and names them by their path, rather than looking for a fixed set and
returning an empty episode when the dataset does not use those names.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from potato.episodes.models import (Episode, EpisodeError, Series,
                                    flatten_vector_column)

logger = logging.getLogger(__name__)

MISSING_MESSAGE = (
    "Reading RLDS/TFDS datasets needs tensorflow_datasets, which Potato does "
    "not install by default — TensorFlow is a very large dependency for a "
    "format most projects never touch.\n"
    "  Install it:   pip install tensorflow tensorflow_datasets\n"
    "  Or convert:   many Open X-Embodiment datasets are also published in "
    "LeRobot v2 form on the HuggingFace hub, which Potato reads with pyarrow "
    "alone."
)


def available() -> bool:
    """Whether the optional dependency is importable, without importing it."""
    import importlib.util
    return importlib.util.find_spec("tensorflow_datasets") is not None


def _require_tfds():
    try:
        import tensorflow_datasets as tfds
    except ImportError as err:
        raise EpisodeError(MISSING_MESSAGE) from err
    return tfds


def read(dataset: str, episode_index: int = 0, split: str = "train",
         data_dir: Optional[str] = None, fps: float = 10.0) -> Episode:
    """
    Read one episode from a TFDS dataset.

    ``fps`` is a parameter with a default rather than something read from the
    data: RLDS records steps, not time, and most Open X-Embodiment datasets do
    not state their control frequency anywhere machine-readable. Ten is the
    modal value across the collection and is documented as a guess — a
    timeline built on a wrong frame rate is still correctly *ordered*, which is
    what phase annotation needs.
    """
    tfds = _require_tfds()

    try:
        builder = tfds.builder_from_directory(data_dir) if data_dir \
            else tfds.builder(dataset)
        ds = builder.as_dataset(split=f"{split}[{episode_index}:"
                                      f"{episode_index + 1}]")
    except Exception as err:      # tfds raises many unrelated types
        raise EpisodeError(
            f"cannot open RLDS dataset '{dataset}': {err}") from err

    steps: List[Dict[str, Any]] = []
    instruction = ""
    for record in ds:
        for step in record["steps"]:
            flat: Dict[str, Any] = {}
            _flatten(step, "", flat)
            text = flat.pop("language_instruction", None)
            if text and not instruction:
                instruction = _as_text(text)
            steps.append(flat)
        break

    if not steps:
        raise EpisodeError(
            f"episode {episode_index} of '{dataset}' has no steps")

    series: List[Series] = []
    for key in steps[0]:
        column = [step.get(key) for step in steps]
        if any(isinstance(v, (list, tuple)) for v in column):
            rows = [list(v) if isinstance(v, (list, tuple)) else []
                    for v in column]
            series.extend(flatten_vector_column(key, rows))
        else:
            numeric = [_number(v) for v in column]
            if any(n == n for n in numeric):
                series.append(Series(name=key, values=numeric, group=key))

    return Episode(
        episode_id=f"{dataset}_{episode_index}",
        num_frames=len(steps),
        fps=fps,
        streams=[],
        series=series,
        instruction=instruction,
        metadata={"dataset": dataset, "split": split,
                  "fps_is_assumed": True},
        source_format="rlds",
    )


def _flatten(node: Any, prefix: str, out: Dict[str, Any],
             depth: int = 0) -> None:
    """Flatten a nested step dict into `a/b/c` keys, skipping image tensors."""
    if depth > 5:
        return
    try:
        items = node.items()
    except AttributeError:
        out[prefix or "value"] = _as_python(node)
        return

    for key, value in items:
        name = f"{prefix}/{key}" if prefix else str(key)
        if hasattr(value, "items"):
            _flatten(value, name, out, depth + 1)
            continue
        shape = getattr(value, "shape", None)
        # (H, W, C) and larger are frames. RLDS keeps them in the record, and
        # drawing a lane for a 480x640x3 tensor is meaningless.
        if shape is not None and len(shape) >= 2:
            continue
        out[name] = _as_python(value)


def _as_python(value: Any) -> Any:
    if hasattr(value, "numpy"):
        value = value.numpy()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _as_text(value: Any) -> str:
    value = _as_python(value)
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
