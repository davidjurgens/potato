#!/usr/bin/env python3
"""Smoke runner: interactive_chat session driven by simulator + agent rating.

Drives a multi-turn chat against examples/agent-testing/interactive-agent-test
(which ships an `agent_proxy.type: echo` backend, so no external agent is
required), then has the agent strategy rate the resulting trajectory.

Validates that:
  - the user-side persona LLM produces messages,
  - /agent_chat/send + /agent_chat/finish round-trip cleanly,
  - the resulting conversation is captured server-side and re-fetched by
    the simulator before annotation,
  - the agent strategy emits per-task ratings (task_success, naturalness,
    helpfulness) over the chat trajectory.

Prerequisites:
  - ollama pull llama3.2:3b   # persona model
  - ollama pull gemma4:e4b     # rating model
  - server: python potato/flask_server.py start \\
        examples/agent-testing/interactive-agent-test/config.yaml -p 8521

Usage:
        python tests/smoke/run_interactive_agent_sim.py
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

CONFIG_PATH = REPO_ROOT / 'examples' / 'simulator-configs' / 'simulator-interactive-ollama.yaml'
ANNOTATION_OUTPUT = REPO_ROOT / 'examples' / 'agent-testing' / 'interactive-agent-test' / 'annotation_output'
SERVER_URL = os.environ.get('POTATO_SMOKE_SERVER', 'http://localhost:8521')


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
            user_id=f'sim_interactive_{run_tag}_{i:02d}',
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
    print('INTERACTIVE-CHAT SMOKE')
    print('=' * 60)
    print(f'Server:    {SERVER_URL}')
    print(f'Config:    {CONFIG_PATH.relative_to(REPO_ROOT)}')
    if config.interactive:
        print(f'Persona:   {config.interactive.endpoint_type} / {config.interactive.model}')
        print(f'Max turns: {config.interactive.max_turns}')
    if config.agent_config:
        print(f'Rater:     {config.agent_config.endpoint_type} / {config.agent_config.model}')
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
    interactive_errors = [e for e in errors if e.startswith('interactive:')]

    label_counts = Counter()
    schema_counts = Counter()
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

    by_schema = {}
    for (schema, label), count in label_counts.items():
        by_schema.setdefault(schema, []).append((label, count))
    print()
    print('Top label choices per schema:')
    for schema, items in sorted(by_schema.items()):
        items.sort(key=lambda kv: -kv[1])
        for label, count in items[:5]:
            print(f'  {schema}={label}: {count}')

    print()
    print(f'Blocked users:       {blocked}')
    print(f'Total errors:        {len(errors)}')
    print(f'Interactive errors:  {len(interactive_errors)}')
    if interactive_errors:
        for e in interactive_errors[:5]:
            print(f'  - {e}')

    pass_criteria = True
    reasons = []
    if blocked > 0:
        pass_criteria = False
        reasons.append(f'{blocked} user(s) blocked')
    if not any(r.annotations for r in results):
        pass_criteria = False
        reasons.append('no annotations submitted')
    if interactive_errors:
        pass_criteria = False
        reasons.append(f'{len(interactive_errors)} interactive session error(s)')
    # Confirm at least one task_success annotation -- proves rating ran
    if not any(s == 'task_success' for s in schema_counts):
        pass_criteria = False
        reasons.append('rater never produced task_success annotations')

    print()
    print(f'SMOKE PASS: {pass_criteria}')
    if not pass_criteria:
        for r in reasons:
            print(f'  - {r}')
    return 0 if pass_criteria else 1


if __name__ == '__main__':
    sys.exit(main())
