"""
Configuration classes for the user simulator.

This module defines all configuration dataclasses used to configure
the simulator behavior, including user competence, timing, and strategies.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Literal, Union
from enum import Enum
import os
import yaml


class CompetenceLevel(Enum):
    """Competence levels for simulated users.

    Each level defines a range of accuracy for the simulated annotator:
    - PERFECT: 100% accuracy (always matches gold standard)
    - GOOD: 80-90% accuracy
    - AVERAGE: 60-70% accuracy
    - POOR: 40-50% accuracy
    - RANDOM: Random selection (~1/N accuracy for N labels)
    - ADVERSARIAL: Intentionally wrong (avoids gold standard)
    """

    PERFECT = "perfect"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"
    RANDOM = "random"
    ADVERSARIAL = "adversarial"


class AnnotationStrategyType(Enum):
    """Annotation generation strategies.

    - RANDOM: Uniform random selection from available labels
    - BIASED: Weighted random selection based on label preferences
    - LLM: Use an LLM to generate annotations based on text content
    - PATTERN: Consistent per-user patterns for testing specific behaviors
    - GOLD_STANDARD: Use gold answer when available, random otherwise
    """

    RANDOM = "random"
    BIASED = "biased"
    LLM = "llm"
    PATTERN = "pattern"
    GOLD_STANDARD = "gold_standard"


@dataclass
class TimingConfig:
    """Configuration for annotation timing behavior.

    Attributes:
        annotation_time_min: Minimum time per annotation in seconds
        annotation_time_max: Maximum time per annotation in seconds
        annotation_time_mean: Mean time for normal distribution
        annotation_time_std: Standard deviation for normal distribution
        distribution: Timing distribution model (uniform, normal, exponential)
        fast_response_threshold: Threshold for flagging suspiciously fast responses
        session_duration_max: Maximum session duration in minutes (optional)
    """

    annotation_time_min: float = 2.0
    annotation_time_max: float = 30.0
    annotation_time_mean: float = 10.0
    annotation_time_std: float = 5.0
    distribution: Literal["uniform", "normal", "exponential"] = "normal"
    fast_response_threshold: float = 1.0
    session_duration_max: Optional[float] = None


@dataclass
class LLMStrategyConfig:
    """Configuration for LLM-based annotation strategy.

    Uses the existing potato.ai endpoint infrastructure.

    Attributes:
        endpoint_type: LLM provider (openai, anthropic, ollama, etc.)
        model: Model name/identifier
        api_key: API key for cloud providers (can use env var reference)
        base_url: Base URL for local providers like Ollama
        temperature: Temperature for generation (0-2)
        max_tokens: Maximum tokens in response
        add_noise: Whether to occasionally add noise to LLM outputs
        noise_rate: Probability of adding noise (0-1)
    """

    endpoint_type: str = "openai"
    model: Optional[str] = None  # Uses provider default if None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 100
    add_noise: bool = True
    noise_rate: float = 0.05


@dataclass
class BiasedStrategyConfig:
    """Configuration for biased annotation strategy.

    Attributes:
        label_weights: Dictionary mapping label names to selection weights.
            Higher weights mean higher probability of selection.
            Example: {"positive": 0.6, "negative": 0.3, "neutral": 0.1}
    """

    label_weights: Dict[str, float] = field(default_factory=dict)


@dataclass
class PatternStrategyConfig:
    """Configuration for pattern-based annotation strategy.

    Allows defining specific behavior patterns per user.

    Attributes:
        patterns: Dictionary mapping user_id to behavior configuration.
            Each pattern can specify:
            - preferred_label: Label this user tends to select
            - bias_strength: How strongly they prefer it (0-1)
            - keywords: Text patterns that trigger specific labels
    """

    patterns: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class UserConfig:
    """Configuration for a single simulated user.

    Attributes:
        user_id: Unique identifier for this user
        competence: Competence level determining accuracy
        strategy: Annotation strategy type
        timing: Timing configuration for this user
        llm_config: LLM configuration if strategy is LLM
        biased_config: Bias configuration if strategy is BIASED
        pattern_config: Pattern configuration if strategy is PATTERN
        max_annotations: Maximum annotations for this user (optional)
    """

    user_id: str
    competence: CompetenceLevel = CompetenceLevel.AVERAGE
    strategy: AnnotationStrategyType = AnnotationStrategyType.RANDOM
    timing: TimingConfig = field(default_factory=TimingConfig)
    llm_config: Optional[LLMStrategyConfig] = None
    biased_config: Optional[BiasedStrategyConfig] = None
    pattern_config: Optional[PatternStrategyConfig] = None
    max_annotations: Optional[int] = None


@dataclass
class SimulatorConfig:
    """Master configuration for the user simulator.

    Attributes:
        user_count: Number of simulated users to create
        competence_distribution: Distribution of competence levels
            (keys are competence level names, values are proportions)
        users: Explicit list of user configurations (overrides user_count)
        timing: Global timing configuration (can be overridden per-user)
        strategy: Default annotation strategy
        llm_config: LLM configuration for LLM strategy
        biased_config: Bias configuration for biased strategy
        gold_standard_file: Path to JSON file with gold standard labels
        parallel_users: Maximum concurrent users
        delay_between_users: Delay between starting users (seconds)
        attention_check_fail_rate: Rate at which users fail attention checks
        respond_fast_rate: Rate of suspiciously fast responses
        simulate_wait: Whether to actually wait between annotations
        output_dir: Directory for output files
        export_format: Output format (json, csv, jsonl)
    """

    # User configuration
    user_count: int = 10
    competence_distribution: Dict[str, float] = field(
        default_factory=lambda: {"good": 0.5, "average": 0.3, "poor": 0.2}
    )
    users: List[UserConfig] = field(default_factory=list)

    # Global timing configuration
    timing: TimingConfig = field(default_factory=TimingConfig)

    # Strategy configuration - default to random
    strategy: AnnotationStrategyType = AnnotationStrategyType.RANDOM
    llm_config: Optional[LLMStrategyConfig] = None
    biased_config: Optional[BiasedStrategyConfig] = None

    # Gold standard data for competence-based accuracy
    gold_standard_file: Optional[str] = None

    # Execution configuration
    parallel_users: int = 5
    delay_between_users: float = 0.5

    # Quality control testing options
    attention_check_fail_rate: float = 0.0
    respond_fast_rate: float = 0.0

    # Whether to actually wait (set False for fast testing)
    simulate_wait: bool = False

    # Output configuration
    output_dir: str = "simulator_output"
    export_format: Literal["json", "csv", "jsonl"] = "json"

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "SimulatorConfig":
        """Load configuration from YAML file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            SimulatorConfig instance
        """
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        return cls._parse_config(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulatorConfig":
        """Load configuration from dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            SimulatorConfig instance
        """
        return cls._parse_config(data)

    @classmethod
    def _parse_config(cls, data: Dict[str, Any]) -> "SimulatorConfig":
        """Parse configuration from dictionary.

        Args:
            data: Raw configuration dictionary

        Returns:
            SimulatorConfig instance
        """
        # Handle nested 'simulator' key if present
        if "simulator" in data:
            data = data["simulator"]

        # Parse timing config
        timing = TimingConfig()
        if "timing" in data:
            timing_data = data["timing"]
            if "annotation_time" in timing_data:
                at = timing_data["annotation_time"]
                timing = TimingConfig(
                    annotation_time_min=at.get("min", 2.0),
                    annotation_time_max=at.get("max", 30.0),
                    annotation_time_mean=at.get("mean", 10.0),
                    annotation_time_std=at.get("std", 5.0),
                    distribution=at.get("distribution", "normal"),
                    fast_response_threshold=timing_data.get(
                        "fast_response_threshold", 1.0
                    ),
                    session_duration_max=timing_data.get("session_duration_max"),
                )
            else:
                timing = TimingConfig(
                    annotation_time_min=timing_data.get("annotation_time_min", 2.0),
                    annotation_time_max=timing_data.get("annotation_time_max", 30.0),
                    annotation_time_mean=timing_data.get("annotation_time_mean", 10.0),
                    annotation_time_std=timing_data.get("annotation_time_std", 5.0),
                    distribution=timing_data.get("distribution", "normal"),
                    fast_response_threshold=timing_data.get(
                        "fast_response_threshold", 1.0
                    ),
                    session_duration_max=timing_data.get("session_duration_max"),
                )

        # Parse LLM config
        llm_config = None
        if "llm_config" in data:
            llm_data = data["llm_config"]
            # Handle environment variable references
            api_key = llm_data.get("api_key")
            if api_key and api_key.startswith("${") and api_key.endswith("}"):
                env_var = api_key[2:-1]
                api_key = os.environ.get(env_var)

            llm_config = LLMStrategyConfig(
                endpoint_type=llm_data.get("endpoint_type", "openai"),
                model=llm_data.get("model"),
                api_key=api_key,
                base_url=llm_data.get("base_url"),
                temperature=llm_data.get("temperature", 0.1),
                max_tokens=llm_data.get("max_tokens", 100),
                add_noise=llm_data.get("add_noise", True),
                noise_rate=llm_data.get("noise_rate", 0.05),
            )

        # Parse biased config
        biased_config = None
        if "biased_config" in data:
            biased_config = BiasedStrategyConfig(
                label_weights=data["biased_config"].get("label_weights", {})
            )

        # Parse strategy
        strategy_str = data.get("strategy", "random")
        try:
            strategy = AnnotationStrategyType(strategy_str)
        except ValueError:
            strategy = AnnotationStrategyType.RANDOM

        # Parse users section
        users_data = data.get("users", {})
        user_count = users_data.get("count", data.get("user_count", 10))
        competence_dist = users_data.get(
            "competence_distribution",
            data.get(
                "competence_distribution", {"good": 0.5, "average": 0.3, "poor": 0.2}
            ),
        )

        # Parse execution config
        execution = data.get("execution", {})
        parallel_users = execution.get("parallel_users", data.get("parallel_users", 5))
        delay_between = execution.get(
            "delay_between_users", data.get("delay_between_users", 0.5)
        )
        max_annotations = execution.get("max_annotations_per_user")

        # Parse QC config
        qc_config = data.get("quality_control", {})
        attention_fail_rate = qc_config.get(
            "attention_check_fail_rate", data.get("attention_check_fail_rate", 0.0)
        )
        respond_fast_rate = qc_config.get(
            "respond_fast_rate", data.get("respond_fast_rate", 0.0)
        )

        # Parse output config
        output_config = data.get("output", {})
        output_dir = output_config.get("dir", data.get("output_dir", "simulator_output"))
        export_format = output_config.get(
            "format", data.get("export_format", "json")
        )

        return cls(
            user_count=user_count,
            competence_distribution=competence_dist,
            timing=timing,
            strategy=strategy,
            llm_config=llm_config,
            biased_config=biased_config,
            gold_standard_file=data.get("gold_standard_file"),
            parallel_users=parallel_users,
            delay_between_users=delay_between,
            attention_check_fail_rate=attention_fail_rate,
            respond_fast_rate=respond_fast_rate,
            simulate_wait=data.get("simulate_wait", False),
            output_dir=output_dir,
            export_format=export_format,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary.

        Returns:
            Configuration as dictionary
        """
        return {
            "user_count": self.user_count,
            "competence_distribution": self.competence_distribution,
            "timing": {
                "annotation_time_min": self.timing.annotation_time_min,
                "annotation_time_max": self.timing.annotation_time_max,
                "annotation_time_mean": self.timing.annotation_time_mean,
                "annotation_time_std": self.timing.annotation_time_std,
                "distribution": self.timing.distribution,
                "fast_response_threshold": self.timing.fast_response_threshold,
                "session_duration_max": self.timing.session_duration_max,
            },
            "strategy": self.strategy.value,
            "llm_config": (
                {
                    "endpoint_type": self.llm_config.endpoint_type,
                    "model": self.llm_config.model,
                    "temperature": self.llm_config.temperature,
                    "max_tokens": self.llm_config.max_tokens,
                    "add_noise": self.llm_config.add_noise,
                    "noise_rate": self.llm_config.noise_rate,
                }
                if self.llm_config
                else None
            ),
            "biased_config": (
                {"label_weights": self.biased_config.label_weights}
                if self.biased_config
                else None
            ),
            "gold_standard_file": self.gold_standard_file,
            "parallel_users": self.parallel_users,
            "delay_between_users": self.delay_between_users,
            "attention_check_fail_rate": self.attention_check_fail_rate,
            "respond_fast_rate": self.respond_fast_rate,
            "simulate_wait": self.simulate_wait,
            "output_dir": self.output_dir,
            "export_format": self.export_format,
        }
