"""Tests for simulator configuration."""

import pytest
import tempfile
import os
import yaml

from potato.simulator.config import (
    SimulatorConfig,
    TimingConfig,
    LLMStrategyConfig,
    BiasedStrategyConfig,
    UserConfig,
    CompetenceLevel,
    AnnotationStrategyType,
)


class TestTimingConfig:
    """Tests for TimingConfig."""

    def test_defaults(self):
        """Should have sensible defaults."""
        config = TimingConfig()
        assert config.annotation_time_min == 2.0
        assert config.annotation_time_max == 30.0
        assert config.annotation_time_mean == 10.0
        assert config.distribution == "normal"

    def test_custom_values(self):
        """Should accept custom values."""
        config = TimingConfig(
            annotation_time_min=1.0,
            annotation_time_max=60.0,
            distribution="exponential",
        )
        assert config.annotation_time_min == 1.0
        assert config.annotation_time_max == 60.0
        assert config.distribution == "exponential"


class TestLLMStrategyConfig:
    """Tests for LLMStrategyConfig."""

    def test_defaults(self):
        """Should have sensible defaults."""
        config = LLMStrategyConfig()
        assert config.endpoint_type == "openai"
        assert config.temperature == 0.1
        assert config.add_noise is True

    def test_ollama_config(self):
        """Should support Ollama configuration."""
        config = LLMStrategyConfig(
            endpoint_type="ollama",
            model="llama3.2",
            base_url="http://localhost:11434",
        )
        assert config.endpoint_type == "ollama"
        assert config.model == "llama3.2"
        assert config.base_url == "http://localhost:11434"


class TestUserConfig:
    """Tests for UserConfig."""

    def test_defaults(self):
        """Should have sensible defaults."""
        config = UserConfig(user_id="test_user")
        assert config.user_id == "test_user"
        assert config.competence == CompetenceLevel.AVERAGE
        assert config.strategy == AnnotationStrategyType.RANDOM

    def test_custom_values(self):
        """Should accept custom values."""
        config = UserConfig(
            user_id="expert_user",
            competence=CompetenceLevel.PERFECT,
            strategy=AnnotationStrategyType.LLM,
        )
        assert config.competence == CompetenceLevel.PERFECT
        assert config.strategy == AnnotationStrategyType.LLM


class TestSimulatorConfig:
    """Tests for SimulatorConfig."""

    def test_defaults(self):
        """Should have sensible defaults."""
        config = SimulatorConfig()
        assert config.user_count == 10
        assert config.strategy == AnnotationStrategyType.RANDOM
        assert config.parallel_users == 5
        assert config.simulate_wait is False

    def test_competence_distribution_default(self):
        """Should have default competence distribution."""
        config = SimulatorConfig()
        assert "good" in config.competence_distribution
        assert "average" in config.competence_distribution
        assert "poor" in config.competence_distribution

    def test_from_dict(self):
        """Should load from dictionary."""
        data = {
            "user_count": 20,
            "strategy": "biased",
            "competence_distribution": {"good": 0.6, "poor": 0.4},
        }
        config = SimulatorConfig.from_dict(data)
        assert config.user_count == 20
        assert config.strategy == AnnotationStrategyType.BIASED
        assert config.competence_distribution["good"] == 0.6

    def test_from_yaml(self):
        """Should load from YAML file."""
        yaml_content = """
simulator:
  users:
    count: 15
    competence_distribution:
      good: 0.7
      average: 0.3
  strategy: random
  timing:
    annotation_time:
      min: 1.0
      max: 20.0
      distribution: uniform
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            config = SimulatorConfig.from_yaml(f.name)

            assert config.user_count == 15
            assert config.competence_distribution["good"] == 0.7
            assert config.timing.annotation_time_min == 1.0
            assert config.timing.distribution == "uniform"

            os.unlink(f.name)

    def test_from_yaml_with_llm(self):
        """Should load LLM config from YAML."""
        yaml_content = """
simulator:
  strategy: llm
  llm_config:
    endpoint_type: ollama
    model: llama3.2
    base_url: http://localhost:11434
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            config = SimulatorConfig.from_yaml(f.name)

            assert config.strategy == AnnotationStrategyType.LLM
            assert config.llm_config is not None
            assert config.llm_config.endpoint_type == "ollama"
            assert config.llm_config.model == "llama3.2"

            os.unlink(f.name)

    def test_to_dict(self):
        """Should convert to dictionary."""
        config = SimulatorConfig(
            user_count=5,
            strategy=AnnotationStrategyType.BIASED,
            biased_config=BiasedStrategyConfig(
                label_weights={"a": 0.5, "b": 0.5}
            ),
        )
        data = config.to_dict()

        assert data["user_count"] == 5
        assert data["strategy"] == "biased"
        assert data["biased_config"]["label_weights"]["a"] == 0.5

    def test_env_var_expansion(self):
        """Should expand environment variables for API keys."""
        os.environ["TEST_API_KEY"] = "test_key_value"

        yaml_content = """
simulator:
  strategy: llm
  llm_config:
    endpoint_type: openai
    api_key: ${TEST_API_KEY}
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            config = SimulatorConfig.from_yaml(f.name)
            assert config.llm_config.api_key == "test_key_value"

            os.unlink(f.name)

        del os.environ["TEST_API_KEY"]
