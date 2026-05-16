#!/usr/bin/env python3
"""Smoke runner: agent simulator against coding-agent-review.

Tier-4 smoke. Exercises the new code_review wire format: the rater LLM
produces verdict + per-file comments + per-file ratings; the strategy
serializes them into the {verdict, comments, file_ratings} JSON the
server expects.

Pass criteria:
  - All instances annotated, no errors
  - Each review submission parses as JSON with verdict in the allowed set
  - At least one comment OR file_rating produced across the run

Prerequisites:
  - ollama pull gemma4:e4b
  - Server: python potato/flask_server.py start \\
      examples/agent-traces/coding-agent-review/config.yaml -p 8526

Usage:
  python tests/smoke/run_coding_agent_review_sim.py
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

CONFIG_PATH = REPO_ROOT / 'examples' / 'simulator-configs' / 'simulator-coding-agent-review-ollama.yaml'
ANNOTATION_OUTPUT = REPO_ROOT / 'examples' / 'agent-traces' / 'coding-agent-review' / 'annotation_output'
SERVER_URL = os.environ.get('POTATO_SMOKE_SERVER', 'http://localhost:8526')


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
            user_id=f'sim_coding_review_{run_tag}_{i:02d}',
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
    print('CODING-AGENT REVIEW SMOKE')
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

    review_payloads = []
    verdict_counts = Counter()
    total_comments = 0
    total_file_ratings = 0
    for r in results:
        for record in r.annotations:
            for key, value in record.annotation.items():
                if key == 'review:::review':
                    try:
                        payload = json.loads(value)
                        review_payloads.append(payload)
                        verdict_counts[payload.get('verdict', '?')] += 1
                        total_comments += len(payload.get('comments', []))
                        total_file_ratings += len(payload.get('file_ratings', {}))
                    except json.JSONDecodeError:
                        pass

    print()
    print(f'Review submissions: {len(review_payloads)}')
    print(f'Verdict distribution: {dict(verdict_counts)}')
    print(f'Total comments produced: {total_comments}')
    print(f'Total file ratings produced: {total_file_ratings}')
    for i, p in enumerate(review_payloads):
        print(f'  [{i}] verdict={p.get("verdict")} comments={len(p.get("comments", []))} '
              f'files_rated={len(p.get("file_ratings", {}))}')

    print()
    print(f'Blocked users: {blocked}')
    print(f'Total errors:  {len(errors)}')
    for e in errors[:5]:
        print(f'  - {e}')

    pass_criteria = (
        blocked == 0
        and not errors
        and any(r.annotations for r in results)
        and len(review_payloads) > 0
        and all(
            p.get('verdict') in ('approve', 'request_changes', 'comment_only')
            for p in review_payloads
        )
        and (total_comments > 0 or total_file_ratings > 0)
    )
    print()
    print(f'SMOKE PASS: {pass_criteria}')
    return 0 if pass_criteria else 1


if __name__ == '__main__':
    sys.exit(main())
