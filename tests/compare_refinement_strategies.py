#!/usr/bin/env python3
"""
End-to-end comparison of refinement strategies on the same dataset.

Launches multiple Flask servers, each with a different refinement strategy,
runs the simulator against each in parallel, and reports per-version
agreement trajectories so we can see which strategy produces the best
validated prompt evolution.

Usage:
    # With live vLLM (burger.si.umich.edu:8001):
    python tests/compare_refinement_strategies.py

Requires the dataset + config files already created:
    tests/data/sst2_500.json, tests/data/sst2_500_gold.json, etc.
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logging.getLogger('datasets').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

from potato.simulator.solo_mode_simulator import SoloModeSimulator, SoloSimulatorConfig


@dataclass
class RunConfig:
    name: str
    port: int
    strategy: str
    gold_file: str
    schema_name: str
    labels: List[str]
    description: str


def run_sim(run_config: RunConfig) -> Dict:
    logger = logging.getLogger(f"run_{run_config.name}")
    logger.info(f"Starting {run_config.name} on port {run_config.port}")

    with open(run_config.gold_file) as f:
        gold = json.load(f)
    gold_flat = {k: v[run_config.schema_name] for k, v in gold.items()}

    config = SoloSimulatorConfig(
        noise_rate=0.10,
        parallel_annotation_count=40,
        active_annotation_count=100,
        task_description=run_config.description,
        schema_name=run_config.schema_name,
        max_wait_autonomous=15,
        annotation_delay=2.5,
        wait_for_predictions_timeout=180,
    )
    sim = SoloModeSimulator(
        server_url=f"http://localhost:{run_config.port}",
        gold_labels=gold_flat,
        available_labels=run_config.labels,
        config=config,
    )
    result = sim.run_full_simulation()
    time.sleep(5)

    s = sim.session
    base = f"http://localhost:{run_config.port}"
    status = s.get(f"{base}/solo/api/status", timeout=60).json()
    log = s.get(f"{base}/solo/api/refinement/log", timeout=60).json()
    prompts = s.get(f"{base}/solo/api/prompts", timeout=60).json()

    return {
        "name": run_config.name,
        "strategy": run_config.strategy,
        "status": status,
        "refinement_log": log,
        "prompts": prompts,
    }


def summarize(results: List[Dict]):
    print("\n" + "=" * 80)
    print("REFINEMENT STRATEGY COMPARISON")
    print("=" * 80)

    for r in results:
        status = r["status"]
        log = r["refinement_log"]
        prompts = r["prompts"]
        pv = status.get("agreement_by_prompt_version", {})
        agr = status.get("agreement_metrics", {})

        print(f"\n{'─' * 70}")
        print(f"{r['name']} (strategy: {r['strategy']})")
        print(f"  Overall: {agr.get('total_compared', 0)} compared, rate={agr.get('agreement_rate', 0):.3f}")
        print(f"  Prompt versions: {prompts.get('current_version', 0)}")
        print(f"  Refinement cycles: {log.get('count', 0)}")

        if pv:
            print(f"  Per-version agreement:")
            for v in sorted(pv.keys(), key=lambda x: int(x)):
                d = pv[v]
                comp = d.get('compared', 0)
                rate = d.get('rate', 0)
                print(f"    v{v}: {rate:.3f} (n={comp})")

        # Show log entries
        for entry in log.get('log', []):
            applied = entry.get('applied_candidate') is not None
            baseline = entry.get('val_baseline_accuracy', 0)
            cand_accs = entry.get('val_candidate_accuracies', {})
            best = max(cand_accs.values()) if cand_accs else 0
            gain = best - baseline if cand_accs else 0
            status_str = "APPLIED" if applied else "REJECTED"
            fail = entry.get('failure_reason', '')
            print(f"  {status_str}: baseline={baseline:.3f}, best_cand={best:.3f} ({gain:+.3f})"
                  + (f" [{fail}]" if fail else ""))


if __name__ == "__main__":
    import sys

    # Datasets with corresponding hybrid ports (default lineup)
    dataset_configs = {
        "sst2": RunConfig(
            name="SST-2 hybrid",
            port=8510, strategy="hybrid_dual_track",
            gold_file="tests/data/sst2_500_gold.json",
            schema_name="sentiment", labels=["positive", "negative"],
            description="Classify the sentiment of the movie review as positive or negative.",
        ),
        "agnews": RunConfig(
            name="AG News hybrid",
            port=8511, strategy="hybrid_dual_track",
            gold_file="tests/data/agnews_500_gold.json",
            schema_name="topic",
            labels=["world", "sports", "business", "science_technology"],
            description="Classify the news article into one of: world, sports, business, science_technology.",
        ),
        "tweeteval": RunConfig(
            name="TweetEval Hate hybrid",
            port=8512, strategy="hybrid_dual_track",
            gold_file="tests/data/tweeteval_hate_500_gold.json",
            schema_name="hate_speech", labels=["not_hateful", "hateful"],
            description="Classify whether the tweet contains hate speech.",
        ),
    }

    # Select which datasets to run based on CLI args (default: sst2 only)
    selected = sys.argv[1:] if len(sys.argv) > 1 else ["sst2"]
    tests = [dataset_configs[k] for k in selected if k in dataset_configs]

    if not tests:
        print(f"Usage: python {sys.argv[0]} [sst2] [agnews] [tweeteval]")
        sys.exit(1)

    with ThreadPoolExecutor(max_workers=len(tests)) as executor:
        futures = {executor.submit(run_sim, tc): tc for tc in tests}
        results = []
        for future in as_completed(futures):
            tc = futures[future]
            try:
                results.append(future.result())
                print(f"Completed: {tc.name}")
            except Exception as e:
                print(f"ERROR {tc.name}: {e}")
                import traceback
                traceback.print_exc()

    summarize(results)

    with open('tests/output/refinement_comparison.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to tests/output/refinement_comparison.json")
