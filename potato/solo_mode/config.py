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
    edge_case_rule_weight: float = 0.0  # Instances matching edge case rule patterns
    cartography_weight: float = 0.0     # Instances with high confidence variability

    def validate(self) -> None:
        """Validate that weights sum to 1.0."""
        total = (
            self.low_confidence_weight +
            self.diversity_weight +
            self.random_weight +
            self.disagreement_weight +
            self.edge_case_rule_weight +
            self.cartography_weight
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
class EdgeCaseRuleConfig:
    """Configuration for Co-DETECT-style edge case rule discovery."""
    enabled: bool = True
    confidence_threshold: float = 0.75  # Extract rules when confidence below this
    min_rules_for_clustering: int = 10  # Minimum rules before clustering triggers
    target_cluster_size: int = 15       # Target items per cluster (Co-DETECT: 10-20)
    auto_extract_on_labeling: bool = True  # Extract rules during LLM labeling
    reannotation_enabled: bool = True
    reannotation_confidence_threshold: float = 0.60  # Re-annotate instances below this
    max_reannotations_per_instance: int = 2  # Prevent infinite loops


@dataclass
class ConfidenceTierConfig:
    """A single tier in the confidence routing cascade."""
    model: 'ModelConfig' = None
    confidence_threshold: float = 0.8  # 0.0-1.0, minimum confidence to accept
    name: str = ""  # e.g. "fast", "strong"

    def __post_init__(self):
        if self.model is None:
            self.model = ModelConfig(endpoint_type='openai', model='')


@dataclass
class ConfusionAnalysisConfig:
    """Configuration for confusion pattern analysis dashboard."""
    enabled: bool = True
    min_instances_for_pattern: int = 3
    max_patterns: int = 20
    auto_suggest_guidelines: bool = False


@dataclass
class RefinementLoopConfig:
    """Configuration for the iterative guideline refinement loop."""
    enabled: bool = True
    trigger_interval: int = 50          # Check every N human annotations
    min_improvement: float = 0.02       # Minimum agreement rate improvement to continue
    max_cycles: int = 5                 # Maximum refinement cycles before alerting
    patience: int = 2                   # Cycles without improvement before stopping
    auto_apply_suggestions: bool = False  # Auto-apply LLM guideline suggestions


@dataclass
class LabelingFunctionConfig:
    """Configuration for labeling function extraction (ALCHEmist-style)."""
    enabled: bool = True
    min_confidence: float = 0.85       # Minimum LLM confidence to consider for extraction
    min_coverage: int = 3              # Minimum instances a pattern must match
    max_functions: int = 50            # Maximum labeling functions to maintain
    auto_extract: bool = True          # Auto-extract during labeling
    vote_threshold: float = 0.5        # Fraction of matching functions needed for label


@dataclass
class ConfidenceRoutingConfig:
    """Cascaded confidence escalation config."""
    enabled: bool = False
    tiers: List['ConfidenceTierConfig'] = field(default_factory=list)


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

    # Edge case rule discovery (Co-DETECT-style)
    edge_case_rules: EdgeCaseRuleConfig = field(default_factory=EdgeCaseRuleConfig)

    # Labeling function extraction (ALCHEmist-style)
    labeling_functions: LabelingFunctionConfig = field(default_factory=LabelingFunctionConfig)

    # Cascaded confidence routing
    confidence_routing: ConfidenceRoutingConfig = field(default_factory=ConfidenceRoutingConfig)

    # Confusion analysis dashboard
    confusion_analysis: ConfusionAnalysisConfig = field(default_factory=ConfusionAnalysisConfig)

    # Iterative guideline refinement loop
    refinement_loop: RefinementLoopConfig = field(default_factory=RefinementLoopConfig)

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
            logger.warning("Required environment variable for API key is not set")

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
        edge_case_rule_weight=sel_data.get('edge_case_rule_weight', 0.0),
        cartography_weight=sel_data.get('cartography_weight', 0.0),
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

    # Parse edge case rule config
    ecr_data = sm.get('edge_case_rules', {})
    edge_case_rules = EdgeCaseRuleConfig(
        enabled=ecr_data.get('enabled', True),
        confidence_threshold=ecr_data.get('confidence_threshold', 0.75),
        min_rules_for_clustering=ecr_data.get('min_rules_for_clustering', 10),
        target_cluster_size=ecr_data.get('target_cluster_size', 15),
        auto_extract_on_labeling=ecr_data.get('auto_extract_on_labeling', True),
        reannotation_enabled=ecr_data.get('reannotation_enabled', True),
        reannotation_confidence_threshold=ecr_data.get('reannotation_confidence_threshold', 0.60),
        max_reannotations_per_instance=ecr_data.get('max_reannotations_per_instance', 2),
    )

    # Parse labeling function config
    lf_data = sm.get('labeling_functions', {})
    labeling_functions = LabelingFunctionConfig(
        enabled=lf_data.get('enabled', True),
        min_confidence=lf_data.get('min_confidence', 0.85),
        min_coverage=lf_data.get('min_coverage', 3),
        max_functions=lf_data.get('max_functions', 50),
        auto_extract=lf_data.get('auto_extract', True),
        vote_threshold=lf_data.get('vote_threshold', 0.5),
    )

    # Parse confidence routing config
    cr_data = sm.get('confidence_routing', {})
    cr_tiers = []
    for tier_data in cr_data.get('tiers', []):
        cr_tiers.append(ConfidenceTierConfig(
            model=_parse_model_config(tier_data.get('model', {})),
            confidence_threshold=tier_data.get('confidence_threshold', 0.8),
            name=tier_data.get('name', ''),
        ))
    confidence_routing = ConfidenceRoutingConfig(
        enabled=cr_data.get('enabled', False),
        tiers=cr_tiers,
    )

    # Parse refinement loop config
    rl_data = sm.get('refinement_loop', {})
    refinement_loop = RefinementLoopConfig(
        enabled=rl_data.get('enabled', True),
        trigger_interval=rl_data.get('trigger_interval', 50),
        min_improvement=rl_data.get('min_improvement', 0.02),
        max_cycles=rl_data.get('max_cycles', 5),
        patience=rl_data.get('patience', 2),
        auto_apply_suggestions=rl_data.get('auto_apply_suggestions', False),
    )

    # Parse confusion analysis config
    ca_data = sm.get('confusion_analysis', {})
    confusion_analysis = ConfusionAnalysisConfig(
        enabled=ca_data.get('enabled', True),
        min_instances_for_pattern=ca_data.get('min_instances_for_pattern', 3),
        max_patterns=ca_data.get('max_patterns', 20),
        auto_suggest_guidelines=ca_data.get('auto_suggest_guidelines', False),
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
        edge_case_rules=edge_case_rules,
        labeling_functions=labeling_functions,
        confidence_routing=confidence_routing,
        confusion_analysis=confusion_analysis,
        refinement_loop=refinement_loop,
        state_dir=state_dir,
    )
