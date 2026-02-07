"""
Solo Mode Configuration

This module defines the configuration dataclass and parsing logic for Solo Mode.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging
import os

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    """Configuration for an LLM endpoint."""
    endpoint_type: str  # 'anthropic', 'openai', 'ollama', etc.
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 1000
    temperature: float = 0.1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for AI endpoint factory."""
        result = {
            'endpoint_type': self.endpoint_type,
            'ai_config': {
                'model': self.model,
                'max_tokens': self.max_tokens,
                'temperature': self.temperature,
            }
        }
        if self.api_key:
            result['ai_config']['api_key'] = self.api_key
        if self.base_url:
            result['ai_config']['base_url'] = self.base_url
        return result


@dataclass
class UncertaintyConfig:
    """Configuration for uncertainty estimation."""
    strategy: str = "direct_confidence"  # direct_confidence, direct_uncertainty, token_entropy, sampling_diversity
    # Sampling diversity options
    num_samples: int = 5
    sampling_temperature: float = 1.0


@dataclass
class ThresholdConfig:
    """Threshold configuration for Solo Mode."""
    end_human_annotation_agreement: float = 0.90
    minimum_validation_sample: int = 50
    confidence_low: float = 0.5
    confidence_high: float = 0.8
    periodic_review_interval: int = 100
    # Disagreement thresholds by annotation type
    likert_tolerance: int = 1  # |human - llm| <= tolerance = agreement
    multiselect_jaccard_threshold: float = 0.5
    textbox_embedding_threshold: float = 0.7
    span_overlap_threshold: float = 0.5


@dataclass
class InstanceSelectionConfig:
    """Configuration for instance selection weights."""
    low_confidence_weight: float = 0.4
    diversity_weight: float = 0.3
    random_weight: float = 0.2
    disagreement_weight: float = 0.1

    def validate(self) -> None:
        """Validate that weights sum to 1.0."""
        total = (
            self.low_confidence_weight +
            self.diversity_weight +
            self.random_weight +
            self.disagreement_weight
        )
        if abs(total - 1.0) > 0.001:
            logger.warning(
                f"Instance selection weights sum to {total}, normalizing to 1.0"
            )


@dataclass
class BatchConfig:
    """Configuration for batch sizes."""
    llm_labeling_batch: int = 50
    max_parallel_labels: int = 200


@dataclass
class PromptOptimizationConfig:
    """Configuration for automatic prompt optimization."""
    enabled: bool = True
    find_smallest_model: bool = True
    target_accuracy: float = 0.85
    optimization_interval_seconds: int = 300  # 5 minutes
    # Optimization objectives weights
    accuracy_weight: float = 0.7
    length_weight: float = 0.2
    consistency_weight: float = 0.1


@dataclass
class EmbeddingConfig:
    """Configuration for embedding model (used for diversity)."""
    model_name: str = "all-MiniLM-L6-v2"


@dataclass
class SoloModeConfig:
    """
    Main configuration dataclass for Solo Mode.

    This contains all settings needed to run Solo Mode including
    model configurations, thresholds, and feature flags.
    """
    enabled: bool = False

    # Models for labeling (tried in order until one succeeds)
    labeling_models: List[ModelConfig] = field(default_factory=list)

    # Models for prompt revision
    revision_models: List[ModelConfig] = field(default_factory=list)

    # Embedding configuration
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)

    # Uncertainty estimation
    uncertainty: UncertaintyConfig = field(default_factory=UncertaintyConfig)

    # Thresholds
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)

    # Instance selection
    instance_selection: InstanceSelectionConfig = field(default_factory=InstanceSelectionConfig)

    # Batch sizes
    batches: BatchConfig = field(default_factory=BatchConfig)

    # Prompt optimization
    prompt_optimization: PromptOptimizationConfig = field(default_factory=PromptOptimizationConfig)

    # Output directory for Solo Mode state
    state_dir: Optional[str] = None

    def validate(self) -> List[str]:
        """
        Validate the configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if self.enabled:
            if not self.labeling_models:
                errors.append("solo_mode.labeling_models is required when solo_mode is enabled")

            if not self.revision_models:
                # Default to using labeling models for revision
                logger.info("No revision_models specified, using labeling_models")

        # Validate instance selection weights
        self.instance_selection.validate()

        # Validate thresholds
        if not 0 <= self.thresholds.end_human_annotation_agreement <= 1:
            errors.append("end_human_annotation_agreement must be between 0 and 1")

        if not 0 <= self.thresholds.confidence_low <= 1:
            errors.append("confidence_low must be between 0 and 1")

        if not 0 <= self.thresholds.confidence_high <= 1:
            errors.append("confidence_high must be between 0 and 1")

        if self.thresholds.confidence_low >= self.thresholds.confidence_high:
            errors.append("confidence_low must be less than confidence_high")

        # Validate uncertainty strategy
        valid_strategies = [
            'direct_confidence', 'direct_uncertainty',
            'token_entropy', 'sampling_diversity'
        ]
        if self.uncertainty.strategy not in valid_strategies:
            errors.append(f"Invalid uncertainty strategy: {self.uncertainty.strategy}")

        return errors


def _parse_model_config(model_data: Dict[str, Any]) -> ModelConfig:
    """Parse a single model configuration."""
    # Handle environment variable expansion for API keys
    api_key = model_data.get('api_key')
    if api_key and api_key.startswith('${') and api_key.endswith('}'):
        env_var = api_key[2:-1]
        api_key = os.environ.get(env_var)
        if not api_key:
            logger.warning(f"Environment variable {env_var} not set")

    return ModelConfig(
        endpoint_type=model_data.get('endpoint_type', 'openai'),
        model=model_data.get('model', ''),
        api_key=api_key,
        base_url=model_data.get('base_url'),
        max_tokens=model_data.get('max_tokens', 1000),
        temperature=model_data.get('temperature', 0.1),
    )


def parse_solo_mode_config(config_data: Dict[str, Any]) -> SoloModeConfig:
    """
    Parse solo_mode section from application config into SoloModeConfig.

    Args:
        config_data: Full application configuration dictionary

    Returns:
        SoloModeConfig instance
    """
    sm = config_data.get('solo_mode', {})

    if not sm:
        return SoloModeConfig(enabled=False)

    # Parse labeling models
    labeling_models = []
    for model_data in sm.get('labeling_models', []):
        labeling_models.append(_parse_model_config(model_data))

    # Parse revision models (default to labeling models if not specified)
    revision_models = []
    for model_data in sm.get('revision_models', sm.get('labeling_models', [])):
        revision_models.append(_parse_model_config(model_data))

    # Parse embedding config
    emb_data = sm.get('embedding', {})
    embedding = EmbeddingConfig(
        model_name=emb_data.get('model_name', 'all-MiniLM-L6-v2')
    )

    # Parse uncertainty config
    unc_data = sm.get('uncertainty', {})
    sampling_data = unc_data.get('sampling_diversity', {})
    uncertainty = UncertaintyConfig(
        strategy=unc_data.get('strategy', 'direct_confidence'),
        num_samples=sampling_data.get('num_samples', 5),
        sampling_temperature=sampling_data.get('temperature', 1.0),
    )

    # Parse threshold config
    thresh_data = sm.get('thresholds', {})
    thresholds = ThresholdConfig(
        end_human_annotation_agreement=thresh_data.get('end_human_annotation_agreement', 0.90),
        minimum_validation_sample=thresh_data.get('minimum_validation_sample', 50),
        confidence_low=thresh_data.get('confidence_low', 0.5),
        confidence_high=thresh_data.get('confidence_high', 0.8),
        periodic_review_interval=thresh_data.get('periodic_review_interval', 100),
        likert_tolerance=thresh_data.get('likert_tolerance', 1),
        multiselect_jaccard_threshold=thresh_data.get('multiselect_jaccard_threshold', 0.5),
        textbox_embedding_threshold=thresh_data.get('textbox_embedding_threshold', 0.7),
        span_overlap_threshold=thresh_data.get('span_overlap_threshold', 0.5),
    )

    # Parse instance selection config
    sel_data = sm.get('instance_selection', {})
    instance_selection = InstanceSelectionConfig(
        low_confidence_weight=sel_data.get('low_confidence_weight', 0.4),
        diversity_weight=sel_data.get('diversity_weight', 0.3),
        random_weight=sel_data.get('random_weight', 0.2),
        disagreement_weight=sel_data.get('disagreement_weight', 0.1),
    )

    # Parse batch config
    batch_data = sm.get('batches', {})
    batches = BatchConfig(
        llm_labeling_batch=batch_data.get('llm_labeling_batch', 50),
        max_parallel_labels=batch_data.get('max_parallel_labels', 200),
    )

    # Parse prompt optimization config
    opt_data = sm.get('prompt_optimization', {})
    prompt_optimization = PromptOptimizationConfig(
        enabled=opt_data.get('enabled', True),
        find_smallest_model=opt_data.get('find_smallest_model', True),
        target_accuracy=opt_data.get('target_accuracy', 0.85),
        optimization_interval_seconds=opt_data.get('optimization_interval_seconds', 300),
        accuracy_weight=opt_data.get('accuracy_weight', 0.7),
        length_weight=opt_data.get('length_weight', 0.2),
        consistency_weight=opt_data.get('consistency_weight', 0.1),
    )

    # Determine state directory
    state_dir = sm.get('state_dir')
    if not state_dir:
        output_dir = config_data.get('output_annotation_dir', 'annotation_output')
        state_dir = os.path.join(output_dir, '.solo_mode')

    return SoloModeConfig(
        enabled=sm.get('enabled', False),
        labeling_models=labeling_models,
        revision_models=revision_models,
        embedding=embedding,
        uncertainty=uncertainty,
        thresholds=thresholds,
        instance_selection=instance_selection,
        batches=batches,
        prompt_optimization=prompt_optimization,
        state_dir=state_dir,
    )
