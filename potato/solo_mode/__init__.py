"""
Solo Mode Module

This module provides human-LLM collaborative annotation for single annotators.
Solo Mode enables efficient dataset labeling through:

1. Prompt synthesis from task descriptions
2. Edge case generation and labeling
3. Parallel human-LLM annotation with disagreement resolution
4. Uncertainty-based instance ordering
5. Progressive validation and autonomous completion

Key Components:
- SoloModeManager: Central orchestrator for Solo Mode workflow
- SoloPhase: Enum defining workflow phases
- PromptManager: Prompt synthesis, versioning, and revision
- UncertaintyEstimator: Pluggable uncertainty estimation strategies
- InstanceSelector: Weighted instance selection for human review
- DisagreementResolver: Human-LLM conflict resolution
- ValidationTracker: Agreement metrics and thresholds
"""

from .config import SoloModeConfig, parse_solo_mode_config
from .phase_controller import SoloPhase, SoloPhaseController
from .manager import (
    SoloModeManager,
    init_solo_mode_manager,
    get_solo_mode_manager,
    clear_solo_mode_manager,
)
from .prompt_manager import PromptManager, PromptRevision
from .instance_selector import InstanceSelector, SelectionWeights
from .llm_labeler import LLMLabelingThread, LabelingResult
from .disagreement_resolver import DisagreementDetector, DisagreementResolver
from .validation_tracker import ValidationTracker, AgreementMetrics, ValidationSample
from .edge_case_synthesizer import EdgeCaseSynthesizer, EdgeCase
from .prompt_optimizer import PromptOptimizer, OptimizationResult

__all__ = [
    # Config
    'SoloModeConfig',
    'parse_solo_mode_config',
    # Phase control
    'SoloPhase',
    'SoloPhaseController',
    # Manager
    'SoloModeManager',
    'init_solo_mode_manager',
    'get_solo_mode_manager',
    'clear_solo_mode_manager',
    # Prompt management
    'PromptManager',
    'PromptRevision',
    # Instance selection
    'InstanceSelector',
    'SelectionWeights',
    # LLM labeling
    'LLMLabelingThread',
    'LabelingResult',
    # Disagreement resolution
    'DisagreementDetector',
    'DisagreementResolver',
    # Validation tracking
    'ValidationTracker',
    'AgreementMetrics',
    'ValidationSample',
    # Edge case synthesis
    'EdgeCaseSynthesizer',
    'EdgeCase',
    # Prompt optimization
    'PromptOptimizer',
    'OptimizationResult',
]
