# VLM Grounding, Pointing & Hallucination Localization

Three questions about vision-language models that are constantly confused,
separated here because they have different right answers:

| | The question | Scored by |
|---|---|---|
| **Grounding** | "The man in the red shirt" — where is he? | IoU against the annotator's region, at a stated threshold |
| **Pointing** | The model emitted a *point*. Did it land on the thing? | point-in-region hit rate |
| **Ungroundedness** | The caption names something that is not there. | an explicit not-present answer, counted separately |

Runnable example:
[`examples/ai-assisted/grounding-eval/`](https://github.com/davidjurgens/potato/tree/master/examples/ai-assisted/grounding-eval).

---

## The schema

`grounding_eval` binds each referring expression to a region drawn on an
`image_annotation` canvas beside it.

```yaml
annotation_schemes:
  # The canvas. grounding_eval owns the phrase-to-region mapping, not the
  # drawing, so it needs an image schema alongside it.
  - annotation_type: image_annotation
    name: region
    description: "Draw the region for the selected phrase"
    source_field: image
    tools: [bbox, polygon, landmark]
    labels: [{name: referent, color: "#6e56cf"}]

  - annotation_type: grounding_eval
    name: grounding
    description: "What does each phrase refer to?"
    region_type: box            # box | polygon | mask | point
    expressions_field: expressions
```

Items carry their phrases:

```json
{"id": "img1", "image": "/media/img1.jpg",
 "expressions": [{"id": "e1", "text": "the man in the red shirt"}]}
```

A bare list of strings works too — ids fall back to position, which is worth
knowing because reordering the list then re-points existing annotations. A
source with stable ids should use them.

### Options

| Key | Default | Meaning |
|---|---|---|
| `region_type` | `box` | `box`, `polygon`, `mask` or `point` |
| `expression_source` | `field` | `field` reads the item; `spans` selects phrases out of a caption |
| `expressions_field` | `expressions` | Where the phrases live |
| `caption_field` | `caption` | The text to ground, in `spans` mode |
| `predictions_field` | — | Model predictions to review; enables the verdict control |
| `require_all` | `false` | Warn once before advancing with phrases unanswered |

---

## Why the expressions are a list on one item

RefCOCO-style data has several phrases per image, answered against the same
picture. One item per phrase would make the annotator reload and re-read the
image for every one, and would destroy the comparison that matters most: "the
leftmost cup" and "the cup behind the kettle" only mean anything next to each
other.

## Three states, and why the third exists

Each phrase is **located**, **not present**, or **not answered**.

The third is not a kind of the second. An annotator who judged that nothing in
the picture matches a phrase and one who simply has not reached it support
*opposite* conclusions about a model that also produced nothing — a correct
refusal versus no evidence at all. Without an explicit "not present in the
image" control the two are indistinguishable in storage, so the control exists
and every measure keeps them apart.

## One phrase on the canvas at a time

The canvas holds only the selected phrase's region; switching captures, clears
and restores. The alternative — draw everything and tag each shape with its
phrase — needs the image manager to carry a foreign field through serialize,
restore, undo, copy-from-previous and every exporter, and the first path that
drops it silently re-attributes an annotation to the wrong phrase.

The cost is that you cannot see all the regions at once. That is a real loss,
taken deliberately: seeing them all is a display problem, mis-attributing one is
a data problem.

---

## Pointing is not grounding with a small box

Molmo-style models emit points. Set `region_type: point` and the annotator
places a landmark.

The scoring is genuinely different, and this is the part people get wrong: **a
point has no area, so every IoU against it is 0.** Scoring points the way boxes
are scored reports total failure for a model that is pointing perfectly. The
question a point answers is "is it *in* the thing", which is a hit rate:

```python
from potato.grounding import pointing_accuracy

pointing_accuracy([
    {"truth": human_region, "point": {"x": 0.42, "y": 0.31}},
])
# {"point_in_region": 0.83, "n_hits": 5, "mean_miss_distance": 0.21, ...}
```

`mean_miss_distance` is over the **misses only**. Averaged over hits as well it
would mostly measure how large the objects are, not how badly the model missed.

A 0.83 point-in-region rate and a 0.83 grounding accuracy at IoU 0.5 mean
different things and belong in different columns.

---

## Grounding accuracy

```python
from potato.grounding import grounding_accuracy

grounding_accuracy([
    {"truth": human_region, "prediction": model_region},
    {"truth": None, "truth_absent": True, "prediction_absent": True},
])
```

Reported at **several IoU thresholds** — 0.25, 0.5, 0.75, 0.9 — for the same
reason a break-point report sweeps its tolerance: one number cannot distinguish
"nearly right" from "nowhere near", and a model tuned to clear 0.5 exactly looks
identical to one that is genuinely tight.

The absent cases are counted separately rather than folded into the mean,
because none of them is an IoU:

| Count | Meaning |
|---|---|
| `correctly_declined` | Nothing matched, and the model pointed at nothing |
| `hallucinated_a_location` | Nothing matched, and the model pointed anyway |
| `missed_a_present_referent` | Something matched, and the model declined |

An expression the annotator never answered is **excluded** from the
denominator, not counted as a miss. Counting it would make a model look worse
the more phrases were skipped, which is a statement about the annotator.

---

## Agreement between annotators

`grounding_accuracy` above scores a *model* against ground truth. The prior
question — is the ground truth itself reliable? — is answered on
**`/admin/iaa`**, automatically, for any grounding schema with two or more
annotators per item. No configuration is needed beyond
`num_annotators_per_item`.

Unlike free-form image annotation, grounding needs no shape matching: the
expression id says which region corresponds to which. What is left splits into
three findings that have different fixes.

| Group | Question | Metrics |
|---|---|---|
| `detection` | Do they agree the referent is *there*? | `alpha`, `percent_agreement` |
| `localization` | Given both found it, do they agree *where*? | `mean_iou`, `median_iou`, plus an IoU-threshold sweep |
| `coverage` | Did anyone answer at all? | `answered_fraction` |

Reporting one blended number would hide which went wrong. "The annotators
disagree about the red mug" means something different when one of them says
there is no red mug (an ambiguous *expression*) than when both found it and drew
different boxes (a sloppy *drawing*).

`detection` reports alpha **and** raw percent agreement because either alone
misleads: in most corpora nearly every expression is present, so an annotator
who never presses "not present" scores near 1.0 on raw agreement — while alpha,
which corrects for that, is undefined when every answer is identical, a
perfectly normal corpus. When alpha is undefined the report says so in words
rather than printing a bare `n/a`.

### Pointing is measured as distance, not overlap

With `region_type: point`, agreement is reported under `pointing` as the mean
and median **distance** between the annotators' points, in normalized image
units — 0 is perfect.

This is not a stylistic choice. A point has no area, so the region measure falls
back to a distance-derived score compressed into the top of its range: two
annotators pointing at *opposite corners of the image* still score about 0.86,
which the page would band as strong agreement in green. A pointing corpus scored
that way looks near-perfect regardless of what the annotators did. The distance
has no ceiling to saturate against, and is named a distance so nothing bands it
as a coefficient.

---

## Hallucination localization

When the phrases are whatever a model happened to say, they cannot be listed in
advance. Select them out of the caption instead:

```yaml
  - annotation_type: grounding_eval
    name: grounding
    description: "Ground each phrase of the caption"
    expression_source: spans
    caption_field: caption
```

The caption is displayed; the annotator selects a phrase, presses **Ground the
selected phrase**, and then either marks its region or says it is not present.
Grounded and ungrounded phrases are marked in the caption itself — with
different underlines as well as different fills, so they are distinguishable
without relying on hue.

The stored value carries per-caption coverage:

```json
{"coverage": {"caption_chars": 58, "grounded_chars": 11,
              "ungrounded_chars": 11, "grounded_fraction": 0.19,
              "ungrounded_fraction": 0.19}}
```

**Characters, not tokens.** Tokenization is the model's business and two
tokenizers disagree; character offsets are what the annotator actually selected.
A consumer that wants token rates can map them from the offsets, and the reverse
is not possible.

Phrase ids encode their offsets (`span:12-27`), which is what makes an answer
reload-safe and what lets two annotators who selected the same phrase produce
the same id — necessary for any agreement over these answers.

### Why this is not built on `span_link`

The roadmap proposed extending `span_link`'s target type to a geometry object.
On inspection that understates it: `span_link` is span-oriented throughout — it
stores pairs of span ids, draws arcs between two spans in one text, and has its
own link-save API. Targeting a region means a link whose second end is on a
different rendering surface, arcs that cross from text to canvas, and a changed
link shape in storage.

Building it on the grounding machinery instead reuses the phrase→region→absent
model exactly, and the only new part is where the phrases come from. `span_link`
is unchanged.

---

## Region captioning

The inverse task: the annotator draws the regions and supplies the language.

```yaml
  - annotation_type: image_annotation
    name: region
    tools: [bbox, polygon]
    labels: [{name: object, color: "#6e56cf"}]

  - annotation_type: region_caption
    name: descriptions
    description: "Describe each region"
    placeholder: "Describe this region…"
    agreement_distance: token     # or `embedding`
```

The caption list follows the canvas and is rebuilt from it on every change,
with captions carried across by **matching the region they were written about**
rather than by index. That is the part that has to be right: deleting the
second of three regions must carry the third region's caption up with it, and a
parallel list would leave it attached to the wrong shape — silently, and looking
exactly like a correct caption of a different object.

### Caption agreement

Two annotators describing the same thing rarely use the same words. "a man in a
red shirt" and "person wearing a crimson top" are the same answer and share no
content word, so every exact-match coefficient scores them as total
disagreement. That is why caption agreement is almost never reported.

Potato reports it via Krippendorff's alpha with a **pluggable text distance** —
the alpha implementation already accepts a callable, so no new coefficient was
needed:

| `agreement_distance` | What it measures | Cost |
|---|---|---|
| `token` (default) | 1 − Jaccard over content tokens | none |
| `embedding` | cosine distance between sentence embeddings | needs `sentence-transformers` |

**The default is a poor proxy and says so.** It scores the paraphrase above as
complete disagreement, so an alpha computed with it is a *lower bound* on
semantic agreement rather than a measure of it. When `embedding` is requested
and the library is missing, the report falls back **and states which distance it
actually used**, because an alpha of 0.3 under a lexical distance and an alpha
of 0.3 under embeddings are different findings — the first may be entirely an
artifact of vocabulary.

**And `embedding` is better, not good.** Measured against `all-MiniLM-L6-v2`:

| pair | `embedding` | `token` |
|---|---|---|
| "a man in a red shirt" / "person wearing a crimson top" | **0.598** | 1.000 |
| "a small dog on the grass" / "a puppy in the lawn" | 0.358 | 1.000 |
| "two people talking" / "a pair of individuals conversing" | 0.127 | 1.000 |
| "a man in a red shirt" / "an empty parking lot at night" | 1.000 | 1.000 |

The headline paraphrase — the one this section opens with — still scores 0.6,
nowhere near "the same sentence": swapping both the colour word and the garment
word defeats a small model. What holds robustly is the **separation**, every
paraphrase below every unrelated pair by a wide margin, and that is the property
alpha depends on. Treat a single distance as a rough ordering rather than a
semantic verdict, and choose a larger model for long or domain-specific
captions.

These numbers come from a test that runs on request rather than in the suite,
because the suite must not download a model:

```bash
POTATO_TEST_EMBEDDINGS=1 pytest tests/unit/test_caption_embedding_distance.py -v
```

Captions are compared **within regions that matched geometrically**, not by
position: two annotators who each wrote three captions did not necessarily write
them about the same three things, and comparing caption *k* with caption *k*
would measure the order they happened to draw in. A region only one annotator
drew is a **detection** disagreement and is counted as one, rather than being
scored as a caption disagreement, which would blame the wrong thing.

`mean_pairwise_distance` is reported beside alpha because alpha is
chance-corrected and it is not: a corpus whose captions are all near-identical
can have an undefined or negative alpha alongside excellent raw agreement, and
only the pair explains what happened.

---

## Reviewing a model's predictions

Set `predictions_field` and the item's predictions travel to the client, which
adds a verdict control:

```yaml
    predictions_field: model_regions
    verdicts:
      - {name: correct}
      - {name: wrong_object}
      - {name: partial}
      - {name: not_present}
```

Predictions are labelled as predictions all the way through and are **never
merged into the annotator's own regions**. A prediction the annotator has not
accepted is evidence about the model, and folding it into the ground truth
destroys the only thing it is for.

---

## Related

- [Image annotation](../annotation-types/multimedia/image_annotation.md)
- [Geometry agreement](../advanced/geometry_agreement.md)
- [World-model evaluation](world_model_eval.md) — the same absent/answered
  reasoning applied to time rather than space
