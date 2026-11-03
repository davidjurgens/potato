# Run from the repo root: python examples/advanced/codebook-lab-goemotions/baseline.py
"""Seed-only baseline: score the GoEmotions seed codebook on the platinum set
and save results like codebook_lab does (run_baseline/scores/seed.json +
leaderboard.csv). Prints progress every 10 items."""
import os, sys, time, yaml
sys.path.insert(0, os.getcwd())
from potato.codebook_lab import io_utils, report
from potato.codebook_lab.endpoints import build_endpoint
from potato.codebook_lab.models import CodebookVariant, VariantScore
from potato.codebook_lab.scorer import _render_codebook_section, score_example

d = "examples/advanced/codebook-lab-goemotions"
cfg = yaml.safe_load(open(f"{d}/experiment.yaml"))
seed = io_utils.load_seed_codebook(f"{d}/seed_codebook.yaml")
labels = [c.name for c in seed]
plat = io_utils.load_platinum_examples(f"{d}/platinum.yaml", labels, multi_label=True)
ep = build_endpoint(cfg["scoring_model"])
v = CodebookVariant("seed", seed, origin="seed")
section = _render_codebook_section(v)
preds, t0 = [], time.time()
for i, ex in enumerate(plat, 1):
    preds.append(score_example(ep, v, section, cfg["task_description"], ex, multi_label=True))
    if i % 10 == 0 or i == len(plat):
        print(f"{i}/{len(plat)} done, {time.time()-t0:.0f}s elapsed", flush=True)
s = VariantScore("seed", preds, multi_label=True)
out = f"{d}/run_baseline"
io_utils.save_score(out, s)
report.write_leaderboard_csv(f"{out}/leaderboard.csv", [s], labels)
print(f"DONE macro-F1={s.overall_score:.3f} exact={s.overall_accuracy:.3f}", flush=True)
