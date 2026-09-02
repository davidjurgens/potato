# Region captioning

One free-text description per region drawn on the image — the annotation behind
dense-captioning and region-grounded VLM training data — plus the thing that is
almost never reported alongside it: **whether two annotators actually agreed.**

```bash
python potato/flask_server.py start examples/image/region-captioning/config.yaml -p 8000
```

The images are generated, so build them first if `media/` is empty:

```bash
cd examples/image/region-captioning && python generate_images.py
```

## What to do in the interface

1. Draw a box or polygon around something.
2. A row appears below the canvas for that region. Type a description.
3. Draw another. Delete one. **The captions stay attached to the right shapes.**

Step 3 is the part worth watching. Captions are matched to regions by *geometry*,
not by position in a list, so deleting the second of three regions carries the
third region's caption with it. A parallel list indexed by position would leave
that caption attached to the wrong shape — which looks exactly like a correct
description of a different object, and is undetectable after the fact.

## Reading the agreement report

With two annotators per item (set here via `num_annotators_per_item`), visit:

```
/admin/iaa
```

The `captions` schema reports:

| Metric | Meaning |
|---|---|
| `alpha` | Krippendorff's alpha with a text distance — chance-corrected |
| `mean_pairwise_distance` | the same distance, **raw** |
| `matching.n_matched_regions` | regions both annotators drew, so captions were comparable |
| `matching.n_unmatched_regions` | regions only one drew — a *detection* disagreement, counted separately |

Both alpha and the raw distance are shown because either alone misleads. A
corpus whose captions are all near-identical can have an undefined or even
negative alpha alongside excellent raw agreement: alpha divides by the expected
disagreement, and when there is almost none, the division is unstable. Only the
pair tells you which situation you are in.

Unmatched regions are **not** scored as caption disagreements. Two annotators
who each drew three regions did not necessarily draw the same three, and
comparing caption *k* with caption *k* would measure the order they happened to
draw in.

## Choosing the text distance

`agreement_distance` in `config.yaml`:

| Value | What it measures | Cost |
|---|---|---|
| `token` (default) | 1 − Jaccard over content tokens | none |
| `embedding` | cosine distance between sentence embeddings | `pip install sentence-transformers` |

The default is a **lower bound**, not a measurement: it scores "a man in a red
shirt" against "person wearing a crimson top" as complete disagreement, because
they share no content word.

`embedding` is better and still not a semantic verdict — measured against
`all-MiniLM-L6-v2`, that same pair comes out at **0.598**, not near zero.
Swapping both the colour word and the garment word defeats a small model. What
does hold is the separation: paraphrases land well below unrelated captions, and
that ordering is what alpha needs. See
`tests/unit/test_caption_embedding_distance.py`, which measures this on request:

```bash
POTATO_TEST_EMBEDDINGS=1 pytest tests/unit/test_caption_embedding_distance.py -v
```

When `embedding` is requested and the library is absent, the report falls back
**and says which distance it actually used** — an alpha of 0.3 from a lexical
distance and an alpha of 0.3 from embeddings are different findings, and the
first may be entirely an artifact of vocabulary.

## Why the scenes are shapes

Region captioning is annotated freely, so what varies between annotators is the
*wording*. Photographs would make captions vary because the scene is rich and
ambiguous, which measures the photograph rather than the agreement. Plain shapes
give an obvious subject and a real choice of words for it — and a couple of them
are deliberately between two names ("box" or "rectangle", red or crimson) so the
two distances come out visibly different on real annotations.

## Related

- [VLM Grounding, Pointing & Hallucination Localization](../../../docs/agent-evaluation/vlm_grounding.md)
- [`examples/ai-assisted/grounding-eval/`](../../ai-assisted/grounding-eval/) — the
  inverse task: the phrase is given, and you draw the region it refers to.
