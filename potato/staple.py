"""
STAPLE — Simultaneous Truth And Performance Level Estimation.

Implements the EM algorithm from:
    Warfield, S. K., Zou, K. H., & Wells, W. M. (2004). Simultaneous truth and
    performance level estimation (STAPLE): an algorithm for the validation of
    image segmentation. IEEE Transactions on Medical Imaging, 23(7), 903-921.

WHY THIS EXISTS ALONGSIDE MACE
------------------------------
MACE answers "whose LABEL do you trust?" and cannot answer "whose MASK do you
trust". It models each annotator as knowing-or-guessing over a *finite shared
label set*; a segmentation mask lives in an unbounded space with no categorical
variable to estimate. Forcing masks through MACE would require inventing a
label set, and whatever was invented would drive the answer.

STAPLE is the established analogue for exactly this problem, and it is the
standard tool in medical imaging for precisely the question Potato users ask:
several people segmented the same structure, which boundary should the dataset
record, and who drew it well?

WHAT IT ESTIMATES
-----------------
Per annotator, two numbers that mean different things and are worth reporting
separately:

* **sensitivity** (p) — of the pixels that truly belong to the object, what
  share did this annotator include? Low sensitivity means under-segmenting:
  drawing inside the true boundary.
* **specificity** (q) — of the pixels that truly do not, what share did they
  correctly leave out? Low specificity means over-segmenting.

An annotator can have excellent sensitivity and poor specificity — someone who
draws generously around everything. A single "accuracy" number would hide that,
and the two have opposite fixes.

Plus a **consensus mask**: the per-pixel posterior probability that the pixel
belongs to the object, weighted by how much each annotator has earned.

The weighting is what makes STAPLE more than a vote. A careful annotator's
disagreement moves the consensus more than a careless one's, and the algorithm
works out which is which from the data rather than being told.

No Potato imports: pure numpy, independently testable, and usable standalone
in the same way ``mace.py`` is.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

#: Guards against log(0) and division by zero.
EPS = 1e-10

#: Warfield et al. initialize both rates optimistically; the EM then pulls
#: careless annotators down. Starting at 0.5 instead makes the algorithm
#: converge to a degenerate all-background solution on sparse masks, because
#: background pixels overwhelmingly outnumber foreground ones.
INITIAL_SENSITIVITY = 0.9999
INITIAL_SPECIFICITY = 0.9999

DEFAULT_MAX_ITER = 50
DEFAULT_TOLERANCE = 1e-7

#: Prior probability that a pixel belongs to the object, when not estimated
#: from the data. Only used as a starting point.
DEFAULT_PRIOR = 0.5


class STAPLEResult:
    """What one STAPLE run produced."""

    def __init__(self, consensus: np.ndarray, sensitivity: Dict[str, float],
                 specificity: Dict[str, float], iterations: int,
                 converged: bool, shape: Tuple[int, ...]):
        #: Per-pixel posterior P(pixel is foreground), flat, in [0, 1].
        self.consensus = consensus
        self.sensitivity = sensitivity
        self.specificity = specificity
        self.iterations = iterations
        self.converged = converged
        self.shape = shape

    def consensus_mask(self, threshold: float = 0.5) -> np.ndarray:
        """
        The consensus as a binary mask.

        0.5 is the natural cut for a posterior probability. Raising it produces
        a tighter mask that only well-agreed pixels survive, which is what you
        want when the consensus will be used as gold rather than as a starting
        point.
        """
        # Reshaped to the ORIGINAL mask shape, not left flat: every caller
        # compares this against an input mask, and a flat return makes
        # `array_equal` silently False on shapes that are actually identical.
        return (self.consensus >= threshold).astype(np.uint8).reshape(self.shape)

    def dice_against_consensus(self, mask: np.ndarray,
                               threshold: float = 0.5) -> float:
        """Dice overlap between one annotator's mask and the consensus."""
        reference = self.consensus_mask(threshold).ravel()
        other = np.asarray(mask).ravel().astype(np.uint8)
        if reference.size != other.size:
            raise ValueError(
                f"mask has {other.size} pixels but the consensus has "
                f"{reference.size}")
        total = reference.sum() + other.sum()
        if total == 0:
            # Both empty. Defined as perfect agreement: they agree there is
            # nothing here, which is a real and correct outcome.
            return 1.0
        return float(2.0 * np.logical_and(reference, other).sum() / total)

    def as_dict(self) -> dict:
        """A JSON-safe summary, without the pixel array."""
        return {
            "sensitivity": dict(self.sensitivity),
            "specificity": dict(self.specificity),
            "iterations": self.iterations,
            "converged": self.converged,
            "shape": list(self.shape),
            "consensus_area": int(self.consensus_mask().sum()),
        }


def staple(masks: Dict[str, np.ndarray],
           *,
           max_iter: int = DEFAULT_MAX_ITER,
           tolerance: float = DEFAULT_TOLERANCE,
           prior: Optional[float] = None) -> STAPLEResult:
    """
    Estimate a consensus segmentation and per-annotator performance.

    Args:
        masks: ``{annotator_id: binary mask}``. Every mask must be the same
            shape; they are compared pixel by pixel.
        max_iter: EM iterations before giving up.
        tolerance: convergence threshold on the mean absolute change in the
            consensus.
        prior: initial P(foreground). Estimated from the masks when None,
            which is almost always better than a fixed 0.5 — real segmentation
            targets occupy a few percent of an image, and starting at 0.5 makes
            the first E-step wildly overconfident.

    Returns:
        :class:`STAPLEResult`

    Raises:
        ValueError: on fewer than two annotators, or mismatched shapes. Both
            are caller errors that would otherwise produce a confident,
            meaningless answer.
    """
    if len(masks) < 2:
        raise ValueError(
            f"STAPLE needs at least two annotators, got {len(masks)}. With one "
            f"there is no performance to estimate — the mask IS the consensus.")

    annotators = sorted(masks)
    shapes = {name: np.asarray(masks[name]).shape for name in annotators}
    distinct = set(shapes.values())
    if len(distinct) > 1:
        raise ValueError(
            f"All masks must have the same shape; got {shapes}. Comparing "
            f"masks at different resolutions pixel-by-pixel would silently "
            f"produce nonsense.")

    shape = shapes[annotators[0]]
    # Column per annotator, row per pixel.
    # float64, NOT bool. `bool_array @ float_vector` overflows inside numpy's
    # matmul and emits divide-by-zero/overflow warnings on every iteration,
    # even though the arithmetic that follows is well conditioned.
    decisions = np.stack(
        [(np.asarray(masks[name]).ravel() > 0).astype(np.float64)
         for name in annotators], axis=1)
    n_pixels, n_annotators = decisions.shape

    if prior is None:
        prior = float(decisions.mean())

    # CLAMPED into the open interval, not backed off to 0.5. Replacing a
    # degenerate prior with the neutral value discards what the annotators
    # actually said: when everyone marks every pixel, the honest answer is
    # "all foreground", and 0.5 made the posterior settle at 0.4999999999 so
    # the consensus mask came back EMPTY on unanimous input.
    prior = min(max(float(prior), EPS), 1.0 - EPS)

    sensitivity = np.full(n_annotators, INITIAL_SENSITIVITY)
    specificity = np.full(n_annotators, INITIAL_SPECIFICITY)

    weights = np.full(n_pixels, prior)
    converged = False
    iterations = 0

    # numpy's matmul sets divide-by-zero/overflow FP flags on some BLAS
    # backends even when every input and output is finite -- verified here
    # with a log vector of -22.3 and a matrix of ones. The arithmetic is
    # correct; the flags are noise, and letting them through prints a scary
    # warning on every single run.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        for iterations in range(1, max_iter + 1):
            previous = weights

            # --- E step: posterior P(pixel is foreground | decisions, rates) ---
            # Computed in log space. The product over annotators underflows to
            # zero on any realistic image (a 512x512 mask with 5 annotators
            # multiplies 5 probabilities per pixel over 260k pixels), and an
            # underflowed denominator makes every posterior NaN.
            log_fg = np.log(prior + EPS) + (
                decisions @ np.log(sensitivity + EPS)
                + (1 - decisions) @ np.log(1 - sensitivity + EPS))
            log_bg = np.log(1 - prior + EPS) + (
                (1 - decisions) @ np.log(specificity + EPS)
                + decisions @ np.log(1 - specificity + EPS))

            peak = np.maximum(log_fg, log_bg)
            fg = np.exp(log_fg - peak)
            bg = np.exp(log_bg - peak)
            weights = fg / (fg + bg + EPS)

            # --- M step: re-estimate each annotator's rates ---
            total_fg = weights.sum()
            total_bg = (1 - weights).sum()
            if total_fg < EPS or total_bg < EPS:
                # Every pixel resolved to one class, so there is nothing left to
                # estimate. Stop rather than divide by zero.
                logger.debug("STAPLE degenerate at iteration %d", iterations)
                break

            sensitivity = (weights @ decisions) / total_fg
            specificity = ((1 - weights) @ (1 - decisions)) / total_bg

            # Keep the rates off the boundary: a rate of exactly 1 makes that
            # annotator's opinion infinitely certain and freezes the EM.
            sensitivity = np.clip(sensitivity, EPS, 1 - EPS)
            specificity = np.clip(specificity, EPS, 1 - EPS)

            change = float(np.abs(weights - previous).mean())
            if change < tolerance:
                converged = True
                break

    return STAPLEResult(
        consensus=weights,
        sensitivity={name: float(sensitivity[i])
                     for i, name in enumerate(annotators)},
        specificity={name: float(specificity[i])
                     for i, name in enumerate(annotators)},
        iterations=iterations,
        converged=converged,
        shape=shape,
    )


def staple_from_rle(rle_by_annotator: Dict[str, dict], width: int, height: int,
                    **kwargs) -> STAPLEResult:
    """
    Run STAPLE over Potato RLE masks.

    The bridge from what Potato stores to what the algorithm needs. Kept here
    rather than in the caller so there is one place that knows both.

    Args:
        rle_by_annotator: ``{annotator_id: {"counts": [...], "size": [h, w]}}``
        width, height: the image dimensions the masks describe
    """
    from potato.export.cv_utils import decode_rle

    masks = {}
    for annotator, rle in rle_by_annotator.items():
        if not rle or not rle.get("counts"):
            continue
        flat = decode_rle(rle, width, height)
        masks[annotator] = np.asarray(flat, dtype=np.uint8).reshape(
            (height, width))
    return staple(masks, **kwargs)


def consensus_rle(result: STAPLEResult, threshold: float = 0.5) -> dict:
    """
    The consensus mask as Potato RLE, so it can be stored like any other.

    Row-major counts alternating from a 0-run, ``size`` as ``[height, width]`` —
    the same contract every other mask in Potato uses.
    """
    binary = result.consensus_mask(threshold).ravel()
    counts: List[int] = []
    current = 0
    run = 0
    for value in binary:
        if int(value) == current:
            run += 1
        else:
            counts.append(run)
            current = 1 - current
            run = 1
    counts.append(run)
    height, width = (result.shape if len(result.shape) == 2
                     else (1, result.consensus.size))
    return {"counts": counts, "size": [int(height), int(width)]}
