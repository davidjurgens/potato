# Near-Duplicate Detection

A thousand consecutive video frames are a thousand items and one picture. They
eat a thousand annotations' worth of budget, and they inflate agreement, because
two annotators trivially agree about the same image shown twice.

Dedup is the step most projects re-implement from scratch. Potato does it in
one call.

---

## Quick start

```bash
curl -H "X-API-Key: $KEY" \
  "http://localhost:8000/curation/api/duplicates"
```

```json
{
  "n_items": 400,
  "n_groups": 12,
  "n_duplicates": 217,
  "duplicate_rate": 0.54,
  "largest_group": 41,
  "groups": [
    {"keeper": "f0012", "duplicates": ["f0013", "f0014"], "size": 3,
     "method": "phash"}
  ],
  "note": "217 of 400 item(s) duplicate another. Each is an annotation budget
           paid twice, and each also inflates agreement: two annotators
           trivially agree about the same item shown twice."
}
```

Then stop assigning them:

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"instance_ids": ["f0013", "f0014"]}' \
     http://localhost:8000/curation/api/duplicates/exclude
```

Excluded items stay in the project and stop being assigned. A duplicate is
still evidence of what the dataset contained, and any annotation already made
on one has to stay readable, so nothing is deleted.

---

## Choosing the measure

Most of the difficulty people report with dedup comes from this choice.

### Perceptual hash — the default

`?method=phash` compares adjacent-pixel gradients on a small greyscale grid, so
it survives re-encoding, mild rescaling and brightness shifts while still
telling two different scenes apart. It needs no model, no index and no GPU.

```bash
curl -H "X-API-Key: $KEY" \
  "http://localhost:8000/curation/api/duplicates?method=phash&max_distance=5"
```

`max_distance` is the Hamming distance in bits, out of 64. The default is 5.
Zero catches only byte-identical re-encodings, and past about ten, unrelated
images start joining.

It needs Pillow, which is already a transitive dependency.

### Embeddings for the semantic case

`?method=embedding` is for the same scene from a different angle, or the same
sentence reworded — where the pixels or characters genuinely differ, so a hash
is useless.

```bash
curl -H "X-API-Key: $KEY" \
  "http://localhost:8000/curation/api/duplicates?method=embedding&min_similarity=0.97"
```

This mode requires a built
[curation index](embedding_visualization.md).

!!! warning "Do not reach for embeddings first"
    Two frames of the same scene sit close in embedding space by design, which
    makes an index good at "find me more like this" and wrong for "is this the
    same picture".

    The default threshold of 0.97 sits far above a typical retrieval threshold
    for the same reason. At 0.9 you get items that are merely related, and a
    reviewer then has to check every group by hand.

---

## Grouping

Grouping is transitive: A near B and B near C puts all three together even when
A and C are further apart than the threshold.

A slow pan produces a chain of frames each close to the next. Splitting that
into overlapping pairs would hand a reviewer the same frames several times.

The **keeper**, the item to keep if you collapse the group, is the first by id.
That is stable across runs, so re-running the scan proposes the same exclusions
each time.

Comparison is all-pairs, which is quadratic. That is fine for the tens of
thousands of items a Potato project holds, and an approximate index would be
faster at the cost of changing the answer.

---

## When nothing can be hashed

A project of plain text, or one whose images are remote URLs, produces no
hashes. Potato says so:

```json
"note": "No item could be perceptually hashed — the project may hold no local
         images, or Pillow may not be installed. This is NOT a finding of zero
         duplicates."
```

People act on a dedup report, so "we found nothing" and "we could not look"
have to read differently.

Remote URLs are skipped rather than fetched. Downloading a dataset to
deduplicate it would turn a local scan into an unbounded network job.

---

## Related

- [Reviewing Model Output](../ai-intelligence/model_review.md) — the other
  curation pass worth running before annotation starts
- [Embedding Visualization](embedding_visualization.md) —
  building the index the semantic mode needs
- [Task Assignment](task_assignment.md) — what exclusion changes
