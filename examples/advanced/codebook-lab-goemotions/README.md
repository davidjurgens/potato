# Codebook Lab: GoEmotions

The `codebook_lab` experiment (see `../codebook-lab-example/README.md`)
run on a real, unsaturated multi-label benchmark:
[GoEmotions](https://github.com/google-research/google-research/tree/master/goemotions)
(Demszky et al., ACL 2020). The data is Reddit comments labeled with 27
emotions plus neutral. Zero-shot LLMs still trail fine-tuned encoders on
it, and their typical failure is **over-labeling**: they add a nearby
emotion the raters didn't choose. Clearer boundaries in the codebook
should fix that kind of error.

## Files

- `build_dataset.py` downloads GoEmotions and writes the two files
  below. The output is deterministic for a given `--seed`/`--per-label`.
- `seed_codebook.yaml` holds the definitions GoEmotions annotators were
  given. Each label also gets one real train-split example where every
  rater chose only that label. Include/exclude rules start empty; the
  variants fill them in. `neutral` had no published definition, so ours
  is a placeholder.
- `platinum.yaml` has 196 test-split items, about 8 per label (grief
  only has 4 eligible). Every gold label on an item was chosen by a
  strict majority of raters, and no rater flagged the item as very
  unclear. Within each label, unanimous items are taken first (164/196).
- `experiment.yaml` sets `task_type: multi_label`.

## Run it

```bash
python examples/advanced/codebook-lab-goemotions/build_dataset.py   # once

ollama serve
ollama pull llama3.1:8b && ollama pull llama3.2:3b
python -m potato.codebook_lab.cli run examples/advanced/codebook-lab-goemotions/experiment.yaml
```

## How multi-label runs are scored

- The model may return several labels per item. Labels outside the
  codebook are recorded as `invalid_labels` in the score files and make
  that item count as wrong for exact match.
- **Per-label score = F1** over the whole platinum set, so extra labels
  count as false positives and are penalized. The hybridizer picks each
  label's fields from the variant with the best F1 on that label.
- **Overall = macro-F1** across the labels present in the platinum set.
  `overall_accuracy` in the score JSON is the exact-set-match rate, kept
  as a stricter secondary number.

## Caveats

- GoEmotions gold labels are noisy even when raters agree. Read the
  platinum items for the labels you care about before trusting a
  per-label win.
- With 4–8 items per label, one prediction moves per-label F1 by 10–25
  points. Rebuild with `--per-label 16` (rare labels are capped by how
  many eligible items exist) when you want tighter per-label comparisons.
- GoEmotions is public and from 2020, so models may have seen it in
  training. That matters less here than usual, because the experiment
  compares codebook variants against each other on the same model.
