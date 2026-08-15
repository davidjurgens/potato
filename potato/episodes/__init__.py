"""
Embodied episodes: multi-stream robot demonstrations, read into one shape.

A robot-learning episode is several synchronized video streams (wrist camera,
overhead, third-person) plus several numeric time series (joint positions,
gripper state, force-torque, reward, action deltas), all indexed by frame. Every
dataset in the field stores that differently — LeRobot in HuggingFace parquet
beside per-episode MP4s, RoboMimic and ALOHA in HDF5, Open X-Embodiment in
RLDS/TFDS shards — and none of them agrees on field names, units, or whether
the action is absolute or a delta.

So the readers converge on :class:`~potato.episodes.models.Episode`, and
everything downstream — the schema, the timeline, the agreement statistics, the
exporter — speaks only that.

## What is deliberately not normalized

**Units and semantics.** The reader records what the file *said* (a field name,
a stated unit) and does not convert. A joint angle in radians and one in degrees
look identical to a normalizer and differ by 57x to an annotator, so guessing is
worse than carrying the label through and letting the config say.

Import is lazy per format: pyarrow for LeRobot, h5py for HDF5,
tensorflow_datasets for RLDS. None is required to run Potato, and the error
when one is missing names the install command rather than raising ImportError
from somewhere in the call stack.
"""

from potato.episodes.models import (Episode, EpisodeError, Series, Stream,
                                    downsample)

__all__ = ["Episode", "EpisodeError", "Series", "Stream", "downsample"]
