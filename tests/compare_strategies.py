#!/usr/bin/env python3
"""Compare refinement strategies side by side on the same dataset.

Runs simulations in parallel against two servers using different strategies
so the results are directly comparable (same random seed, same dataset).
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
    strategy: str  # just for labeling
    gold_file: str
    schema_name: str
    labels: List[str]
    description: str


def run_sim(run_config: RunConfig) -> Dict:
    """Run a single simulation and return full results."""
    logger = logging.getLogger(f"run_{run_config.name}")
    logger.info(f"Starting {run_config.name} on port {run_config.port}")

    with open(run_config.gold_file) as f:
        gold = json.load(f)
    gold_flat = {k: v[run_config.schema_name] for k, v in gold.items()}

    config = SoloSimulatorConfig(
        noise_rate=0.10,
        parallel_annotation_count=50,
        active_annotation_count=150,
        task_description=run_config.description + " Labels: " + ", ".join(run_config.labels),
        schema_name=run_config.schema_name,
        max_wait_autonomous=15,
        annotation_delay=3.0,
        wait_for_predictions_timeout=180,
    )

    sim = SoloModeSimulator(
        server_url=f"http://localhost:{run_config.port}",
        gold_labels=gold_flat,
        available_labels=run_config.labels,
        config=config,
    )

    result = sim.run_full_simulation()
    time.sleep(10)

    s = sim.session
    base = f"http://localhost:{run_config.port}"
    status = s.get(f"{base}/solo/api/status", timeout=120).json()
    rs = s.get(f"{base}/solo/api/refinement-status", timeout=120).json()
    prompts = s.get(f"{base}/solo/api/prompts", timeout=120).json()

    return {
        "name": run_config.name,
        "strategy": run_config.strategy,
        "status": status,
        "refinement": rs,
        "prompts": prompts,
    }


def main():
    tests = [
        RunConfig(
            name="SST-2 focused_edit",
            port=8501,
            strategy="focused_edit",
            gold_file="tests/data/sst2_500_gold.json",
            schema_name="sentiment",
            labels=["positive", "negative"],
            description="Classify the sentiment of the movie review as positive or negative.",
        ),
        RunConfig(
            name="SST-2 generator_critic",
            port=8504,
            strategy="generator_critic",
            gold_file="tests/data/sst2_500_gold.json",
            schema_name="sentiment",
            labels=["positive", "negative"],
            description="Classify the sentiment of the movie review as positive or negative.",
        ),
    ]

    # Run both simulations in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
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

    # Print comparison
    print("\n" + "=" * 80)
    print("STRATEGY COMPARISON")
    print("=" * 80)

    for r in results:
        status = r["status"]
        rs = r["refinement"]
        prompts = r["prompts"]
        pv = status.get("agreement_by_prompt_version", {})
        agr = status.get("agreement_metrics", {})

        print(f"\n{'─' * 70}")
        print(f"{r['name']} (strategy: {r['strategy']})")
        print(f"  Overall: {agr.get('total_compared', 0)} compared, rate={agr.get('agreement_rate', 0):.3f}")
        print(f"  Prompt versions: {prompts.get('current_version', 0)}")
        print(f"  Refinement cycles: {rs.get('total_cycles', 0)}")

        if pv:
            print(f"  Per-version agreement:")
            for v in sorted(pv.keys(), key=lambda x: int(x)):
                d = pv[v]
                comp = d.get('compared', 0)
                rate = d.get('rate', 0)
                print(f"    v{v}: {rate:.3f} (n={comp})")

        cycles = rs.get("cycles", [])
        if cycles:
            print(f"  Cycle results:")
            for c in cycles:
                after = f"{c['agreement_rate_after']:.3f}" if c.get('agreement_rate_after') is not None else "?"
                print(f"    Cycle {c['cycle_number']}: {c['status']}, "
                      f"suggestions={c['suggestions_generated']}, "
                      f"agreement: {c['agreement_rate_before']:.3f} -> {after}")

        # Show final prompt guidelines
        history = prompts.get("history", [])
        if history:
            final = history[-1]
            text = final.get('prompt', '')
            import re
            match = re.search(r'## (?:Annotation|Refinement) Guidelines.*', text, re.DOTALL)
            if match:
                print(f"  Final guidelines ({len(match.group(0))} chars):")
                seen = set()
                for line in match.group(0).split('\n'):
                    stripped = line.strip()
                    if stripped.startswith('- ') and stripped not in seen:
                        seen.add(stripped)
                        print(f"    {stripped[:200]}")

    # Save
    with open('tests/output/strategy_comparison.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to tests/output/strategy_comparison.json")


if __name__ == "__main__":
    main()
