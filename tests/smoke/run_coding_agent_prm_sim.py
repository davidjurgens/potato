#!/usr/bin/env python3
"""Smoke runner: agent simulator against coding-agent-prm.

Tier-3 smoke. Exercises the new process_reward wire format: the rater
LLM picks the first incorrect step in each agent trace; the strategy
expands that into the {steps: [...], mode: "first_error"} JSON the
server expects.

Pass criteria:
  - All instances annotated, no errors
  - process_reward submissions parseable as JSON with the expected shape
  - At least one trace has a first_error_step (i.e. the model is making
    discriminative choices, not always returning "all correct")

Prerequisites:
  - ollama pull gemma4:e4b
  - Server: python potato/flask_server.py start \\
      examples/agent-traces/coding-agent-prm/config.yaml -p 8525

Usage:
  python tests/smoke/run_coding_agent_prm_sim.py
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

CONFIG_PATH = REPO_ROOT / 'examples' / 'simulator-configs' / 'simulator-coding-agent-prm-ollama.yaml'
ANNOTATION_OUTPUT = REPO_ROOT / 'examples' / 'agent-traces' / 'coding-agent-prm' / 'annotation_output'
SERVER_URL = os.environ.get('POTATO_SMOKE_SERVER', 'http://localhost:8525')


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
            user_id=f'sim_coding_prm_{run_tag}_{i:02d}',
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
    print('CODING-AGENT PRM SMOKE')
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

    # PRM-specific introspection
    prm_payloads = []
    overall_quality_counts = Counter()
    for r in results:
        for record in r.annotations:
            for key, value in record.annotation.items():
                if key == 'step_rewards:::step_rewards':
                    try:
                        payload = json.loads(value)
                        prm_payloads.append(payload)
                    except json.JSONDecodeError:
                        pass
                elif ':' in key and not key.endswith(':text'):
                    schema, label = key.split(':', 1)
                    if schema == 'overall_quality':
                        overall_quality_counts[label] += 1

    print()
    print(f'PRM submissions: {len(prm_payloads)}')
    has_first_error = 0
    all_correct = 0
    for p in prm_payloads:
        steps = p.get('steps', [])
        rewards = [s.get('reward') for s in steps]
        n_wrong = sum(1 for r in rewards if r == -1)
        n_correct = sum(1 for r in rewards if r == 1)
        if n_wrong > 0:
            has_first_error += 1
        else:
            all_correct += 1
        print(f'  mode={p.get("mode")} steps={len(steps)} correct={n_correct} wrong={n_wrong}')

    print()
    print(f'Overall quality distribution: {dict(overall_quality_counts)}')

    print()
    print(f'Blocked users: {blocked}')
    print(f'Total errors:  {len(errors)}')
    for e in errors[:5]:
        print(f'  - {e}')

    pass_criteria = (
        blocked == 0
        and not errors
        and any(r.annotations for r in results)
        and len(prm_payloads) > 0
        and all(isinstance(p.get('steps'), list) for p in prm_payloads)
    )
    print()
    print(f'SMOKE PASS: {pass_criteria}')
    return 0 if pass_criteria else 1


if __name__ == '__main__':
    sys.exit(main())
