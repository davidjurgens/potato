#!/usr/bin/env python3
"""Smoke runner: Dockerized coding-agent end-to-end.

Tier-5b smoke. Identical to run_live_coding_agent_sim.py except the
agent_proxy runs each action inside an ephemeral Docker container
(--network=none, --memory, --cpus, --read-only). Validates the safer
sandbox path.

Prerequisites:
  - docker pull python:3.11-slim
  - ollama pull llama3.2:3b
  - ollama pull gemma4:e4b
  - Server: python potato/flask_server.py start \\
      examples/agent-testing/coding-agent-docker-test/config.yaml -p 8528

Usage:
  python tests/smoke/run_docker_coding_agent_sim.py
"""
import logging
import os
import shutil
import shutil as _shutil
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

CONFIG_PATH = REPO_ROOT / 'examples' / 'simulator-configs' / 'simulator-docker-coding-ollama.yaml'
ANNOTATION_OUTPUT = REPO_ROOT / 'examples' / 'agent-testing' / 'coding-agent-docker-test' / 'annotation_output'
SERVER_URL = os.environ.get('POTATO_SMOKE_SERVER', 'http://localhost:8528')


def reset_simulator_user_state(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for child in output_dir.iterdir():
        if child.is_dir() and child.name.startswith('sim_'):
            shutil.rmtree(child)


def main() -> int:
    if _shutil.which('docker') is None:
        print('SKIP: docker CLI not found on PATH', file=sys.stderr)
        return 77

    if not CONFIG_PATH.exists():
        print(f'ERROR: simulator config not found: {CONFIG_PATH}', file=sys.stderr)
        return 2

    reset_simulator_user_state(ANNOTATION_OUTPUT)
    config = SimulatorConfig.from_yaml(str(CONFIG_PATH))

    run_tag = time.strftime('%Y%m%d_%H%M%S')
    config.users = [
        UserConfig(
            user_id=f'sim_docker_coding_{run_tag}_{i:02d}',
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
    print('DOCKER CODING-AGENT SMOKE')
    print('=' * 60)
    print(f'Server:    {SERVER_URL}')
    print(f'Config:    {CONFIG_PATH.relative_to(REPO_ROOT)}')
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
    schema_counts = Counter()
    for r in results:
        for record in r.annotations:
            for key in record.annotation.keys():
                if ':' in key:
                    schema = key.split(':', 1)[0]
                    schema_counts[schema] += 1

    print()
    print(f'Per-schema annotation counts: {dict(schema_counts)}')
    print(f'Blocked users: {blocked}')
    print(f'Total errors:  {len(errors)}')
    for e in errors[:5]:
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
