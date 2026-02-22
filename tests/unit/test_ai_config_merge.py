"""
Tests for external AI config file merging (_merge_ai_config_file).

Tests cover:
- Merging with an external ai-config.yaml file present
- Graceful disable when external file is missing
- Merge precedence (external overrides inline)
- Environment variable substitution in both files
- Backward compatibility (no ai_config_file key = unchanged behavior)
- Edge cases (invalid YAML, non-dict content, non-string ai_config_file)
"""

import os
import pytest
import yaml
import tempfile
import shutil

from potato.server_utils.config_module import _merge_ai_config_file


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test config files."""
    d = tempfile.mkdtemp(prefix="potato_test_ai_config_")
    yield d
    shutil.rmtree(d)


class TestAiConfigMergeBasic:
    """Test basic merge functionality."""

    def test_no_ai_support_section(self, temp_dir):
        """Config without ai_support section is returned unchanged."""
        config = {"annotation_task_name": "test"}
        result = _merge_ai_config_file(config, temp_dir)
        assert result == config
        assert "ai_support" not in result

    def test_no_ai_config_file_key(self, temp_dir):
        """Config with ai_support but no ai_config_file is unchanged (backward compat)."""
        config = {
            "ai_support": {
                "enabled": True,
                "endpoint_type": "ollama",
                "ai_config": {
                    "model": "qwen3:0.6b",
                    "temperature": 0.7,
                },
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["endpoint_type"] == "ollama"
        assert result["ai_support"]["ai_config"]["model"] == "qwen3:0.6b"
        assert result["ai_support"]["ai_config"]["temperature"] == 0.7

    def test_merge_with_external_file(self, temp_dir):
        """External file merges endpoint_type and ai_config values."""
        # Write external config
        external = {
            "endpoint_type": "ollama",
            "model": "qwen3:0.6b",
            "base_url": "http://localhost:11434",
        }
        ext_path = os.path.join(temp_dir, "ai-config.yaml")
        with open(ext_path, "w") as f:
            yaml.dump(external, f)

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "ai-config.yaml",
                "ai_config": {
                    "temperature": 0.7,
                    "max_tokens": 150,
                    "include": {"all": True},
                },
            }
        }
        result = _merge_ai_config_file(config, temp_dir)

        # endpoint_type should be set at ai_support level
        assert result["ai_support"]["endpoint_type"] == "ollama"
        # External values merged into ai_config
        assert result["ai_support"]["ai_config"]["model"] == "qwen3:0.6b"
        assert result["ai_support"]["ai_config"]["base_url"] == "http://localhost:11434"
        # Inline defaults preserved
        assert result["ai_support"]["ai_config"]["temperature"] == 0.7
        assert result["ai_support"]["ai_config"]["max_tokens"] == 150
        assert result["ai_support"]["ai_config"]["include"] == {"all": True}


class TestAiConfigMergePrecedence:
    """Test that external values override inline values."""

    def test_external_overrides_inline(self, temp_dir):
        """External file values take precedence over inline ai_config values."""
        external = {
            "endpoint_type": "vllm",
            "model": "Qwen/Qwen3-4B",
            "temperature": 0.1,
        }
        ext_path = os.path.join(temp_dir, "ai-config.yaml")
        with open(ext_path, "w") as f:
            yaml.dump(external, f)

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "ai-config.yaml",
                "ai_config": {
                    "model": "default-model",
                    "temperature": 0.7,
                    "max_tokens": 150,
                },
            }
        }
        result = _merge_ai_config_file(config, temp_dir)

        # External values win
        assert result["ai_support"]["ai_config"]["model"] == "Qwen/Qwen3-4B"
        assert result["ai_support"]["ai_config"]["temperature"] == 0.1
        assert result["ai_support"]["endpoint_type"] == "vllm"
        # Inline-only values preserved
        assert result["ai_support"]["ai_config"]["max_tokens"] == 150


class TestAiConfigMergeMissingFile:
    """Test graceful handling when external file is missing."""

    def test_missing_file_disables_ai(self, temp_dir):
        """Missing external file disables AI support with a warning."""
        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "nonexistent.yaml",
                "ai_config": {"model": "test"},
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["enabled"] is False

    def test_missing_file_preserves_other_config(self, temp_dir):
        """Missing file disables AI but doesn't remove other config keys."""
        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "nonexistent.yaml",
                "ai_config": {"model": "test", "temperature": 0.5},
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["enabled"] is False
        assert result["ai_support"]["ai_config"]["model"] == "test"


class TestAiConfigMergeEnvVars:
    """Test environment variable substitution."""

    def test_env_var_in_external_file(self, temp_dir, monkeypatch):
        """Environment variables in external file are substituted."""
        monkeypatch.setenv("TEST_API_KEY", "sk-secret123")

        ext_path = os.path.join(temp_dir, "ai-config.yaml")
        with open(ext_path, "w") as f:
            f.write("endpoint_type: openai\nmodel: gpt-4o-mini\napi_key: ${TEST_API_KEY}\n")

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "ai-config.yaml",
                "ai_config": {"temperature": 0.7},
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["ai_config"]["api_key"] == "sk-secret123"

    def test_env_var_in_inline_config_without_external(self, temp_dir, monkeypatch):
        """Environment variables in inline ai_config are substituted even without external file."""
        monkeypatch.setenv("INLINE_KEY", "my-inline-key")

        config = {
            "ai_support": {
                "enabled": True,
                "endpoint_type": "openai",
                "ai_config": {
                    "api_key": "${INLINE_KEY}",
                    "model": "gpt-4o-mini",
                },
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["ai_config"]["api_key"] == "my-inline-key"

    def test_env_var_in_inline_config_with_external(self, temp_dir, monkeypatch):
        """Environment variables in inline ai_config are substituted when external file also used."""
        monkeypatch.setenv("INLINE_TEMP", "0.9")

        external = {"endpoint_type": "ollama", "model": "test"}
        ext_path = os.path.join(temp_dir, "ai-config.yaml")
        with open(ext_path, "w") as f:
            yaml.dump(external, f)

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "ai-config.yaml",
                "ai_config": {
                    "some_value": "${INLINE_TEMP}",
                },
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["ai_config"]["some_value"] == "0.9"


class TestAiConfigMergeEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_yaml_in_external_file(self, temp_dir):
        """Invalid YAML in external file disables AI support."""
        ext_path = os.path.join(temp_dir, "ai-config.yaml")
        with open(ext_path, "w") as f:
            f.write("{{invalid yaml: [")

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "ai-config.yaml",
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["enabled"] is False

    def test_non_dict_external_file(self, temp_dir):
        """External file with non-dict content disables AI support."""
        ext_path = os.path.join(temp_dir, "ai-config.yaml")
        with open(ext_path, "w") as f:
            f.write("- just\n- a\n- list\n")

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "ai-config.yaml",
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["enabled"] is False

    def test_empty_external_file(self, temp_dir):
        """Empty external file is handled gracefully (no crash)."""
        ext_path = os.path.join(temp_dir, "ai-config.yaml")
        with open(ext_path, "w") as f:
            f.write("")

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "ai-config.yaml",
                "ai_config": {"temperature": 0.7},
            }
        }
        # Empty file -> yaml.safe_load returns None -> treated as {}
        result = _merge_ai_config_file(config, temp_dir)
        # Should not crash; AI stays enabled with inline defaults
        assert result["ai_support"]["enabled"] is True
        assert result["ai_support"]["ai_config"]["temperature"] == 0.7

    def test_non_string_ai_config_file(self, temp_dir):
        """Non-string ai_config_file is ignored with a warning."""
        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": 12345,
                "endpoint_type": "ollama",
                "ai_config": {"model": "test"},
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        # Should be unchanged (ignored the invalid ai_config_file)
        assert result["ai_support"]["endpoint_type"] == "ollama"
        assert result["ai_support"]["ai_config"]["model"] == "test"

    def test_ai_support_not_dict(self, temp_dir):
        """Non-dict ai_support is returned unchanged."""
        config = {"ai_support": "invalid"}
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"] == "invalid"

    def test_no_inline_ai_config(self, temp_dir):
        """External file works even when there's no inline ai_config section."""
        external = {
            "endpoint_type": "ollama",
            "model": "qwen3:0.6b",
        }
        ext_path = os.path.join(temp_dir, "ai-config.yaml")
        with open(ext_path, "w") as f:
            yaml.dump(external, f)

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "ai-config.yaml",
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["endpoint_type"] == "ollama"
        assert result["ai_support"]["ai_config"]["model"] == "qwen3:0.6b"

    def test_relative_path_resolution(self, temp_dir):
        """External file path is resolved relative to config directory."""
        # Create a subdirectory with the external config
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)
        ext_path = os.path.join(subdir, "my-ai.yaml")
        with open(ext_path, "w") as f:
            yaml.dump({"endpoint_type": "vllm", "model": "test"}, f)

        config = {
            "ai_support": {
                "enabled": True,
                "ai_config_file": "subdir/my-ai.yaml",
            }
        }
        result = _merge_ai_config_file(config, temp_dir)
        assert result["ai_support"]["endpoint_type"] == "vllm"
