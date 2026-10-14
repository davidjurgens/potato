"""
Solo Mode Configuration

The configuration dataclass and parsing logic for Solo Mode.
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
    think: Optional[bool] = None  # None = use endpoint default, True/False = override
    # None means "let the endpoint apply its own default", which is 30s for
    # openai/anthropic/gemini/huggingface/vllm, 60s for ollama and the
    # openai/anthropic vision endpoints, and 120s for ollama_vision. The
    # sentinel has to be outside the valid range: this was `int = 60` with a
    # `!= 60` guard below, so writing the documented default was the one way
    # to NOT set it -- `timeout: 61` gave you 61 and `timeout: 60` gave you 30.
    timeout: Optional[int] = None  # Request timeout in seconds (raise for thinking models)
    #: Endpoint-specific options passed through to ai_config unchanged:
    #: device/batch_size for laya, state_key for systemone, max_options for
    #: both. Only the keys in ENDPOINT_OPTION_KEYS are read from a config.
    options: Dict[str, Any] = field(default_factory=dict)

    def to_endpoint_config(self, temperature_override: Optional[float] = None) -> Dict[str, Any]:
        """Build the full endpoint config dict for AIEndpointFactory.

        This is the single place that builds the config dict passed to
        AIEndpointFactory.create_endpoint(). All solo mode components
        should use this instead of manually constructing the dict.

        Args:
            temperature_override: Override the model's default temperature.

        Returns:
            Dict ready for AIEndpointFactory.create_endpoint()
        """
        ai_config = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': temperature_override if temperature_override is not None else self.temperature,
        }
        if self.api_key:
            ai_config['api_key'] = self.api_key
        if self.base_url:
            ai_config['base_url'] = self.base_url
        if self.think is not None:
            ai_config['think'] = self.think
        if self.timeout is not None:
            ai_config['timeout'] = self.timeout
        for key, value in self.options.items():
            ai_config.setdefault(key, value)
        return {
            'ai_support': {
                'enabled': True,
                'endpoint_type': self.endpoint_type,
                'ai_config': ai_config,
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for AI endpoint factory (legacy format)."""
        ec = self.to_endpoint_config()
        return {
            'endpoint_type': self.endpoint_type,
            'ai_config': ec['ai_support']['ai_config'],
        }


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


CURRICULUM_DIFFICULTY_SIGNALS = ('confidence', 'cartography', 'combined')
SUGGESTION_DISPLAY_MODES = ('before_label', 'after_label', 'blind_sample')

#: Endpoint types that pick an option but cannot write text (potato/ai/
#: decision_endpoint.py). They can label; they cannot revise a prompt.
DECISION_ENDPOINT_TYPES = ('systemone', 'laya')
#: Scheme types a decision model can answer (one-of-N questions).
DECISION_SCHEME_TYPES = ('radio', 'select', 'likert', 'slider')


@dataclass
class SuggestionsConfig:
    """When the annotator sees the LLM's suggestion, and how agreement is read.

    A suggestion shown before the human answers anchors the answer: labels
    shift toward it and agreement with the LLM is inflated (Schroeder, Roy &
    Kabbara, Findings of ACL 2025). Agreement measured on those labels is what
    hands the corpus to the LLM, so the handoff can come too early.

    ``before_label`` shows it first (the original behaviour). ``after_label``
    never shows it before the human answers; a disagreement then opens the
    resolution page, which shows the LLM's label. ``blind_sample`` hides it on
    a deterministic ``blind_rate`` fraction of items, which measures the
    anchoring gap while keeping the speed-up on the rest.

    Once ``minimum_blind_sample`` blind comparisons exist, the handoff gate
    reads blind agreement only. Under ``after_label`` and ``blind_sample`` it
    waits for them; under ``before_label`` it falls back to all comparisons.
    """
    display: str = 'before_label'
    blind_rate: float = 0.2
    minimum_blind_sample: int = 20


@dataclass
class JuryConfig:
    """Several labeling models vote on each item (jury.py)."""
    enabled: bool = False
    models: List['ModelConfig'] = field(default_factory=list)
    early_stop: bool = True


@dataclass
class GoldConfig:
    """Items with known answers, for scoring prompt versions (evaluation.py)."""
    file: Optional[str] = None
    id_key: str = 'id'
    label_key: str = 'label'
    #: Set when the gold file carries its own text (items outside the corpus).
    text_key: Optional[str] = None


@dataclass
class CacheConfig:
    """Reuse a stored reply for an identical labeling call (label_cache.py)."""
    enabled: bool = True


@dataclass
class CurriculumConfig:
    """Easy-first ordering for the human's first labels (Annotation Curricula, CL 2022).

    For the first ``warmup_items`` human labels the selector shows the items
    the LLM found easiest, so human and model agree on the clear cases before
    either is judged on the hard ones. Over the next ``ramp_items`` labels the
    target difficulty rises from easiest to hardest, after which the weighted
    pools take over. ``window`` is how many neighbours of the target difficulty
    are considered at once, so the predicted label can be rotated rather than
    showing the same obvious class over and over.
    """
    enabled: bool = False
    warmup_items: int = 20
    ramp_items: int = 30
    difficulty_signal: str = 'confidence'
    window: int = 5


@dataclass
class InstanceSelectionConfig:
    """Configuration for instance selection weights."""
    low_confidence_weight: float = 0.4
    diversity_weight: float = 0.3
    random_weight: float = 0.2
    disagreement_weight: float = 0.1
    edge_case_rule_weight: float = 0.0  # Instances matching edge case rule patterns
    cartography_weight: float = 0.0     # Instances with high confidence variability
    llm_predicted_weight: float = 0.0   # Instances with LLM predictions needing human comparison
    curriculum: CurriculumConfig = field(default_factory=CurriculumConfig)

    def validate(self) -> None:
        """Validate that weights sum to 1.0."""
        total = (
            self.low_confidence_weight +
            self.diversity_weight +
            self.random_weight +
            self.disagreement_weight +
            self.edge_case_rule_weight +
            self.cartography_weight +
            self.llm_predicted_weight
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
    refinement_strategy: str = "focused_edit"  # Legacy or new names supported

    # New framework options (used when strategy is validated_*, principle_icl,
    # hybrid_dual_track, or legacy_append from the refinement registry)
    validation_split_ratio: float = 0.3  # fraction of disagreements held out
    eval_sample_size: int = 10  # val instances used to score each candidate
    num_candidates: int = 3  # candidates proposed per cycle (where applicable)
    min_val_size: int = 10  # minimum val size before validation-gated refinement runs
    max_consecutive_failures: int = 2  # stop after N cycles with no improvement
    dry_run: bool = False  # if True, log candidates but don't apply
    require_approval: bool = False  # if True, queue for admin approval before applying
    min_val_improvement: float = 0.0  # candidate must beat baseline by at least this much (strict=0.0)
    # Separate temperature for the evaluator pass. Sampling diversity needs
    # non-zero temperature for confidence, but the validation gate should
    # measure prompt quality, not sampling variance.
    eval_temperature: float = 0.0
    # If True, prefer val instances that have disagreed across ≥2 labeling
    # passes (i.e. stable systematic errors) over one-off disagreements
    # that may be stochastic. Falls back to any disagreement if too few
    # qualify.
    prefer_consistent_disagreements: bool = True


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

    # When the LLM suggestion is shown, and blind-vs-shown agreement
    suggestions: SuggestionsConfig = field(default_factory=SuggestionsConfig)

    # Response cache for labeling calls
    cache: CacheConfig = field(default_factory=CacheConfig)

    # Gold set for scoring prompt versions
    gold: GoldConfig = field(default_factory=GoldConfig)

    # Several models vote on each item
    jury: JuryConfig = field(default_factory=JuryConfig)

    # Output directory for Solo Mode state
    state_dir: Optional[str] = None

    def validate(self, annotation_schemes: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        """
        Validate the configuration.

        Args:
            annotation_schemes: The study's schemes, for the checks that depend
                on what is being labelled. Omitted, those checks are skipped.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Decision models label; prompt synthesis, revision and edge-case
        # synthesis all need a model that writes text. revision_models
        # defaults to labeling_models, so this is also the check for a study
        # that set a decision model as its only model.
        decision_revisers = [m.model for m in self.revision_models
                             if m.endpoint_type in DECISION_ENDPOINT_TYPES]
        if decision_revisers:
            errors.append(
                "solo_mode.revision_models must be models that write text, but "
                f"{', '.join(map(repr, decision_revisers))} is a decision model "
                "(systemone/laya). Set solo_mode.revision_models to a generative "
                "model; it defaults to labeling_models when unset")
        labelers = list(self.labeling_models) + (
            [t.model for t in self.confidence_routing.tiers]
            if self.confidence_routing.enabled else []) + (
            list(self.jury.models) if self.jury.enabled else [])

        if self.jury.enabled:
            from .jury import JURY_SCHEME_TYPES
            if len(self.jury.models) < 2:
                errors.append("solo_mode.jury needs at least two models")
            if self.confidence_routing.enabled:
                errors.append(
                    "solo_mode.jury and solo_mode.confidence_routing both decide "
                    "which model labels an item; enable one of them")
            if annotation_schemes:
                first = annotation_schemes[0] if isinstance(annotation_schemes[0], dict) else {}
                if first.get('annotation_type') not in JURY_SCHEME_TYPES:
                    errors.append(
                        f"solo_mode.jury aggregates {', '.join(JURY_SCHEME_TYPES)} "
                        f"schemes; {first.get('name')!r} is "
                        f"{first.get('annotation_type')!r}")
        if annotation_schemes and any(
                m.endpoint_type in DECISION_ENDPOINT_TYPES for m in labelers):
            first = annotation_schemes[0] if isinstance(annotation_schemes[0], dict) else {}
            atype = first.get('annotation_type')
            if atype not in DECISION_SCHEME_TYPES:
                errors.append(
                    f"A decision model (systemone/laya) can label "
                    f"{', '.join(DECISION_SCHEME_TYPES)} schemes, but the scheme "
                    f"solo mode labels ({first.get('name')!r}) is {atype!r}. Use a "
                    f"generative model for it")

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

        curriculum = self.instance_selection.curriculum
        curriculum_errors = []
        if not isinstance(curriculum.enabled, bool):
            curriculum_errors.append(
                "instance_selection.curriculum.enabled must be true or false")
        for key in ('warmup_items', 'ramp_items', 'window'):
            value = getattr(curriculum, key)
            if isinstance(value, bool) or not isinstance(value, int):
                curriculum_errors.append(
                    f"instance_selection.curriculum.{key} must be an integer, "
                    f"got {value!r}")
        if curriculum.difficulty_signal not in CURRICULUM_DIFFICULTY_SIGNALS:
            curriculum_errors.append(
                f"Invalid instance_selection.curriculum.difficulty_signal: "
                f"{curriculum.difficulty_signal!r} (expected one of "
                f"{', '.join(CURRICULUM_DIFFICULTY_SIGNALS)})")
        if self.gold.file is not None and annotation_schemes:
            from .evaluation import GOLD_SCHEME_TYPES
            first = annotation_schemes[0] if isinstance(annotation_schemes[0], dict) else {}
            if first.get('annotation_type') not in GOLD_SCHEME_TYPES:
                errors.append(
                    f"solo_mode.gold scores {', '.join(GOLD_SCHEME_TYPES)} schemes; "
                    f"{first.get('name')!r} is {first.get('annotation_type')!r}")

        if not isinstance(self.cache.enabled, bool):
            errors.append("solo_mode.cache.enabled must be true or false")

        suggestions = self.suggestions
        if suggestions.display not in SUGGESTION_DISPLAY_MODES:
            errors.append(
                f"Invalid suggestions.display: {suggestions.display!r} "
                f"(expected one of {', '.join(SUGGESTION_DISPLAY_MODES)})")
        if (isinstance(suggestions.blind_rate, bool)
                or not isinstance(suggestions.blind_rate, (int, float))
                or not 0 < suggestions.blind_rate <= 1):
            errors.append("suggestions.blind_rate must be a number in (0, 1]")
        if (isinstance(suggestions.minimum_blind_sample, bool)
                or not isinstance(suggestions.minimum_blind_sample, int)
                or suggestions.minimum_blind_sample < 1):
            errors.append("suggestions.minimum_blind_sample must be an integer of at least 1")

        if not curriculum_errors:  # the range checks need integers
            if curriculum.warmup_items < 0 or curriculum.ramp_items < 0:
                curriculum_errors.append(
                    "instance_selection.curriculum.warmup_items and ramp_items "
                    "must be 0 or more")
            if curriculum.window < 1:
                curriculum_errors.append(
                    "instance_selection.curriculum.window must be at least 1")
        errors.extend(curriculum_errors)

        # Validate uncertainty strategy
        valid_strategies = [
            'direct_confidence', 'direct_uncertainty',
            'token_entropy', 'sampling_diversity'
        ]
        if self.uncertainty.strategy not in valid_strategies:
            errors.append(f"Invalid uncertainty strategy: {self.uncertainty.strategy}")

        return errors


#: Model-config keys that are specific to one endpoint type and are passed to
#: it as they are (see ModelConfig.options).
ENDPOINT_OPTION_KEYS = ('device', 'batch_size', 'head_max_len', 'max_options',
                        'state_key')


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
        base_url=model_data.get('base_url') or model_data.get('endpoint_url'),
        max_tokens=model_data.get('max_tokens', 1000),
        temperature=model_data.get('temperature', 0.1),
        think=model_data.get('think'),  # None = endpoint default, True/False = override
        timeout=model_data.get('timeout'),  # absent = endpoint default, see ModelConfig
        options={k: model_data[k] for k in ENDPOINT_OPTION_KEYS if k in model_data},
    )


def _parse_suggestions_config(data: Dict[str, Any]) -> SuggestionsConfig:
    defaults = SuggestionsConfig()
    return SuggestionsConfig(
        display=data.get('display', defaults.display),
        blind_rate=data.get('blind_rate', defaults.blind_rate),
        minimum_blind_sample=data.get(
            'minimum_blind_sample', defaults.minimum_blind_sample),
    )


def _parse_curriculum_config(data: Dict[str, Any]) -> CurriculumConfig:
    defaults = CurriculumConfig()
    # Values pass through unconverted; validate() names a wrong type instead
    # of int("twenty") raising out of the parser.
    return CurriculumConfig(
        enabled=data.get('enabled', defaults.enabled),
        warmup_items=data.get('warmup_items', defaults.warmup_items),
        ramp_items=data.get('ramp_items', defaults.ramp_items),
        difficulty_signal=data.get('difficulty_signal', defaults.difficulty_signal),
        window=data.get('window', defaults.window),
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
        llm_predicted_weight=sel_data.get('llm_predicted_weight', 0.0),
        curriculum=_parse_curriculum_config(sel_data.get('curriculum') or {}),
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
        refinement_strategy=rl_data.get('refinement_strategy', 'focused_edit'),
        validation_split_ratio=rl_data.get('validation_split_ratio', 0.3),
        eval_sample_size=rl_data.get('eval_sample_size', 10),
        num_candidates=rl_data.get('num_candidates', 3),
        min_val_size=rl_data.get('min_val_size', 10),
        max_consecutive_failures=rl_data.get('max_consecutive_failures', 2),
        dry_run=rl_data.get('dry_run', False),
        require_approval=rl_data.get('require_approval', False),
        min_val_improvement=rl_data.get('min_val_improvement', 0.0),
        eval_temperature=rl_data.get('eval_temperature', 0.0),
        prefer_consistent_disagreements=rl_data.get('prefer_consistent_disagreements', True),
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
        suggestions=_parse_suggestions_config(sm.get('suggestions') or {}),
        cache=CacheConfig(enabled=(sm.get('cache') or {}).get('enabled', True)),
        gold=GoldConfig(**{k: v for k, v in (sm.get('gold') or {}).items()
                           if k in ('file', 'id_key', 'label_key', 'text_key')}),
        jury=JuryConfig(
            enabled=(sm.get('jury') or {}).get('enabled', False),
            models=[_parse_model_config(m) for m in (sm.get('jury') or {}).get('models', [])],
            early_stop=(sm.get('jury') or {}).get('early_stop', True),
        ),
        state_dir=state_dir,
    )
