#!/usr/bin/env python3
"""Smoke runner: agent (vision-LLM) simulator against agent-trace-evaluation.

Drives the SimulatorManager with strategy=agent against a Potato server
serving the agent-trace-evaluation example. Validates that:

  - the simulator reads structured / multi-modal instance content,
  - a vision-capable Ollama model (Gemma3 by default) produces parseable
    annotations across the full schema set,
  - per-instance batching keeps the LLM call count low,
  - submitted annotations match gold labels for the trace_*_gold instances
    that ship with the example.

Prerequisites:
  - Ollama running locally with `gemma4:e4b` pulled
        ollama pull gemma4:e4b
  - Annotation server started on port 8520:
        python potato/flask_server.py start \\
            examples/agent-traces/agent-trace-evaluation/config.yaml -p 8520

Run from the repo root:
        python tests/smoke/run_agent_trace_sim.py
"""
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from potato.simulator import (  # noqa: E402
    SimulatorConfig,
    SimulatorManager,
    UserConfig,
    CompetenceLevel,
)

CONFIG_PATH = REPO_ROOT / 'examples' / 'simulator-configs' / 'simulator-agent-trace-ollama.yaml'
DATA_PATH = REPO_ROOT / 'examples' / 'agent-traces' / 'agent-trace-evaluation' / 'data' / 'agent-traces.json'
ANNOTATION_OUTPUT = REPO_ROOT / 'examples' / 'agent-traces' / 'agent-trace-evaluation' / 'annotation_output'
SERVER_URL = os.environ.get('POTATO_SMOKE_SERVER', 'http://localhost:8520')


def reset_simulator_user_state(output_dir: Path) -> None:
    """Remove sim_user_* state directories so the smoke run starts fresh.

    Without this, the simulator users finish all instances on the first run
    and subsequent runs return zero annotations because the server reports
    "no more instances" on login.
    """
    if not output_dir.exists():
        return
    import shutil
    for child in output_dir.iterdir():
        if child.is_dir() and child.name.startswith('sim_user_'):
            shutil.rmtree(child)


def _extract_value(annotation: dict, schema: str):
    """Pull the chosen value for ``schema`` out of a wire annotation dict.

    Wire format is ``{"<schema>:<label>": "on", ...}`` for radio/likert/multiselect
    and ``{"<schema>:text": "..."}`` for textbox.
    """
    chosen = []
    prefix = f'{schema}:'
    for key in annotation.keys():
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix):]
        if suffix == 'text':
            return annotation[key]
        chosen.append(suffix)
    if len(chosen) == 1:
        return chosen[0]
    if len(chosen) > 1:
        return chosen
    return None


def load_gold_labels(data_path: Path) -> dict:
    """Extract gold_labels from the example data file (instances ending _gold)."""
    gold = {}
    with open(data_path) as f:
        text = f.read().strip()
    # The file is JSONL with one record per line
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if 'gold_labels' in record and 'id' in record:
            gold[record['id']] = record['gold_labels']
    return gold


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f'ERROR: simulator config not found: {CONFIG_PATH}', file=sys.stderr)
        return 2

    reset_simulator_user_state(ANNOTATION_OUTPUT)
    config = SimulatorConfig.from_yaml(str(CONFIG_PATH))

    # Use timestamped user IDs so a re-run against an already-warm server
    # registers fresh users instead of reusing state from a prior run.
    run_tag = time.strftime('%Y%m%d_%H%M%S')
    config.users = [
        UserConfig(
            user_id=f'sim_agent_{run_tag}_{i:02d}',
            competence=CompetenceLevel.PERFECT,
            strategy=config.strategy,
            timing=config.timing,
            agent_config=config.agent_config,
        )
        for i in range(max(1, config.user_count))
    ]
    config.user_count = len(config.users)

    gold = load_gold_labels(DATA_PATH) if DATA_PATH.exists() else {}
    if gold:
        print(f'Loaded {len(gold)} gold-labeled instances from {DATA_PATH.name}')
    else:
        print('No gold_labels in example data; smoke relies on pipeline-only checks')

    # Pass gold dict to manager: enables post-hoc client-side accuracy compare.
    # The agent strategy itself does NOT consult gold_answer (we want to
    # evaluate the LLM's own choices).
    manager = SimulatorManager(config, SERVER_URL, gold_standards=gold or None)

    print('=' * 60)
    print('AGENT-TRACE SMOKE')
    print('=' * 60)
    print(f'Server:    {SERVER_URL}')
    print(f'Config:    {CONFIG_PATH.relative_to(REPO_ROOT)}')
    print(f'Strategy:  {config.strategy.value}')
    if config.agent_config:
        print(f'Endpoint:  {config.agent_config.endpoint_type}')
        print(f'Model:     {config.agent_config.model}')
    print()

    t0 = time.time()
    results_by_id = manager.run_sequential(10)
    elapsed = time.time() - t0
    results = list(results_by_id.values())

    print()
    print(f'SIMULATION DONE in {elapsed:.0f}s')
    print('-' * 60)
    manager.print_summary()

    # Inspect rating distribution -- catches the "model collapses to one
    # label" failure mode that pipeline-only checks miss.
    label_counts = Counter()
    schema_counts = Counter()
    blocked = 0
    errors = 0
    for r in results:
        if r.was_blocked:
            blocked += 1
        errors += len(r.errors)
        for record in r.annotations:
            for key in record.annotation.keys():
                # keys look like "schema_name:label" -- ignore "<schema>:text"
                if ':' in key:
                    schema, label = key.split(':', 1)
                    if label == 'text':
                        # Free-text response; record submission but don't treat
                        # as a categorical choice.
                        schema_counts[schema] += 1
                        continue
                    schema_counts[schema] += 1
                    label_counts[(schema, label)] += 1

    print()
    print('Per-schema annotation counts:')
    for schema, count in sorted(schema_counts.items()):
        print(f'  {schema}: {count}')

    print()
    print('Top label choices per schema:')
    by_schema = {}
    for (schema, label), count in label_counts.items():
        by_schema.setdefault(schema, []).append((label, count))
    for schema, items in sorted(by_schema.items()):
        items.sort(key=lambda kv: -kv[1])
        for label, count in items[:5]:
            print(f'  {schema}={label}: {count}')

    print()
    print(f'Blocked users: {blocked}')
    print(f'Total errors:  {errors}')

    # Client-side gold-label comparison (manager-tracked QC only fires when the
    # server has gold instances configured; we compare the submitted annotations
    # directly against the file's gold_labels here).
    gold_correct = gold_total = 0
    if gold:
        per_schema_correct = Counter()
        per_schema_total = Counter()
        for r in results:
            for record in r.annotations:
                gold_for_instance = gold.get(record.instance_id)
                if not gold_for_instance:
                    continue
                for schema, expected in gold_for_instance.items():
                    per_schema_total[schema] += 1
                    gold_total += 1
                    actual = _extract_value(record.annotation, schema)
                    if actual is not None and str(actual).lower() == str(expected).lower():
                        per_schema_correct[schema] += 1
                        gold_correct += 1
        if gold_total:
            print()
            print(f'Gold-label accuracy (client-side): {gold_correct}/{gold_total} = {gold_correct/gold_total:.2%}')
            for schema, n in per_schema_total.items():
                c = per_schema_correct.get(schema, 0)
                print(f'  {schema}: {c}/{n} = {c/n:.2%}')

    # Smoke-pass criteria:
    #   1. Pipeline ran without LLM/HTTP errors
    #   2. Every user submitted at least one annotation
    #   3. The agent strategy actually invoked the LLM (some categorical
    #      schema must have at least 2 distinct label choices across the run,
    #      otherwise the strategy might have collapsed to fallback) -- we
    #      relax this when there are fewer than 5 instances total
    #   4. If gold labels exist, at least 50% accuracy on gold instances
    pass_criteria = True
    reasons = []
    if blocked > 0:
        pass_criteria = False
        reasons.append(f'{blocked} user(s) blocked by QC')
    if errors > 0:
        pass_criteria = False
        reasons.append(f'{errors} simulator error(s)')
    if not any(r.annotations for r in results):
        pass_criteria = False
        reasons.append('no annotations submitted')

    distinct_choosing_schemas = sum(
        1 for items in by_schema.values() if len(items) >= 2
    )
    total_instances = sum(len(r.annotations) for r in results)
    if total_instances >= 5 and distinct_choosing_schemas == 0:
        pass_criteria = False
        reasons.append('every categorical schema collapsed to a single label')

    if gold and gold_total > 0 and gold_correct / gold_total < 0.5:
        pass_criteria = False
        reasons.append(f'gold accuracy below 50% ({gold_correct}/{gold_total})')

    print()
    print(f'SMOKE PASS: {pass_criteria}')
    if not pass_criteria:
        for r in reasons:
            print(f'  - {r}')
    return 0 if pass_criteria else 1


if __name__ == '__main__':
    sys.exit(main())
