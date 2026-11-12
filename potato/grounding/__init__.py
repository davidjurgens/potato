"""
Grounding: which part of an image a piece of language refers to.

Three questions live here, and they are separated because they have different
right answers and get confused constantly:

- **Grounding.** "The man in the red shirt" — where is he? A referring
  expression denotes a region, and a model is right if it points at the same
  one a person would. Scored by IoU against the annotator's region, at a
  stated threshold.
- **Pointing.** Molmo-style models emit *points*, not boxes. A point has no
  area, so IoU is undefined for it and the natural question is different: does
  the point land inside the thing? Scored as point-in-region, which is a
  hit rate, not an overlap.
- **Ungroundedness.** A caption says "a red bicycle" and there is no bicycle.
  This is not a localisation error with a low score; it is a claim about
  something that is not there, and the only honest answer is a region that
  does not exist. It has to be an explicit annotation — see
  :mod:`potato.grounding.metrics` on why "no region drawn" cannot stand in
  for it.

## The negatives are the whole point

An expression an annotator skipped and an expression an annotator judged to
have no referent look identical in storage unless the interface makes the
second one a thing you can say. They lead to opposite conclusions about a
model: skipping is missing data, "not present" is a correct refusal to point.
Every measure here excludes the first and scores the second, which is why the
schema has an explicit **not present in the image** control.
"""

from potato.grounding.metrics import (  # noqa: F401
    GroundingError,
    grounding_accuracy,
    point_in_region,
    pointing_accuracy,
    region_center,
    region_similarity,
)
