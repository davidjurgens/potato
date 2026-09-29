# Codebook Lab example

Runs the experiment described in `potato/codebook_lab/`:

1. Generate N variants of `seed_codebook.yaml`, some improved, some
   worsened, some lateral rewrites.
2. Score every variant (plus the seed itself) against `platinum.yaml`,
   per label and overall.
3. Build a "best of breed" hybrid: for each label, take the definition/
   clarification/examples/exclusion-rules from whichever variant scored
   best on that specific label.
4. Score the hybrid the same way and report whether it actually beats
   every single variant.

## Files

- `seed_codebook.yaml` — starting codebook (4 labels: access barriers,
  cost concerns, provider trust, wait times — the same ones from
  `examples/advanced/solo-codebook-example/config.yaml`).
- `platinum.yaml` — 16 hand-written "must get right" examples, 4 per
  label. **Illustrative only** — replace with your own reviewed examples
  before trusting any conclusions from a run.
- `experiment.yaml` — ties the above together plus model config.

## Run it

```bash
ollama serve
ollama pull llama3.2:3b

python -m potato.codebook_lab.cli run examples/advanced/codebook-lab-example/experiment.yaml
```

Output lands in `run/`:

```
run/
  variants/          # one JSON file per generated variant
  scores/            # one JSON file per candidate (seed, each variant, hybrid): every prediction + accuracy
  hybrid.json         # the best-per-label hybrid codebook
  leaderboard.csv     # variant x label accuracy matrix
```

A console leaderboard prints at the end, e.g.:

```
variant                     access barriers  cost concerns  provider trust  wait times  overall
--------------------------------------------------------------------------------------------------
v03_introduce_regression    91.7%            83.3%          75.0%           66.7%       79.2%
seed                        83.3%            83.3%          83.3%           83.3%       83.3%
v01_improve_clarity         91.7%            91.7%          83.3%           83.3%       87.5%
--------------------------------------------------------------------------------------------------
hybrid                      91.7%            91.7%          83.3%           83.3%       87.5%

Hybrid ties the best single variant (v01_improve_clarity) at 87.5%.
```

## Iterating without regenerating

Variant generation is the expensive/slow step (one LLM call per variant).
Re-running the same command reuses whatever's already in `run/variants/`
instead of generating fresh ones — useful for tweaking `platinum.yaml`
and re-scoring the same variant pool. Pass `--regenerate` to force new
variants:

```bash
python -m potato.codebook_lab.cli run examples/advanced/codebook-lab-example/experiment.yaml --regenerate
```

## Using your own codebook/data

Point `experiment.yaml`'s `seed_codebook` and `platinum_examples` at your
own files (same shapes as here — see
`potato/codebook_lab/io_utils.py`'s module docstring), and swap
`generation_model`/`scoring_model` for any endpoint type Potato supports
(openai, anthropic, ollama, ...).
