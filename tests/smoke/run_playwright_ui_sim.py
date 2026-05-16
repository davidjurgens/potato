#!/usr/bin/env python3
"""Smoke runner: Playwright UI driver against agent-trace-evaluation.

Drives the browser end-to-end:
  - registers + logs in via the actual login form,
  - waits through any consent/instructions/training screens,
  - reads each instance's structured payload via API (cookies shared
    with Playwright),
  - generates annotations through the agent strategy (Gemma3 vision),
  - clicks the matching radios / fills textareas via real DOM events,
  - waits for the debounced auto-save to fire,
  - clicks the rendered #next-btn to advance.

This catches UI regressions that the HTTP-only smoke (run_agent_trace_sim.py)
can never see: missing form elements, broken save pipeline, non-functional
Next button, etc.

Prerequisites:
  - pip install playwright && playwright install chromium
  - ollama pull gemma4:e4b
  - ollama serve
  - server: python potato/flask_server.py start \\
      examples/agent-traces/agent-trace-evaluation/config.yaml -p 8522

Usage:
        python tests/smoke/run_playwright_ui_sim.py
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
    UserConfig,
    CompetenceLevel,
)
from potato.simulator.playwright_simulator import PlaywrightSimulatedUser  # noqa: E402

CONFIG_PATH = REPO_ROOT / 'examples' / 'simulator-configs' / 'simulator-playwright-agent-trace.yaml'
ANNOTATION_OUTPUT = REPO_ROOT / 'examples' / 'agent-traces' / 'agent-trace-evaluation' / 'annotation_output'
SERVER_URL = os.environ.get('POTATO_SMOKE_SERVER', 'http://localhost:8522')
HEADLESS = os.environ.get('POTATO_PLAYWRIGHT_HEADLESS', '1') != '0'


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
    user_config = UserConfig(
        user_id=f'sim_pw_{run_tag}',
        competence=CompetenceLevel.PERFECT,
        strategy=config.strategy,
        timing=config.timing,
        agent_config=config.agent_config,
    )

    print('=' * 60)
    print('PLAYWRIGHT UI SMOKE')
    print('=' * 60)
    print(f'Server:    {SERVER_URL}')
    print(f'Config:    {CONFIG_PATH.relative_to(REPO_ROOT)}')
    print(f'Headless:  {HEADLESS}')
    if config.agent_config:
        print(f'Rater:     {config.agent_config.endpoint_type} / {config.agent_config.model}')
    print()

    user = PlaywrightSimulatedUser(
        user_config=user_config,
        server_url=SERVER_URL,
        headless=HEADLESS,
    )

    t0 = time.time()
    result = user.run_simulation(max_annotations=3)
    elapsed = time.time() - t0

    print()
    print(f'SIMULATION DONE in {elapsed:.0f}s')
    print('-' * 60)
    print(f'User: {result.user_id}')
    print(f'Annotations: {len(result.annotations)}')
    print(f'Errors: {len(result.errors)}')
    for e in result.errors[:5]:
        print(f'  - {e}')

    schema_counts = Counter()
    label_counts = Counter()
    for record in result.annotations:
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

    pass_criteria = True
    reasons = []
    if len(result.annotations) == 0:
        pass_criteria = False
        reasons.append('no annotations submitted')
    if len(result.errors) > 0:
        # Allow interactive errors (we don't have one); count others as failures
        non_interactive = [e for e in result.errors if not e.startswith('interactive:')]
        if non_interactive:
            pass_criteria = False
            for e in non_interactive[:3]:
                reasons.append(e)

    print()
    print(f'SMOKE PASS: {pass_criteria}')
    if not pass_criteria:
        for r in reasons:
            print(f'  - {r}')
    return 0 if pass_criteria else 1


if __name__ == '__main__':
    sys.exit(main())
