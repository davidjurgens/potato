#!/usr/bin/env python
"""
codebook_lab — offline experiment: generate N codebook variants, score
them per label against a platinum example set, build a "best of breed"
hybrid, and check whether it actually beats every single variant.

Usage:
    python -m potato.codebook_lab.cli run experiment.yaml
    python -m potato.codebook_lab.cli run experiment.yaml --regenerate

See examples/advanced/codebook-lab-example/ for a runnable experiment
(experiment.yaml, seed_codebook.yaml, platinum.yaml) and its README for
what each file needs to contain.
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import sys
from typing import Any, Dict, List

import yaml

from . import io_utils, report
from .hybridizer import build_hybrid
from .models import CodebookVariant
from .scorer import score_variant
from .variant_generator import generate_variants

logger = logging.getLogger(__name__)


def _resolve(base_dir: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.normpath(
        os.path.join(base_dir, path))


def _seed_as_variant(seed) -> CodebookVariant:
    return CodebookVariant(variant_id="seed", codes=list(seed), origin="seed")


def run_experiment(
    config_path: str, *, regenerate: bool = False,
) -> Dict[str, Any]:
    with open(config_path, "rt", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    base_dir = os.path.dirname(os.path.abspath(config_path))
    output_dir = _resolve(base_dir, cfg.get("output_dir", "codebook_lab_run"))
    os.makedirs(output_dir, exist_ok=True)

    seed = io_utils.load_seed_codebook(
        _resolve(base_dir, cfg["seed_codebook"]))
    label_names = [c.name for c in seed]
    platinum = io_utils.load_platinum_examples(
        _resolve(base_dir, cfg["platinum_examples"]), label_names)
    task_description = cfg.get("task_description", "")
    if not task_description:
        logger.warning(
            "No task_description in %s — the LLM will only see the "
            "codebook block, with no framing of what the overall task "
            "is. Fine for a quick test, but likely to hurt every "
            "variant's accuracy roughly equally.", config_path)

    num_variants = int(cfg.get("num_variants", 8))
    variants_dir = os.path.join(output_dir, "variants")
    existing = sorted(glob.glob(os.path.join(variants_dir, "*.json")))

    variants: List[CodebookVariant]
    if existing and not regenerate:
        logger.info(
            "Loading %d existing variant(s) from %s (pass --regenerate "
            "to make fresh ones instead)", len(existing), variants_dir)
        variants = [io_utils.load_variant(p) for p in existing]
    else:
        gen_endpoint = _build_endpoint(cfg, "generation_model", base_dir)
        variants = generate_variants(gen_endpoint, seed, num_variants)
        for v in variants:
            io_utils.save_variant(output_dir, v)
        logger.info("Generated and saved %d variant(s) to %s",
                    len(variants), variants_dir)

    all_candidates = [_seed_as_variant(seed)] + variants

    score_endpoint = _build_endpoint(
        cfg, "scoring_model", base_dir, fallback_key="generation_model")
    scores = []
    for v in all_candidates:
        s = score_variant(score_endpoint, v, task_description, platinum)
        io_utils.save_score(output_dir, s)
        scores.append(s)

    hybrid = build_hybrid(all_candidates, scores, hybrid_id="hybrid")
    io_utils.save_hybrid(output_dir, hybrid)
    hybrid_score = score_variant(score_endpoint, hybrid, task_description, platinum)
    io_utils.save_score(output_dir, hybrid_score)

    print()
    report.print_leaderboard(scores, label_names, hybrid_score=hybrid_score)
    csv_path = os.path.join(output_dir, "leaderboard.csv")
    report.write_leaderboard_csv(csv_path, scores, label_names, hybrid_score=hybrid_score)
    print(f"\nFull results in {output_dir}/ (variants/, scores/, "
          f"leaderboard.csv, hybrid.json)")

    return {
        "output_dir": output_dir,
        "scores": scores,
        "hybrid_score": hybrid_score,
    }


def _build_endpoint(
    cfg: Dict[str, Any], key: str, base_dir: str, fallback_key: str = None,
):
    from .endpoints import build_endpoint

    model_cfg = cfg.get(key) or (cfg.get(fallback_key) if fallback_key else None)
    if not model_cfg:
        raise ValueError(
            f"Experiment config is missing '{key}' "
            f"(and no '{fallback_key}' to fall back to)" if fallback_key
            else f"Experiment config is missing '{key}'")
    endpoint = build_endpoint(model_cfg)
    if endpoint is None:
        raise RuntimeError(
            f"Could not create an endpoint for '{key}': {model_cfg}. "
            f"Check the model is reachable (e.g. `ollama serve` running, "
            f"model pulled) and the config is correct.")
    return endpoint


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m potato.codebook_lab.cli",
        description="Generate, score, and hybridize codebook variants "
                     "against a platinum example set.")
    parser.add_argument("command", choices=["run"], help="Only 'run' for now")
    parser.add_argument("config_file", help="Path to experiment.yaml")
    parser.add_argument(
        "--regenerate", action="store_true",
        help="Generate fresh variants even if output_dir/variants/ already "
             "has some (default: reuse them, so re-scoring/hybridizing is free).")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S")

    if not os.path.isfile(args.config_file):
        print(f"Config not found: {args.config_file}", file=sys.stderr)
        return 2

    try:
        run_experiment(args.config_file, regenerate=args.regenerate)
    except Exception as e:
        logger.error("Run failed: %s", e, exc_info=args.verbose)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
