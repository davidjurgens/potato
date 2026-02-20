"""
Example validation tests.

Validates that every example in examples/ is self-contained and has valid configuration.
These tests catch broken configs, missing data files, and path errors.
"""

import pytest
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"

# Examples that require external services and should be skipped in CI
SKIP_IN_CI = {
    "ollama-ai-demo": "Requires running Ollama instance",
    "mturk-example": "Requires AWS credentials",
    "image-vllm-rationale": "Requires running vLLM server",
    "image-ai-detection": "Requires AI endpoint",
    "span-ai-keywords-demo": "Requires AI endpoint",
    "active-learning": "Requires AI endpoint",
}


def discover_example_configs():
    """Find all config.yaml files under examples/, excluding simulator-configs."""
    configs = []
    for config_file in EXAMPLES_DIR.rglob("config.yaml"):
        if "simulator-configs" in str(config_file):
            continue
        configs.append(config_file)
    return sorted(configs, key=lambda p: str(p))


def config_id(config_path):
    """Generate a readable test ID from a config path."""
    # e.g. examples/classification/check-box/config.yaml -> classification/check-box
    rel = config_path.relative_to(EXAMPLES_DIR)
    return str(rel.parent)


EXAMPLE_CONFIGS = discover_example_configs()
EXAMPLE_IDS = [config_id(c) for c in EXAMPLE_CONFIGS]


class TestExampleSelfContained:
    """Every example must have all referenced data files present."""

    @pytest.mark.parametrize("config_path", EXAMPLE_CONFIGS, ids=EXAMPLE_IDS)
    def test_data_files_exist(self, config_path):
        config = yaml.safe_load(config_path.read_text())
        config_dir = config_path.parent

        data_files = config.get("data_files", [])
        if isinstance(data_files, str):
            data_files = [data_files]

        for entry in data_files:
            # data_files can be dicts with path key or plain strings
            if isinstance(entry, dict):
                path_val = entry.get("path", entry.get("file", ""))
            else:
                path_val = entry

            if not path_val:
                continue

            resolved = config_dir / path_val
            assert resolved.exists(), (
                f"Missing data file: {path_val} (resolved to {resolved})"
            )

    @pytest.mark.parametrize("config_path", EXAMPLE_CONFIGS, ids=EXAMPLE_IDS)
    def test_surveyflow_files_exist(self, config_path):
        config = yaml.safe_load(config_path.read_text())
        config_dir = config_path.parent

        surveyflow = config.get("surveyflow", {})
        if not isinstance(surveyflow, dict):
            return

        for phase_key, phase_val in surveyflow.items():
            if not isinstance(phase_val, dict):
                continue
            for path_field in ["file", "template"]:
                if path_field in phase_val:
                    path_val = phase_val[path_field]
                    if path_val:
                        resolved = config_dir / path_val
                        assert resolved.exists(), (
                            f"Missing {path_field}: {path_val} in surveyflow.{phase_key}"
                        )


class TestExampleConfigValidity:
    """Every config must parse as valid YAML with required fields."""

    @pytest.mark.parametrize("config_path", EXAMPLE_CONFIGS, ids=EXAMPLE_IDS)
    def test_config_parses(self, config_path):
        config = yaml.safe_load(config_path.read_text())
        assert isinstance(config, dict), "Config must be a YAML mapping"

    @pytest.mark.parametrize("config_path", EXAMPLE_CONFIGS, ids=EXAMPLE_IDS)
    def test_config_has_required_fields(self, config_path):
        config = yaml.safe_load(config_path.read_text())

        has_name = (
            "annotation_task_name" in config
            or "server_name" in config
            or "title" in config
        )
        assert has_name, "Config must have annotation_task_name, server_name, or title"

        has_data = (
            "data_files" in config
            or "data_directory" in config
            or "data_sources" in config
        )
        assert has_data, "Config must have data_files, data_directory, or data_sources"

        assert "annotation_schemes" in config, "Config must have annotation_schemes"

    @pytest.mark.parametrize("config_path", EXAMPLE_CONFIGS, ids=EXAMPLE_IDS)
    def test_config_has_task_dir(self, config_path):
        config = yaml.safe_load(config_path.read_text())
        task_dir = config.get("task_dir", ".")
        assert task_dir == ".", (
            f"Example configs should use task_dir: . for self-containedness, "
            f"got task_dir: {task_dir}"
        )


class TestExampleServerStartup:
    """Every example config must start a server successfully."""

    @pytest.mark.slow
    @pytest.mark.parametrize("config_path", EXAMPLE_CONFIGS, ids=EXAMPLE_IDS)
    def test_server_starts(self, config_path, base_port):
        from tests.integration.base import IntegrationTestServer

        example_name = config_path.parent.name
        if example_name in SKIP_IN_CI:
            pytest.skip(SKIP_IN_CI[example_name])

        server = IntegrationTestServer(str(config_path), port=base_port)
        try:
            success, error = server.start(timeout=30)
            assert success, f"Server failed to start: {error}"
        finally:
            server.stop()
