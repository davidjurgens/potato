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
    - AGENT: Vision-capable LLM that reads structured / multi-modal instance
      content (dialogue traces, spreadsheets, image fields) and emits a
      single batched annotation covering every schema for the instance.
    """

    RANDOM = "random"
    BIASED = "biased"
    LLM = "llm"
    PATTERN = "pattern"
    GOLD_STANDARD = "gold_standard"
    AGENT = "agent"


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
class InteractiveConfig:
    """Configuration for driving live ``interactive_chat`` sessions.

    When enabled, the simulator runs a multi-turn chat against the server's
    ``/agent_chat/*`` routes before annotating each instance whose display
    contains an ``interactive_chat`` field. The simulator plays the user
    role; the server-side ``agent_proxy`` plays the agent (echo, OpenAI,
    HTTP, etc. -- whatever the annotation config specifies).

    Attributes:
        enabled: Whether to attempt an interactive session per instance.
        endpoint_type: AI endpoint used to generate the user persona's
            messages. Defaults to ``ollama`` (text only -- the persona
            usually doesn't need vision).
        model: Persona model name. Defaults to provider default.
        api_key: Optional API key (env-var refs supported).
        base_url: Optional endpoint base URL.
        temperature: Sampling temperature for persona messages.
        max_tokens: Per-message token cap.
        max_turns: Hard upper bound on turn count per session.
        persona_system_prompt: System prompt that defines the user persona.
            Should encourage natural multi-turn behavior and a clear
            ``DONE`` signal when the task is complete.
        done_marker: Substring (case-insensitive) the persona emits when
            it considers the task complete. The runner finishes the
            session immediately when seen.
        first_message_template: Template applied to the persona's first
            message. ``{task}`` is replaced with the task description. If
            None, the persona generates the first message from scratch.
    """

    enabled: bool = False
    endpoint_type: str = "ollama"
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 200
    max_turns: int = 6
    persona_system_prompt: str = (
        "You are a curious end-user testing an AI assistant. "
        "Send concise, natural messages that drive the assistant to "
        "complete the task. When the assistant has fully completed the "
        "task, respond with a short acknowledgement and the literal "
        "marker [DONE]."
    )
    done_marker: str = "[DONE]"
    first_message_template: Optional[str] = (
        "Please help me with this task: {task}"
    )


@dataclass
class AgentStrategyConfig:
    """Configuration for the agent (vision-LLM) annotation strategy.

    Drives a vision-capable LLM that consumes structured / multi-modal
    instance content (dialogue arrays, spreadsheets, image fields) and
    produces a batched annotation over every schema for the instance.

    Attributes:
        endpoint_type: AI endpoint (default ``ollama_vision``). Any vision
            endpoint registered with ``AIEndpointFactory`` works
            (``anthropic_vision``, ``openai_vision``, etc.).
        model: Model identifier (e.g. ``gemma3:4b``, ``llava:latest``,
            ``llama3.2-vision``). Defaults to provider default.
        api_key: Cloud-provider API key (env-var refs supported, e.g.
            ``${ANTHROPIC_API_KEY}``).
        base_url: Custom endpoint URL (Ollama: ``http://localhost:11434``).
        temperature: Sampling temperature.
        max_tokens: Cap on response tokens.
        max_image_dim: Resize images so the longest edge is at most this
            many pixels before sending. ``None`` keeps the original.
        max_image_count: Skip image attachment past this many images per
            instance (some models cap at 1–4).
        include_dialogue_text: Render dialogue arrays as
            ``<speaker>: <text>`` lines in the prompt.
        include_spreadsheet: Render spreadsheet/table fields as plain text.
        max_dialogue_chars: Truncate long dialogue payloads to this many
            characters in the prompt to fit the model's context window.
        cache_per_instance: When True (default), one LLM call per instance
            answers all schemas; subsequent ``generate_annotation`` calls
            for the same instance return cached results.
        add_noise: Probability of falling back to a random annotation per
            schema (mirrors ``LLMStrategyConfig`` so existing competence
            modeling still applies).
        noise_rate: Probability used for noise injection (0–1).
    """

    endpoint_type: str = "ollama_vision"
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 800
    max_image_dim: Optional[int] = 1024
    max_image_count: int = 4
    include_dialogue_text: bool = True
    include_spreadsheet: bool = True
    max_dialogue_chars: int = 12000
    cache_per_instance: bool = True
    add_noise: bool = False
    noise_rate: float = 0.0


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
    agent_config: Optional[AgentStrategyConfig] = None
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
    agent_config: Optional[AgentStrategyConfig] = None
    interactive: Optional[InteractiveConfig] = None

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

        # Parse interactive (chat-driving) config
        interactive_config = None
        if "interactive" in data:
            ic = data["interactive"]
            api_key = ic.get("api_key")
            if api_key and api_key.startswith("${") and api_key.endswith("}"):
                api_key = os.environ.get(api_key[2:-1])
            kwargs = {
                "enabled": ic.get("enabled", True),
                "endpoint_type": ic.get("endpoint_type", "ollama"),
                "model": ic.get("model"),
                "api_key": api_key,
                "base_url": ic.get("base_url"),
                "temperature": ic.get("temperature", 0.7),
                "max_tokens": ic.get("max_tokens", 200),
                "max_turns": ic.get("max_turns", 6),
                "done_marker": ic.get("done_marker", "[DONE]"),
            }
            if "persona_system_prompt" in ic:
                kwargs["persona_system_prompt"] = ic["persona_system_prompt"]
            if "first_message_template" in ic:
                kwargs["first_message_template"] = ic["first_message_template"]
            interactive_config = InteractiveConfig(**kwargs)

        # Parse agent (vision-LLM) config
        agent_config = None
        if "agent_config" in data:
            ad = data["agent_config"]
            api_key = ad.get("api_key")
            if api_key and api_key.startswith("${") and api_key.endswith("}"):
                api_key = os.environ.get(api_key[2:-1])
            agent_config = AgentStrategyConfig(
                endpoint_type=ad.get("endpoint_type", "ollama_vision"),
                model=ad.get("model"),
                api_key=api_key,
                base_url=ad.get("base_url"),
                temperature=ad.get("temperature", 0.1),
                max_tokens=ad.get("max_tokens", 800),
                max_image_dim=ad.get("max_image_dim", 1024),
                max_image_count=ad.get("max_image_count", 4),
                include_dialogue_text=ad.get("include_dialogue_text", True),
                include_spreadsheet=ad.get("include_spreadsheet", True),
                max_dialogue_chars=ad.get("max_dialogue_chars", 12000),
                cache_per_instance=ad.get("cache_per_instance", True),
                add_noise=ad.get("add_noise", False),
                noise_rate=ad.get("noise_rate", 0.0),
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
            agent_config=agent_config,
            interactive=interactive_config,
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
