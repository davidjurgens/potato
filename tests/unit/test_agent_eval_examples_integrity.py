"""Integrity guard for the agent-evaluation example projects.

Root-cause guard for two classes of issue that slipped past lighter checks:

1. **Missing data files.** `config_module.validate_file_paths()` checks that every
   referenced data file exists — but only the *server boot* path calls it; the
   preview CLI does not. So an example with a missing `data/*.json` validates under
   `preview` yet 500s on boot. (This is exactly how the interaction-graph example
   shipped without its data file.) Here we run the real `validate_file_paths` against
   each example so a missing/again-deleted data file fails CI.

2. **Silent layout failures.** `safe_generate_layout` swallows generator exceptions
   into an `annotation-error` error block rather than crashing, so a schema can
   "render" while actually being broken (e.g. `trajectory_eval` choking on
   string `error_types`). Here we generate each scheme from its real example config
   and assert no error sentinel is produced.
"""

import glob
import os

import yaml
import pytest

from potato.server_utils import config_module
from potato.server_utils.schemas.registry import schema_registry

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# The agent/multimodal example projects added in the M-series (+ the recipes).
NEW_EXAMPLE_DIRS = [
    "interaction-graph", "failure-attribution", "handoff-review", "agent-scorecard",
    "tool-contention", "emergent-behavior", "gui-trajectory", "tool-call-review",
    "voice-interaction", "temporal-grounding", "speech-transcript",
    "multimodal-reasoning", "table-grid", "mast-step-tagging", "orchestration-pattern",
]

CONFIGS = [
    os.path.join(PROJECT_ROOT, "examples", "agent-traces", d, "config.yaml")
    for d in NEW_EXAMPLE_DIRS
]


@pytest.mark.parametrize("config_path", CONFIGS, ids=NEW_EXAMPLE_DIRS)
def test_example_config_and_data_files_exist(config_path):
    assert os.path.exists(config_path), f"example config missing: {config_path}"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    example_dir = os.path.dirname(config_path)
    # The real boot-time check: raises ConfigValidationError if any data file is missing.
    config_module.validate_file_paths(cfg, project_dir=example_dir, config_file_dir=example_dir)


@pytest.mark.parametrize("config_path", CONFIGS, ids=NEW_EXAMPLE_DIRS)
def test_example_schemes_render_without_error_block(config_path):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    for scheme in cfg.get("annotation_schemes", []):
        html, _ = schema_registry.generate(scheme)
        assert "annotation-error" not in html, (
            f"{scheme.get('annotation_type')} '{scheme.get('name')}' in {config_path} "
            f"rendered a safe_generate_layout error block (silent failure)"
        )
