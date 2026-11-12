"""
SAM 2 video tracking: prompt one frame, follow the object through the rest.

WHY THIS EXISTS IN PYTHON AS WELL AS JAVASCRIPT
-----------------------------------------------
Two reasons, and the second is the important one.

1. Long clips. The browser path handles a few hundred frames comfortably; a
   ten-minute clip on a laptop does not. This runs the same loop server-side
   for projects that have somewhere to run it.
2. **It is the oracle.** The tracking loop is stateful — a memory bank of past
   frames, in a specific order, padded a specific way, with temporal encodings
   applied per slot — and every part of that is easy to get subtly wrong in a
   way that still returns a plausible mask. Having the loop written twice, and
   testing that the two agree tensor for tensor, is what catches an assembly
   error that visual inspection never would.

WHAT MAKES THIS DIFFERENT FROM RE-PROMPTING
-------------------------------------------
Potato's earlier "propagation" carried a mask forward by re-prompting the next
frame with the previous mask and a centroid point. That works while an object
moves slowly and fails on occlusion, because nothing remembers what the object
looked like. SAM 2 keeps a memory bank: each frame's features and predicted
mask are encoded into memory tokens, and the next frame's features are
conditioned on them through cross-attention. The model then reports occlusion
itself, through `object_score_logits`, rather than guessing.

THE CONTRACT
------------
Five graphs, from an export that includes the memory modules (most do not):

    vision_encoder    image -> feats0/1/2, feats2_no_mem, vision_pos_embed
    mask_decoder      feats + points -> low/high-res mask, iou,
                                        object_score_logits, object_pointer
    memory_encoder    feats2 + mask -> memory_tokens, memory_pos
    memory_attention  current feats + memory bank -> conditioned feats
    pointer_tpos      normalized frame offsets -> pointer positional encodings

The memory bank is a FIXED-SIZE tensor: 7 mask memories x 4096 tokens plus 16
object pointers x 4 chunks = 28736 rows. Fewer than that in hand means padding
by repeating the most recent entry, NOT zero-filling — zeros are a valid memory
that says "empty scene", and the model believes it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Filled on first use. Nothing here is imported at module load: numpy and
#: onnxruntime are optional, and a guarded module-level import still loads the
#: whole stack for anyone who happens to have them.
_np = None
_ort = None


def _lazy():
    global _np, _ort
    if _np is None:
        import numpy  # noqa: PLC0415
        _np = numpy
    if _ort is None:
        import onnxruntime  # noqa: PLC0415
        _ort = onnxruntime
    return _np, _ort


@dataclass
class TrackedFrame:
    """One frame's result."""

    frame: int
    #: Binary mask at the ORIGINAL image resolution, or None when occluded.
    mask: Any = None
    #: The model's own occlusion score. Positive means "the object is here".
    object_score: float = 0.0
    iou: float = 0.0

    @property
    def visible(self) -> bool:
        return self.object_score > 0


@dataclass
class _Memory:
    """One frame's contribution to the memory bank."""

    tokens: Any          # (4096, 1, 64)
    pos: Any             # (4096, 1, 64)
    pointer: Any         # (1, 256)
    frame: int
    is_conditioning: bool = False


@dataclass
class SAM2VideoTracker:
    """
    Track one object through a sequence of frames.

    Usage::

        tracker = SAM2VideoTracker(model_dir)
        tracker.start(first_frame, points=[(x, y, 1)])
        for frame in rest:
            result = tracker.step(frame)
    """

    model_dir: Path
    #: How many mask memories the bank holds. The export fixes this at 7.
    num_maskmem: int = 7
    max_object_pointers: int = 16

    _sessions: Dict[str, Any] = field(default_factory=dict, repr=False)
    _constants: Dict[str, Any] = field(default_factory=dict, repr=False)
    _memories: List[_Memory] = field(default_factory=list, repr=False)
    _conditioning: Optional[_Memory] = field(default=None, repr=False)
    _frame_index: int = 0
    _orig_size: Tuple[int, int] = (0, 0)

    # ---------------------------------------------------------------- setup

    def __post_init__(self):
        self.model_dir = Path(self.model_dir)

    def _session(self, name: str):
        if name not in self._sessions:
            np, ort = _lazy()
            path = self.model_dir / f"{name}.onnx"
            if not path.exists():
                raise FileNotFoundError(
                    f"{path} is missing. Install the model with:  "
                    f"potato download-models sam2_video_tiny")
            self._sessions[name] = ort.InferenceSession(
                str(path), providers=["CPUExecutionProvider"])
        return self._sessions[name]

    @property
    def constants(self) -> Dict[str, Any]:
        if not self._constants:
            self._constants = json.loads(
                (self.model_dir / "constants.json").read_text())
            self.num_maskmem = self._constants.get("num_maskmem", 7)
            self.max_object_pointers = self._constants.get(
                "max_object_pointers", 16)
        return self._constants

    @property
    def image_size(self) -> int:
        return int(self.constants.get("image_size", 1024))

    # ------------------------------------------------------------ encoding

    def preprocess(self, image) -> Any:
        """PIL image -> the encoder's NCHW tensor, and remember the size."""
        np, _ = _lazy()
        from PIL import Image  # noqa: PLC0415

        rgb = image.convert("RGB") if hasattr(image, "convert") else image
        self._orig_size = (rgb.height, rgb.width)
        size = self.image_size
        resized = rgb.resize((size, size), Image.BILINEAR)
        arr = np.asarray(resized, dtype=np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        return arr.transpose(2, 0, 1)[None].astype(np.float32)

    def _encode(self, image):
        pixel_values = self.preprocess(image)
        out = self._session("vision_encoder").run(None,
                                                  {"pixel_values": pixel_values})
        names = [o.name for o in self._session("vision_encoder").get_outputs()]
        return dict(zip(names, out))

    # -------------------------------------------------------- memory bank

    def _temporal_pe(self, row: int):
        np, _ = _lazy()
        table = np.array(
            self.constants["memory_temporal_positional_encoding"],
            dtype=np.float32)
        return table[row]

    def _bank(self):
        """
        Assemble the fixed-size memory tensors.

        Order matters and is not arbitrary: the conditioning frame occupies the
        LAST temporal slot, and recent frames fill the slots before it working
        backwards. Getting this wrong does not raise — it produces a tracker
        that drifts.
        """
        np, _ = _lazy()
        blocks: List[Tuple[Any, Any]] = []

        recent = [m for m in self._memories if not m.is_conditioning]
        recent = recent[-(self.num_maskmem - 1):]

        # Recent frames first, oldest to newest, taking temporal rows counting
        # back from the conditioning slot.
        for offset, memory in enumerate(recent):
            row = self.num_maskmem - 1 - (len(recent) - offset)
            pos = memory.pos + self._temporal_pe(max(row, 0)).reshape(1, 1, -1)
            blocks.append((memory.tokens, pos))

        if self._conditioning is not None:
            pos = self._conditioning.pos + \
                self._temporal_pe(self.num_maskmem - 1).reshape(1, 1, -1)
            blocks.append((self._conditioning.tokens, pos))

        if not blocks:
            raise RuntimeError("no memory to attend to; call start() first")

        # Pad by REPEATING the most recent block. Zero-filling would be a
        # memory that says "nothing here", which the model believes.
        while len(blocks) < self.num_maskmem:
            blocks.append(blocks[-1])

        memory = np.concatenate([b[0] for b in blocks], axis=0)
        memory_pos = np.concatenate([b[1] for b in blocks], axis=0)

        pointers, pointer_pos = self._pointer_bank()
        memory = np.concatenate([memory, pointers], axis=0)
        memory_pos = np.concatenate([memory_pos, pointer_pos], axis=0)
        return memory.astype(np.float32), memory_pos.astype(np.float32)

    def _pointer_bank(self):
        """Object pointers, each split into four 64-wide chunks."""
        np, _ = _lazy()
        all_memories = ([self._conditioning] if self._conditioning else []) \
            + [m for m in self._memories if not m.is_conditioning]
        pointers = all_memories[-self.max_object_pointers:]
        while len(pointers) < self.max_object_pointers:
            pointers.append(pointers[-1])

        span = max(min(self._frame_index + 1, self.max_object_pointers) - 1, 1)
        diffs = np.array(
            [(self._frame_index - m.frame) / span for m in pointers],
            dtype=np.float32)
        pos = self._session("pointer_tpos").run(
            None, {"normalized_diffs": diffs})[0]          # (16, 64)

        chunks = np.concatenate(
            [p.pointer.reshape(4, 64) for p in pointers], axis=0)  # (64, 64)
        pos_chunks = np.repeat(pos, 4, axis=0)                     # (64, 64)
        return chunks[:, None, :], pos_chunks[:, None, :]

    # ------------------------------------------------------------ decoding

    def _decode(self, feats, points, labels):
        np, _ = _lazy()
        out = self._session("mask_decoder").run(None, {
            "feats0": feats["feats0"],
            "feats1": feats["feats1"],
            "feats2_cond": feats["feats2_cond"],
            "input_points": np.array([[points]], dtype=np.float32),
            "input_labels": np.array([[labels]], dtype=np.int32),
        })
        names = [o.name for o in self._session("mask_decoder").get_outputs()]
        return dict(zip(names, out))

    def _remember(self, feats, decoded, binarize: float, conditioning: bool):
        np, _ = _lazy()
        out = self._session("memory_encoder").run(None, {
            "feats2": feats["feats2"],
            "high_res_mask": decoded["high_res_mask"].astype(np.float32),
            "object_score_logits": decoded["object_score_logits"].reshape(1, 1)
                                    .astype(np.float32),
            "binarize": np.array(binarize, dtype=np.float32),
        })
        memory = _Memory(tokens=out[0], pos=out[1],
                         pointer=decoded["object_pointer"].reshape(1, 256),
                         frame=self._frame_index,
                         is_conditioning=conditioning)
        if conditioning:
            self._conditioning = memory
        else:
            self._memories.append(memory)
            # Only the most recent few are ever read, and holding every frame's
            # memory for a long clip is how this runs a machine out of RAM.
            keep = max(self.num_maskmem, self.max_object_pointers) + 2
            if len(self._memories) > keep:
                self._memories = self._memories[-keep:]

    def _to_mask(self, decoded):
        """High-res logits -> a boolean mask at the original resolution."""
        np, _ = _lazy()
        from PIL import Image  # noqa: PLC0415

        logits = decoded["high_res_mask"][0, 0]
        height, width = self._orig_size
        if (height, width) != logits.shape:
            resized = Image.fromarray(logits).resize((width, height),
                                                     Image.BILINEAR)
            logits = np.asarray(resized, dtype=np.float32)
        return logits > 0

    # ---------------------------------------------------------------- API

    def start(self, image, points: Sequence[Tuple[float, float, int]]) -> TrackedFrame:
        """
        Prompt the first frame. Coordinates are in ORIGINAL image pixels.

        The seed frame is decoded from `feats2_no_mem` — there is no memory to
        condition on yet — and its memory is encoded with `binarize=1`, which is
        what marks it as the point-prompted frame the rest of the sequence
        refers back to.
        """
        np, _ = _lazy()
        self._memories.clear()
        self._conditioning = None
        self._frame_index = 0

        feats = self._encode(image)
        scale = self.image_size
        height, width = self._orig_size
        scaled = [[float(x) * scale / width, float(y) * scale / height]
                  for x, y, _ in points]
        labels = [int(label) for _, _, label in points]

        decoded = self._decode(
            {**feats, "feats2_cond": feats["feats2_no_mem"]}, scaled, labels)
        self._remember(feats, decoded, binarize=1.0, conditioning=True)
        return TrackedFrame(
            frame=0, mask=self._to_mask(decoded),
            object_score=float(decoded["object_score_logits"].reshape(-1)[0]),
            iou=float(decoded["iou"].reshape(-1)[0]))

    def step(self, image) -> TrackedFrame:
        """Carry the tracked object into the next frame."""
        np, _ = _lazy()
        self._frame_index += 1
        feats = self._encode(image)

        memory, memory_pos = self._bank()
        conditioned = self._session("memory_attention").run(None, {
            "current_vision_features":
                feats["feats2"].reshape(1, 256, -1).transpose(2, 0, 1)
                .astype(np.float32),
            "current_vision_position_embeddings":
                feats["vision_pos_embed"].reshape(1, 256, -1).transpose(2, 0, 1)
                .astype(np.float32),
            "memory": memory,
            "memory_pos": memory_pos,
        })[0]

        # A single padding point with label -1: the decoder's interface always
        # wants points, and on a propagated frame there are none to give.
        decoded = self._decode({**feats, "feats2_cond": conditioned},
                               [[0.0, 0.0]], [-1])
        self._remember(feats, decoded, binarize=0.0, conditioning=False)

        score = float(decoded["object_score_logits"].reshape(-1)[0])
        return TrackedFrame(
            frame=self._frame_index,
            # The model reports occlusion itself rather than being asked to
            # guess, so an occluded frame comes back empty rather than wrong.
            mask=self._to_mask(decoded) if score > 0 else None,
            object_score=score,
            iou=float(decoded["iou"].reshape(-1)[0]))

    def track(self, frames, points) -> List[TrackedFrame]:
        """Prompt the first frame and propagate through the rest."""
        frames = list(frames)
        if not frames:
            return []
        results = [self.start(frames[0], points)]
        for frame in frames[1:]:
            results.append(self.step(frame))
        return results
