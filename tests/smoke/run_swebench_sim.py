#!/usr/bin/env python3
"""Smoke runner: agent simulator against examples/agent-traces/swebench-evaluation/.

Tier-1 smoke: confirms the existing AgentSimulatorStrategy handles
SWE-bench data without code changes. The example uses standard fields
(task_description, conversation, metadata_table) and standard schemas
(radio/likert/multiselect/text), so the strategy should annotate every
instance and produce non-degenerate label distributions.

Pipeline-only check (no gold labels in this example).

Prerequisites:
  - ollama pull gemma4:e4b
  - Server: python potato/flask_server.py start \\
      examples/agent-traces/swebench-evaluation/config.yaml -p 8523

Usage:
  python tests/smoke/run_swebench_sim.py
"""
import logging
import os
import shutil
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
ANNOTATION_OUTPUT = REPO_ROOT / 'examples' / 'agent-traces' / 'swebench-evaluation' / 'annotation_output'
SERVER_URL = os.environ.get('POTATO_SMOKE_SERVER', 'http://localhost:8523')


def reset_simulator_user_state(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for child in output_dir.iterdir():
        if child.is_dir() and child.name.startswith('sim_'):
            shutil.rmtree(child)


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f'ERROR: simulator config not found: {CONFIG_PATH}', file=sys.stderr)
        return 2

    reset_simulator_user_state(ANNOTATION_OUTPUT)
    config = SimulatorConfig.from_yaml(str(CONFIG_PATH))

    run_tag = time.strftime('%Y%m%d_%H%M%S')
    config.users = [
        UserConfig(
            user_id=f'sim_swebench_{run_tag}_{i:02d}',
            competence=CompetenceLevel.PERFECT,
            strategy=config.strategy,
            timing=config.timing,
            agent_config=config.agent_config,
        )
        for i in range(max(1, config.user_count))
    ]
    config.user_count = len(config.users)

    manager = SimulatorManager(config, SERVER_URL)

    print('=' * 60)
    print('SWEBENCH SMOKE')
    print('=' * 60)
    print(f'Server:    {SERVER_URL}')
    print(f'Config:    {CONFIG_PATH.relative_to(REPO_ROOT)}')
    if config.agent_config:
        print(f'Endpoint:  {config.agent_config.endpoint_type}')
        print(f'Model:     {config.agent_config.model}')
    print()

    t0 = time.time()
    results = list(manager.run_sequential(3).values())
    elapsed = time.time() - t0

    print()
    print(f'SIMULATION DONE in {elapsed:.0f}s')
    print('-' * 60)
    manager.print_summary()

    blocked = sum(1 for r in results if r.was_blocked)
    errors = [e for r in results for e in r.errors]

    schema_counts = Counter()
    label_counts = Counter()
    for r in results:
        for record in r.annotations:
            for key in record.annotation.keys():
                if ':' not in key:
                    continue
                schema, label = key.split(':', 1)
                if label == 'text':
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
    print(f'Total errors:  {len(errors)}')
    for e in errors[:5]:
        print(f'  - {e}')

    pass_criteria = (
        blocked == 0
        and not errors
        and any(r.annotations for r in results)
        and 'patch_correctness' in schema_counts
    )
    print()
    print(f'SMOKE PASS: {pass_criteria}')
    return 0 if pass_criteria else 1


if __name__ == '__main__':
    sys.exit(main())
