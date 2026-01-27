"""
User Simulator for Potato Annotation Platform.

This module provides tools for simulating multiple annotators with varying
competence levels and behaviors for testing purposes.

Example usage:
    from potato.simulator import SimulatorManager, SimulatorConfig

    config = SimulatorConfig(
        user_count=10,
        strategy="random",
        competence_distribution={"good": 0.5, "average": 0.3, "poor": 0.2}
    )

    manager = SimulatorManager(config, "http://localhost:8000")
    results = manager.run_parallel(max_annotations_per_user=20)

    print(manager.get_summary())
"""

from .config import (
    SimulatorConfig,
    UserConfig,
    TimingConfig,
    LLMStrategyConfig,
    BiasedStrategyConfig,
    PatternStrategyConfig,
    CompetenceLevel,
    AnnotationStrategyType,
)
from .competence_profiles import (
    CompetenceProfile,
    create_competence_profile,
)
from .annotation_strategies import (
    AnnotationStrategy,
    RandomStrategy,
    BiasedStrategy,
    LLMStrategy,
    PatternStrategy,
    create_strategy,
)
from .timing_models import TimingModel
from .user_simulator import SimulatedUser, UserSimulationResult, AnnotationRecord
from .simulator_manager import SimulatorManager
from .reporting import SimulationReporter

__all__ = [
    # Config
    "SimulatorConfig",
    "UserConfig",
    "TimingConfig",
    "LLMStrategyConfig",
    "BiasedStrategyConfig",
    "PatternStrategyConfig",
    "CompetenceLevel",
    "AnnotationStrategyType",
    # Competence
    "CompetenceProfile",
    "create_competence_profile",
    # Strategies
    "AnnotationStrategy",
    "RandomStrategy",
    "BiasedStrategy",
    "LLMStrategy",
    "PatternStrategy",
    "create_strategy",
    # Timing
    "TimingModel",
    # User simulation
    "SimulatedUser",
    "UserSimulationResult",
    "AnnotationRecord",
    # Manager
    "SimulatorManager",
    # Reporting
    "SimulationReporter",
]
