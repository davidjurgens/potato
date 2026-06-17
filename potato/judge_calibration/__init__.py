"""
Judge Calibration mode.

A lightweight LLM-as-judge auto-labeling + blind human calibration workflow.
Researchers configure a judge prompt and a set of LLMs, each sampled k times to
label (up to a cap of) the data; human(s) then blind-label a sample and Potato
produces a calibration report (accuracy vs human gold, IAA human<->LLM and
LLM<->LLM, ECE/reliability, per-LLM confusion matrices) plus a file of every
LLM's labels.

This is a deliberately simpler cousin of ``solo_mode`` (no refinement loops,
edge-case synthesis or disagreement-resolution UI) and is distinct from the
single-judge ``judge_alignment`` feature (which shows suggestions inline and
draws few-shot from gold labels).
"""

from .config import JudgeCalibrationConfig, parse_judge_calibration_config
from .phase import JCPhase, JCPhaseController
from .aggregation import ModelItemResult, aggregate
from .storage import ResultStore
from .generation import LLMGenerationThread, build_prompt, parse_sample
from .manager import (
    JudgeCalibrationManager,
    init_judge_calibration_manager,
    get_judge_calibration_manager,
    clear_judge_calibration_manager,
)

__all__ = [
    "JudgeCalibrationConfig",
    "parse_judge_calibration_config",
    "JCPhase",
    "JCPhaseController",
    "ModelItemResult",
    "aggregate",
    "ResultStore",
    "LLMGenerationThread",
    "build_prompt",
    "parse_sample",
    "JudgeCalibrationManager",
    "init_judge_calibration_manager",
    "get_judge_calibration_manager",
    "clear_judge_calibration_manager",
]
