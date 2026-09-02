# Chance-Corrected Agreement over Geometry

How reliable is a bounding-box or segmentation dataset? This page is the method
Potato uses to answer that, and what each number does and does not tell you.

Where a measure is weak, this page says so.

## What everyone else reports, and why it is not enough

CVAT's consensus engine and V7's consensus stage both compare annotators with
**raw IoU against a per-class threshold**. Neither applies any chance
correction. That makes the headline number uninterpretable on its own:

> A corpus where every image holds one large, centred object will show a mean
> IoU around 0.95 no matter who annotates it — including annotators who never
> looked at the image and simply drew a box in the middle.

Chance correction is what separates "these annotators agree" from "this task is
too easy to disagree on".

## Why not Krippendorff's α over 1 − IoU

That was this project's original plan, and it is empirically the wrong default.

Braylan, Alonso and Lease (WWW 2022, *Measuring Annotator Agreement Generally
across Complex Structured, Multi-object, and Free-text Annotation Tasks*)
evaluate candidate distance functions by whether the resulting agreement score
**ranks annotator quality correctly** — the only property that really matters —
and report that for bounding boxes, α ranks plain L2 (0.687) *above* IoU (0.505)
and GIoU (0.507), inverting the ordering their own distribution-based measures
and practitioners both give.

There is a structural reason. IoU distance is bounded in [0, 1] and saturates:
two randomly paired shapes almost always have IoU 0, so expected disagreement
collapses to ≈1 and α degenerates to `1 − mean distance` with no working chance
correction left in it.

Plain IoU is also **flat where it matters most**. Two boxes that do not overlap
score 0 whether they are touching or at opposite corners of the image — so the
measure has no gradient exactly where annotators disagree.

## What Potato reports instead

### σ (sigma) — the primary measure

```
σ = 1 − mean(within-item distance) / mean(between-item distance)
```

This is α's own `1 − D_o/D_e` form generalized to an arbitrary distance, with
the chance baseline estimated empirically by comparing annotations of
**different items**.

| σ | Meaning |
|---|---|
| 1.0 | Perfect agreement |
| 0.0 | Annotators agree no more than they would on unrelated items |
| < 0 | Systematic disagreement — usually a *definition* problem, not carelessness |

Negative values are **not clamped**. "Further apart on the same image than on
different images" is a real, diagnosable state and hiding it helps nobody.

### KS — the robust companion

The two-sample Kolmogorov–Smirnov statistic between the within-item and
between-item distance *distributions*. σ compares two means and can be dragged
by a few outliers; KS compares the whole distributions and holds up better when
item difficulty varies a lot.

Report both. They disagreeing is itself informative: it means a minority of
items is driving the mean.

### GIoU as the default distance

Generalized IoU (Rezatofighi et al., CVPR 2019) subtracts the share of the
smallest enclosing box that neither annotator's shape occupies, so a near-miss
scores better than a wild miss. That restores the gradient plain IoU lacks.

`centroid` (normalized L2) and `iou` are also available. **Every offered
distance is tested for the ordering property** — noisier annotations must score
lower — and one that failed would be removed rather than shipped.

## Three questions, not one

Annotators can disagree about whether an object exists, what it is, and where
its boundary lies. These have different causes and different fixes, so Potato
reports them separately.

| Measure | Question | Method |
|---|---|---|
| `detection_alpha` | Did they find the same objects? | α over present/absent per matched cluster |
| `classification_alpha` | Do they agree what it is? | α over labels, matched objects only |
| `sigma` / `ks` | Do they agree where it is? | σ/KS over matched-pair distances |

Detection and classification are genuine **categorical** variables, so α applies
without any of the objections above — and the same decomposition is what lets
MACE estimate per-annotator competence on those parts.

Reading them together:

| detection | localization | Diagnosis |
|---|---|---|
| high | low | They agree what to annotate; drawing guidelines are too loose |
| low | high | They draw well; the definition of "an object" is unclear |
| low | low | The task needs rethinking, not more annotators |

A single blended 0.65 would suggest none of these.

## 3D boxes

Cuboids flow through exactly the same machinery — matched, then split into the
same three questions — because the only thing that has to change is the
distance between two shapes. The measure is **volumetric IoU, exact for any
rotation**.

That last part is a deliberate cost. The usual approach is bird's-eye-view IoU
multiplied by vertical overlap, which is exact when both boxes are level and
silently wrong when either is not. Potato's storage contract carries a full
quaternion precisely so that drone, handheld and indoor-scan data are
representable, so an agreement measure that quietly degraded on exactly those
datasets would undo the decision. Instead, two boxes are treated as twelve
half-spaces and the shared volume comes out of the divergence theorem over the
resulting faces.

| Type | Distance |
|---|---|
| `cuboid_3d` | 1 − volumetric IoU, exact under arbitrary rotation |
| `point_3d` | Euclidean, with a 2 m falloff — two annotators clicking the same lamppost in a sparse cloud will not agree to the centimetre |
| `polyline_3d` | Boundary F1 in **three** dimensions; two paths tracing the same ground track at different heights are not the same annotation |
| `segment_3d` | Jaccard over point indices, which *is* IoU when the unit is a point |

Vertically separated boxes score 0, not 1: a sign that BEV-only comparison is
not being used anywhere.

## When a number is undefined

α divides by expected disagreement. A corpus where every annotator gave the
same answer everywhere has D<sub>e</sub> = 0, so α is **genuinely undefined —
not 1.0**.

Potato reports `NaN` *with a reason*:

```json
{"detection_alpha": NaN,
 "detection_alpha_note": "every annotator found every object, so there is no
   variation for alpha to correct against. Perfect agreement, not a failed
   computation."}
```

A bare NaN cannot be told apart from a broken computation, and someone will
eventually read one as the other.

## Matching, and its one honest weakness

Objects are paired across annotators by the Hungarian algorithm on IoU
(globally optimal when scipy is present; greedy best-first otherwise), above a
threshold that defaults to 0.5.

**The threshold is a real modelling choice, not an implementation detail.** Two
boxes at IoU 0.4 are recorded as a *detection* disagreement — two different
objects — where a human reviewer would likely call them one object drawn
sloppily. Lower the threshold and sloppy work is re-attributed from detection to
localization.

There is no correct universal value. If your objects are small or your
annotators are imprecise, lower it and say so in your methods section.

## Confidence intervals

Percentile bootstrap, resampling **items** rather than instances:

```python
report = geometry_agreement(items, bootstrap=200)
report["confidence"]   # {"sigma_lower": .., "sigma_upper": .., "n_resamples": ..}
```

Two boxes on one image are not independent observations. Resampling instances
individually produces intervals far too narrow to be honest.

The chance baseline is sampled, so the seed is fixed by default: an agreement
number that moves between runs of identical data cannot go in a paper.

## Usage

```python
from potato.server_utils.iaa.geometry_agreement import geometry_agreement

report = geometry_agreement(
    {"image_1": {"alice": [obj, ...], "bob": [obj, ...]}},
    distance="giou",        # giou | centroid | iou
    threshold=0.5,
    bootstrap=200,
)
```

The admin agreement report includes `sigma`, `ks`, `detection_alpha` and
`classification_alpha` for every `image_annotation` schema automatically,
alongside the uncorrected `mean_matched_iou` and `detection_f1`.

## Mask consensus: whose boundary do you trust?

σ answers "do they agree?". It does not answer "whose mask should the dataset
record, and who drew it well?" That is a different question and it needs a
different model.

**MACE cannot do it.** MACE models each annotator as knowing-or-guessing over a
*finite shared label set*; a mask lives in an unbounded space with no
categorical variable to estimate. Forcing masks through it would mean inventing
a label set, and whatever was invented would drive the answer.

**STAPLE can** (Warfield, Zou & Wells, 2004) — the established tool for exactly
this in medical imaging. It runs EM over per-pixel labels and estimates, per
annotator:

| | Meaning | Low value means |
|---|---|---|
| **sensitivity** | of the true foreground, how much did you include? | under-segmenting — drawing inside the boundary |
| **specificity** | of the true background, how much did you correctly exclude? | over-segmenting — drawing generously around it |

Both are reported because they have **opposite fixes**, and a single "accuracy"
number would score the two failure modes identically.

```python
from potato.server_utils.iaa.geometry_agreement import mask_consensus

report = mask_consensus(items, {"image_1": (640, 480)}, label="cell")
report["mean_sensitivity"]   # {"alice": 0.98, "bob": 0.33}
```

### Weighted consensus, not a majority vote

A careful annotator's disagreement moves the consensus more than a careless
one's, and the algorithm works out which is which from the data.

Measured on two careful annotators outnumbered 3-to-2 by noisy ones:

| Method | Dice against truth |
|---|---|
| Majority vote | 0.846 |
| **STAPLE** | **1.000** |

A vote lets the three noisy annotators decide. STAPLE notices that the careful
pair agree with each other and the noisy three do not.

### Caveats worth knowing

- An annotator with three instances of a class contributes their **union**.
  STAPLE compares pixel by pixel; keeping instances apart would require
  matching them across annotators first, which is the detection question and is
  answered separately.
- Items with fewer than two mask-bearing annotators are **counted and skipped**,
  not silently dropped — otherwise coverage is overstated.

## Cost control

Pairwise comparison is quadratic in annotators *and* in instances per item. A
5-annotator project with 50 instances per image costs 25,000 mask decodes per
image, which turns an admin page load into a hang.

There is a hard budget (`max_pairs`, default 200,000). When it is hit:

- the item is skipped **whole**, never half-measured — a partially processed
  item biases the mean toward whichever annotator pair happened to run
- the report sets `truncated: true` and says how many items *did* fit

A truncated agreement number that reads as complete is worse than no number,
because it will be quoted.

## What this does not do

- **Temporal segments** get the uncorrected measures only. σ's baseline is built
  from between-item distances, and "a segment from a different clip" is not a
  meaningful comparison when clips differ in length. Getting that right needs
  its own design.
- **Per-annotator competence over box geometry** is not estimated. Detection and
  classification are categorical and MACE handles them; STAPLE covers masks; the
  box case needs a random-effects treatment that is not built yet.

## Citations

- Krippendorff, K. (2004). *Content Analysis: An Introduction to Its
  Methodology*, 2nd ed. — α and the `1 − D_o/D_e` form.
- Braylan, A., Alonso, O., Lease, M. (2022). Measuring Annotator Agreement
  Generally across Complex Structured, Multi-object, and Free-text Annotation
  Tasks. *WWW '22*. arXiv:2212.09503 — the σ/KS approach and the distance-ranking
  evaluation.
- Rezatofighi, H. et al. (2019). Generalized Intersection over Union: A Metric
  and A Loss for Bounding Box Regression. *CVPR 2019*. — GIoU.
- Warfield, S., Zou, K., Wells, W. (2004). Simultaneous Truth and Performance
  Level Estimation (STAPLE). *IEEE TMI 23(7)*. — named above as the correct tool
  for mask consensus, which Potato does not yet implement.

## Related

- [Image annotation](../annotation-types/multimedia/image_annotation.md)
- [Quality control](../workflow/quality_control.md)
