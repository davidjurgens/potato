# Run from the repo root: python examples/advanced/codebook-lab-naacl-frames/run_laya.py
"""Seed + generated variants -> score on dev with Laya -> hybrid built from
dev per-label winners -> score everything on held-out test. Choosing the
hybrid's parts and scoring it on the same set would flatter it (it picks
up per-label noise), so the honest comparison is the test leaderboard.
Prints a paired bootstrap of hybrid vs seed and vs the best single
variant (chosen on dev)."""
import glob, json, logging, os, random, sys, yaml
sys.path.insert(0, os.getcwd())
from potato.codebook_lab import io_utils, report
from potato.codebook_lab.hybridizer import build_hybrid
from potato.codebook_lab.laya_scorer import score_from_probs, score_variant_laya
from potato.codebook_lab.models import CodebookVariant, VariantScore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
d = "examples/advanced/codebook-lab-naacl-frames"
cfg = yaml.safe_load(open(f"{d}/experiment.yaml"))
lc = cfg["laya"]
out = f"{d}/{cfg['output_dir']}"
seed = io_utils.load_seed_codebook(f"{d}/{cfg['seed_codebook']}")
labels = [c.name for c in seed]
dev = io_utils.load_platinum_examples(f"{d}/{cfg['dev_examples']}", labels, multi_label=True)
test = io_utils.load_platinum_examples(f"{d}/{cfg['test_examples']}", labels, multi_label=True)
variants = [io_utils.load_variant(p) for p in sorted(glob.glob(f"{out}/variants/*.json"))]
candidates = [CodebookVariant("seed", list(seed), origin="seed")] + variants


def score_all(split, examples, cands):
    scores, probs = [], {}
    for v in cands:
        s, p = score_variant_laya(lc["base_url"], v, examples, cfg.get("task_description", ""),
                                  lc["head_max_len"], lc["threshold"])
        io_utils.save_score(f"{out}/{split}", s)
        io_utils._dump_structured(f"{out}/{split}/probs/{v.variant_id}.json", p)
        scores.append(s)
        probs[v.variant_id] = p
    return scores, probs


dev_scores, _ = score_all("dev", dev, candidates)
hybrid = build_hybrid(candidates, dev_scores, hybrid_id="hybrid")
io_utils.save_hybrid(out, hybrid)
dev_hybrid, _ = score_all("dev", dev, [hybrid])
test_scores, test_probs = score_all("test", test, candidates + [hybrid])
test_hybrid = test_scores.pop()

for split, sc, hy in (("dev", dev_scores, dev_hybrid[0]), ("test", test_scores, test_hybrid)):
    print(f"\n===== {split.upper()} ({'hybrid parts chosen here' if split == 'dev' else 'held out'}) =====")
    report.print_leaderboard(sc, labels, hybrid_score=hy)
    report.write_leaderboard_csv(f"{out}/leaderboard_{split}.csv", sc, labels, hybrid_score=hy)

# Paired bootstrap over test items: resample items, recompute macro-F1.
best_dev = max(dev_scores, key=lambda s: s.overall_score).variant_id
by_id = {s.variant_id: s for s in test_scores}
rng = random.Random(0)
n = len(test)


def macro_f1(score, idx):
    return VariantScore("x", [score.predictions[i] for i in idx], multi_label=True).overall_score


results = {"best_single_on_dev": best_dev, "hybrid_sources": hybrid.notes,
           "test_macro_f1": {s.variant_id: s.overall_score for s in test_scores + [test_hybrid]},
           "dev_macro_f1": {s.variant_id: s.overall_score for s in dev_scores + dev_hybrid}}
print(f"\nHybrid parts: {hybrid.notes}")
for other in sorted({"seed", best_dev}):
    diffs = []
    for _ in range(1000):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(macro_f1(test_hybrid, idx) - macro_f1(by_id[other], idx))
    diffs.sort()
    obs = test_hybrid.overall_score - by_id[other].overall_score
    p_le0 = sum(x <= 0 for x in diffs) / len(diffs)
    results[f"hybrid_minus_{other}"] = {"diff": obs, "ci95": [diffs[25], diffs[974]], "p_hybrid_not_better": p_le0}
    print(f"TEST hybrid - {other}: {obs:+.4f} macro-F1, 95% CI [{diffs[25]:+.4f}, {diffs[974]:+.4f}], "
          f"P(diff<=0)={p_le0:.3f}")
io_utils._dump_structured(f"{out}/summary.json", results)
