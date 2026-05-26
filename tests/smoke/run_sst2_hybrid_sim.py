#!/usr/bin/env python3
"""Run the SST-2 hybrid-dual-track simulation against the server on port 8510.

Used for live validation of the refinement framework's gate behavior —
prints the refinement log and final per-version agreement at the end.
"""
import json
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

from potato.simulator.solo_mode_simulator import SoloModeSimulator, SoloSimulatorConfig


def main():
    with open('tests/data/sst2_500_gold.json') as f:
        gold = json.load(f)
    gold_flat = {k: v['sentiment'] for k, v in gold.items()}

    config = SoloSimulatorConfig(
        noise_rate=0.10,
        parallel_annotation_count=50,
        active_annotation_count=150,
        task_description=(
            "Classify the sentiment of the movie review as positive or negative. "
            "Labels: positive, negative"
        ),
        schema_name='sentiment',
        max_wait_autonomous=15,
        annotation_delay=1.0,
        wait_for_predictions_timeout=180,
    )

    sim = SoloModeSimulator(
        server_url='http://localhost:8510',
        gold_labels=gold_flat,
        available_labels=['positive', 'negative'],
        config=config,
    )

    t0 = time.time()
    result = sim.run_full_simulation()
    elapsed = time.time() - t0

    s = sim.session
    base = 'http://localhost:8510'
    try:
        status = s.get(f'{base}/solo/api/status', timeout=60).json()
    except Exception as e:
        status = {'error': str(e)}
    try:
        rlog = s.get(f'{base}/solo/api/refinement/log', timeout=60).json()
    except Exception as e:
        rlog = {'error': str(e)}
    try:
        prompts = s.get(f'{base}/solo/api/prompts', timeout=60).json()
    except Exception as e:
        prompts = {'error': str(e)}

    print('\n' + '=' * 60)
    print(f'SIMULATION DONE in {elapsed:.0f}s')
    print('=' * 60)
    print(f'\nsuccess={getattr(result, "success", None)} phases_completed={len(getattr(result, "phase_results", []))}')
    agr = status.get('agreement', {}) if isinstance(status, dict) else {}
    print(f'\nFinal agreement: rate={agr.get("agreement_rate")} compared={agr.get("total_compared")}')
    print(f'Prompt versions: {len(prompts.get("versions", [])) if isinstance(prompts, dict) else "err"}')

    log_entries = rlog.get('log', rlog) if isinstance(rlog, dict) else []
    if isinstance(log_entries, list):
        print(f'\nRefinement cycles recorded: {len(log_entries)}')
        for i, e in enumerate(log_entries):
            baseline = e.get('val_baseline_accuracy', 0)
            cand_accs = e.get('val_candidate_accuracies', {})
            best = max(cand_accs.values()) if cand_accs else 0
            applied = e.get('applied_candidate') is not None
            n = e.get('val_sample_size', 0)
            status_str = 'APPLIED' if applied else 'REJECTED'
            print(f'  [{i+1}] {status_str}: baseline={baseline:.3f} best={best:.3f} '
                  f'n={n} strategy={e.get("strategy")}')
            if e.get('failure_reason'):
                print(f'      reason: {e["failure_reason"]}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
