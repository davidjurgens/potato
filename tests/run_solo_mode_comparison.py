#!/usr/bin/env python3
"""
Run solo mode simulations across multiple datasets and compare results.

Usage:
    python tests/run_solo_mode_comparison.py

Expects servers running on ports 8501 (SST-2), 8502 (AG News), 8503 (TweetEval Hate).
"""

import json
import logging
import time
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
class TestConfig:
    name: str
    port: int
    gold_file: str
    schema_name: str
    labels: List[str]
    description: str
    expected_difficulty: str  # easy, medium, hard


ALL_GOEMOTION_LABELS = [
    'admiration', 'amusement', 'anger', 'annoyance', 'approval', 'caring',
    'confusion', 'curiosity', 'desire', 'disappointment', 'disapproval',
    'disgust', 'embarrassment', 'excitement', 'fear', 'gratitude', 'grief',
    'joy', 'love', 'nervousness', 'optimism', 'pride', 'realization',
    'relief', 'remorse', 'sadness', 'surprise', 'neutral',
]

TESTS = [
    TestConfig(
        name="SST-2 (2 labels)",
        port=8501,
        gold_file="tests/data/sst2_500_gold.json",
        schema_name="sentiment",
        labels=["positive", "negative"],
        description="Classify the sentiment of the movie review as positive or negative.",
        expected_difficulty="easy",
    ),
    TestConfig(
        name="AG News (4 labels)",
        port=8502,
        gold_file="tests/data/agnews_500_gold.json",
        schema_name="topic",
        labels=["world", "sports", "business", "science_technology"],
        description="Classify the news article into one of: world, sports, business, science_technology.",
        expected_difficulty="medium",
    ),
    TestConfig(
        name="TweetEval Hate (2 labels)",
        port=8503,
        gold_file="tests/data/tweeteval_hate_500_gold.json",
        schema_name="hate_speech",
        labels=["not_hateful", "hateful"],
        description="Classify whether the tweet contains hate speech.",
        expected_difficulty="hard-subjective",
    ),
    TestConfig(
        name="GoEmotions (28 labels)",
        port=8400,
        gold_file="tests/data/goemotion_500_gold.json",
        schema_name="emotion",
        labels=ALL_GOEMOTION_LABELS,
        description="Classify the primary emotion expressed in each Reddit comment.",
        expected_difficulty="very-hard",
    ),
]


def run_test(tc: TestConfig) -> Dict:
    """Run a single test and return results."""
    print(f"\n{'=' * 70}")
    print(f"STARTING: {tc.name} (port {tc.port}, {tc.expected_difficulty})")
    print(f"{'=' * 70}")

    with open(tc.gold_file) as f:
        gold = json.load(f)
    gold_flat = {k: v[tc.schema_name] for k, v in gold.items()}

    config = SoloSimulatorConfig(
        noise_rate=0.10,
        parallel_annotation_count=50,
        active_annotation_count=150,
        task_description=tc.description + " Labels: " + ", ".join(tc.labels),
        schema_name=tc.schema_name,
        max_wait_autonomous=15,
        annotation_delay=3.0,
        wait_for_predictions_timeout=180,
    )

    sim = SoloModeSimulator(
        server_url=f"http://localhost:{tc.port}",
        gold_labels=gold_flat,
        available_labels=tc.labels,
        config=config,
    )

    result = sim.run_full_simulation()
    time.sleep(5)

    # Collect results
    s = sim.session
    base = f"http://localhost:{tc.port}"
    status = s.get(f"{base}/solo/api/status", timeout=120).json()
    agreement = status.get("agreement_metrics", {})
    stats = status.get("annotation_stats", {})

    ca = s.get(f"{base}/solo/api/confusion-analysis", timeout=120).json()
    patterns = ca.get("patterns", [])
    cells = ca.get("matrix_data", {}).get("cells", [])
    nonzero = sorted(
        [c for c in cells if c["count"] > 0],
        key=lambda x: x["count"], reverse=True
    )

    rs = s.get(f"{base}/solo/api/refinement-status", timeout=120).json()
    prompts = s.get(f"{base}/solo/api/prompts", timeout=120).json()

    # Re-annotation report
    reann = {}
    try:
        reann = s.get(f"{base}/solo/api/reannotation-report", timeout=120).json()
    except Exception:
        pass

    return {
        "name": tc.name,
        "difficulty": tc.expected_difficulty,
        "human_labeled": stats.get("human_labeled"),
        "llm_labeled": stats.get("llm_labeled"),
        "compared": agreement.get("total_compared"),
        "agreement_rate": agreement.get("agreement_rate", 0),
        "agreements": agreement.get("agreements"),
        "disagreements": agreement.get("disagreements"),
        "confusion_patterns": len(patterns),
        "top_confusions": nonzero[:5],
        "refinement_cycles": rs.get("total_cycles"),
        "prompt_versions": prompts.get("current_version"),
        "prompt_history": prompts.get("history", []),
        "reannotation": reann,
        "cycles": rs.get("cycles", []),
        "duration": (
            (result.end_time - result.start_time).total_seconds()
            if result.start_time and result.end_time else 0
        ),
    }


def print_comparison(results: List[Dict]):
    """Print comparative results table."""
    print("\n" + "=" * 80)
    print("COMPARISON: Solo Mode Pipeline Across Datasets")
    print("=" * 80)

    # Summary table
    print(f"\n{'Dataset':<30} {'Agree%':>8} {'Compared':>10} {'Patterns':>10} {'Prompts':>9} {'Cycles':>8} {'Time':>8}")
    print("-" * 80)
    for r in results:
        print(
            f"{r['name']:<30} "
            f"{r['agreement_rate']*100:>7.1f}% "
            f"{r['compared']:>10} "
            f"{r['confusion_patterns']:>10} "
            f"{r['prompt_versions']:>9} "
            f"{r['refinement_cycles']:>8} "
            f"{r['duration']:>7.0f}s"
        )

    # Per-dataset details
    for r in results:
        print(f"\n{'─' * 70}")
        print(f"{r['name']} ({r['difficulty']})")
        print(f"  Human: {r['human_labeled']}, LLM: {r['llm_labeled']}")
        print(f"  Agreement: {r['agreements']}/{r['compared']} = {r['agreement_rate']:.3f}")

        if r['top_confusions']:
            print(f"  Top confusions:")
            for c in r['top_confusions'][:3]:
                print(f"    {c['predicted']:>18} -> {c['actual']:<18}: {c['count']}")

        if r['cycles']:
            print(f"  Refinement cycles:")
            for c in r['cycles']:
                changed = f" -> v{c['prompt_version_after']}" if c.get('prompt_version_after') else ""
                after = f"{c['agreement_rate_after']:.3f}" if c.get('agreement_rate_after') is not None else "?"
                print(
                    f"    Cycle {c['cycle_number']}: {c['status']}{changed}, "
                    f"suggestions={c['suggestions_generated']}, "
                    f"agreement: {c['agreement_rate_before']:.3f} -> {after}"
                )

        reann = r.get('reannotation', {})
        if reann.get('total_completed', 0) > 0:
            print(f"  Re-annotation: {reann['total_completed']} completed, "
                  f"improved={reann.get('improved', 0)}, "
                  f"worsened={reann.get('worsened', 0)}, "
                  f"unchanged={reann.get('unchanged', 0)}")

        # Prompt evolution
        history = r.get('prompt_history', [])
        if len(history) > 1:
            v1_len = len(history[0].get('prompt', ''))
            latest_len = len(history[-1].get('prompt', ''))
            print(f"  Prompt: {v1_len} -> {latest_len} chars ({len(history)} versions)")
            for h in history[1:]:
                text = h.get('prompt', '')
                v1_text = history[0].get('prompt', '')
                if text.startswith(v1_text):
                    added = text[len(v1_text):]
                    # Show just the new guidelines
                    guidelines = [l.strip() for l in added.split('\n') if l.strip().startswith('- ')]
                    for g in guidelines[:3]:
                        print(f"    {g}")
                    if len(guidelines) > 3:
                        print(f"    ... ({len(guidelines)} total guidelines)")


if __name__ == "__main__":
    results = []
    for tc in TESTS:
        try:
            r = run_test(tc)
            results.append(r)
        except Exception as e:
            print(f"\nERROR running {tc.name}: {e}")
            import traceback
            traceback.print_exc()

    if results:
        print_comparison(results)

    # Save full results
    output_file = "tests/output/solo_mode_comparison.json"
    with open(output_file, 'w') as f:
        # Remove non-serializable parts
        for r in results:
            for h in r.get('prompt_history', []):
                if 'timestamp' in h:
                    h['timestamp'] = str(h['timestamp'])
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to {output_file}")
