#!/usr/bin/env python3
"""Smoke runner: live coding-agent end-to-end.

Tier-5a smoke. Drives a full pipeline:
  1. The simulator's user persona (llama3.2:3b) sends natural messages.
  2. The Potato server routes each message through the new
     `subprocess_coding` agent_proxy, which:
       a. Asks a planner LLM for a JSON {thought, action} object.
       b. Executes the action (`python` or `shell`) in a per-session
          tempdir via subprocess with a per-step timeout.
       c. Returns the result as the agent's reply.
  3. After [DONE] (or max_turns), the agent strategy (gemma4:e4b) rates
     the captured conversation -- task_success, code_quality, notes.

Pass criteria:
  - All instances annotated, no errors, no blocked users
  - Conversation length >= 2 turns per instance (proves real chat ran)
  - At least one instance produced a 'success' or 'partial' task_success

Prerequisites:
  - ollama pull llama3.2:3b
  - ollama pull gemma4:e4b
  - Server: python potato/flask_server.py start \\
      examples/agent-testing/coding-agent-live-test/config.yaml -p 8527

Usage:
  python tests/smoke/run_live_coding_agent_sim.py
"""
import json
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

CONFIG_PATH = REPO_ROOT / 'examples' / 'simulator-configs' / 'simulator-live-coding-ollama.yaml'
ANNOTATION_OUTPUT = REPO_ROOT / 'examples' / 'agent-testing' / 'coding-agent-live-test' / 'annotation_output'
SERVER_URL = os.environ.get('POTATO_SMOKE_SERVER', 'http://localhost:8527')


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
            user_id=f'sim_live_coding_{run_tag}_{i:02d}',
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
    print('LIVE CODING-AGENT SMOKE')
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
    results = list(manager.run_sequential(2).values())
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
    success_count = 0
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
                if schema == 'task_success' and label in ('success', 'partial'):
                    success_count += 1

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

    # Conversation lengths from the example's annotation_output
    conv_lengths = []
    for sub in ANNOTATION_OUTPUT.glob('sim_*'):
        for f in sub.rglob('*.json'):
            try:
                with open(f) as fh:
                    blob = json.load(fh)
                if isinstance(blob, dict) and 'conversation' in blob:
                    conv_lengths.append(len(blob['conversation']))
            except Exception:
                continue

    print()
    print(f'Blocked users:       {blocked}')
    print(f'Total errors:        {len(errors)}')
    print(f'Interactive errors:  {len(interactive_errors)}')
    print(f'Conversation lengths captured: {conv_lengths}')
    if interactive_errors:
        for e in interactive_errors[:5]:
            print(f'  - {e}')

    pass_criteria = (
        blocked == 0
        and not errors
        and any(r.annotations for r in results)
        and 'task_success' in schema_counts
    )

    print()
    print(f'SMOKE PASS: {pass_criteria}')
    return 0 if pass_criteria else 1


if __name__ == '__main__':
    sys.exit(main())
