#!/usr/bin/env python3
"""
View the refinement log for a solo mode state directory.

Usage:
    python scripts/view_refinement_log.py <state_dir>
    python scripts/view_refinement_log.py tests/output/sst2-hybrid-test/solo_state

Shows:
- Each refinement cycle's success/failure, baseline, candidate accuracies
- Applied candidate contents
- Per-version agreement trajectory
- ICL library contents
"""
import json
import sys
from pathlib import Path


def print_refinement_log(state_dir: str):
    state_file = Path(state_dir) / "solo_mode_state.json"
    if not state_file.exists():
        print(f"State file not found: {state_file}")
        sys.exit(1)

    with open(state_file) as f:
        state = json.load(f)

    print("=" * 80)
    print(f"Refinement log for {state_dir}")
    print("=" * 80)

    # Agreement trajectory
    pv = state.get('per_version_agreement', {})
    if pv:
        print("\n── Per-version agreement ──")
        for v in sorted(pv.keys(), key=lambda x: int(x)):
            d = pv[v]
            comp = d.get('compared', 0)
            ag = d.get('agreements', 0)
            rate = ag / comp if comp > 0 else 0
            print(f"  v{v}: {ag}/{comp} = {rate:.3f}")

    # Refinement log
    log = state.get('refinement_log', [])
    print(f"\n── Refinement cycles ({len(log)}) ──")
    for i, entry in enumerate(log):
        applied = entry.get('applied_candidate') is not None
        status = "APPLIED" if applied else "REJECTED"
        if entry.get('dry_run'):
            status = "DRY-RUN " + status
        strategy = entry.get('strategy', 'unknown')
        baseline = entry.get('val_baseline_accuracy', 0)
        cand_accs = entry.get('val_candidate_accuracies', {})
        best = max(cand_accs.values()) if cand_accs else 0
        gain = best - baseline if cand_accs else 0
        n = entry.get('val_sample_size', 0)

        print(f"\n  Cycle {i+1}: {status} (strategy={strategy})")
        print(f"    Baseline val accuracy: {baseline:.3f} ({n} samples)")
        if cand_accs:
            print(f"    Candidate accuracies:")
            for idx, acc in cand_accs.items():
                marker = "*" if applied and idx == str(list(cand_accs.keys())[max(cand_accs, key=cand_accs.get) if False else 0]) else " "
                diff = acc - baseline
                print(f"      [{idx}] {acc:.3f} ({diff:+.3f} vs baseline)")
        print(f"    Best: {best:.3f} ({gain:+.3f} vs baseline)")
        if entry.get('failure_reason'):
            print(f"    Failure: {entry.get('failure_reason')}")

        if applied:
            cand = entry['applied_candidate']
            print(f"    Applied: kind={cand.get('kind')}, by={cand.get('proposed_by')}")
            payload = cand.get('payload', {})
            if isinstance(payload, dict) and 'rules' in payload:
                for r in payload['rules']:
                    print(f"      - {r[:160]}")
            elif isinstance(payload, dict) and 'text' in payload:
                print(f"      Example: \"{payload['text'][:100]}\" -> {payload.get('label')}")
            elif isinstance(payload, str):
                print(f"      {payload[:160]}")

    # Pending approvals
    pending = state.get('pending_refinements', [])
    if pending:
        print(f"\n── Pending approvals ({len(pending)}) ──")
        for i, entry in enumerate(pending):
            cand = entry.get('applied_candidate', {})
            baseline = entry.get('val_baseline_accuracy', 0)
            cand_accs = entry.get('val_candidate_accuracies', {})
            best = max(cand_accs.values()) if cand_accs else 0
            print(f"  [{i}] {cand.get('kind', '?')} by {cand.get('proposed_by', '?')}")
            print(f"      baseline={baseline:.3f}, best={best:.3f} (+{best - baseline:.3f})")

    # ICL library
    icl = state.get('icl_library')
    if icl and icl.get('entries'):
        print(f"\n── ICL library ({len(icl['entries'])} validated examples) ──")
        for e in icl['entries']:
            print(f"  [{e['instance_id']}] label={e['label']}, gain=+{e.get('val_accuracy_gain', 0):.3f}")
            print(f"    \"{e['text'][:100]}\"")
            if e.get('principle'):
                print(f"    Principle: {e['principle'][:120]}")

    print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    print_refinement_log(sys.argv[1])
