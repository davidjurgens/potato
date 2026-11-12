"""
Rollout sets: several videos of the same scenario, compared side by side.

A world-model evaluation item is not one video. It is a *real* recording and
one or more model rollouts of the same starting state, and every question worth
asking compares them: which one breaks first, which one is better, is this
divergence plausible given the intervention that caused it.

So the unit this package reads is a **rollout set** — an ordered list of
streams sharing one timeline — rather than a video. Everything downstream
(the panels, the timeline, the break-point agreement) is written against that
shape, which is why it is a package and not a field on the item.

## Two sources, because two things are actually true

- Benchmarks ship a table whose row already *is* the set: a prompt plus a
  column per generator. Those items carry their streams inline and never touch
  the disk.
- Datasets shipped as directories put a small JSON next to the videos.

Both produce a :class:`RolloutSet`; the schema client cannot tell which it got.
"""

from potato.rollouts.models import (  # noqa: F401
    RolloutError,
    RolloutSet,
    RolloutStream,
    stable_order,
)
from potato.rollouts.registry import read_rollout_set  # noqa: F401
