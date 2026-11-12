"""
Judge Calibration configuration.

Parses the ``judge_calibration:`` block of an application config into a typed
``JudgeCalibrationConfig``. This is a deliberately lightweight cousin of
``solo_mode`` — there are no refinement loops, edge-case synthesis or
disagreement-resolution settings. The workflow is: pick N judge LLMs, sample
each ``k`` times over (up to) a capped number of items, then have human(s)
*blind*-label a sample and produce a calibration report.

LLM endpoint settings reuse ``solo_mode.config.ModelConfig`` (and its
``to_endpoint_config()``), which already covers every provider Potato supports
(openai/anthropic/ollama/vllm/gemini/...) plus env-var API-key expansion.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging
import os

# Reuse the solo-mode model dataclass + parser so endpoint handling stays in
# one place (env-var expansion, to_endpoint_config(), base_url aliasing, ...).
from potato.solo_mode.config import ModelConfig, _parse_model_config

logger = logging.getLogger(__name__)


_VALID_SAMPLING_STRATEGIES = ("random", "stratified", "all")
_VALID_GOLD = ("single", "majority")


@dataclass
class SamplingConfig:
    """How the human calibration subset is drawn from the LLM-labeled items."""
    strategy: str = "random"          # random | stratified | all
    stratify_by: Optional[str] = None  # item-data field to stratify on
    sample_size: int = 200            # number of items humans blind-label
    seed: int = 42


@dataclass
class HumanConfig:
    """Who provides the human ground-truth labels."""
    num_raters: int = 1               # 1 = solo researcher; N adds human-human IAA
    gold: str = "single"              # single | majority (used when num_raters > 1)


@dataclass
class CalibrationConfig:
    """Calibration (ECE / reliability diagram) settings."""
    n_bins: int = 10


@dataclass
class OutputConfig:
    """Where outputs are written and under what filenames."""
    dir: str = "judge_calibration_output"
    labels_file: str = "llm_labels.jsonl"
    report_json: str = "report.json"
    report_html: str = "report.html"


@dataclass
class JudgeCalibrationConfig:
    """Top-level configuration for Judge Calibration mode."""
    enabled: bool = False

    # The judge instruction shown to every model. Supports ``{text}``,
    # ``{labels}`` and ``{description}`` substitution (filled per-item /
    # per-schema at generation time).
    prompt: str = ""

    # Judge LLMs. Each is sampled ``k_samples`` times per item.
    models: List[ModelConfig] = field(default_factory=list)

    k_samples: int = 5

    # Cap on how many items the LLMs label. Exactly one of max_items / fraction
    # is honored (max_items wins if both set); None/None means "all items".
    max_items: Optional[int] = None
    fraction: Optional[float] = None

    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    human: HumanConfig = field(default_factory=HumanConfig)

    # Annotation scheme names to evaluate. Empty = all categorical schemes.
    schemas: List[str] = field(default_factory=list)

    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    state_dir: str = "judge_calibration_state"

    def validate(self) -> List[str]:
        """Return a list of human-readable error strings (empty if valid)."""
        errors: List[str] = []
        if not self.enabled:
            return errors

        if not self.models:
            errors.append("judge_calibration.models is required (at least one model)")
        for i, m in enumerate(self.models):
            if not m.model:
                errors.append(f"judge_calibration.models[{i}].model is required")
            if not m.endpoint_type:
                errors.append(f"judge_calibration.models[{i}].endpoint_type is required")

        if self.k_samples < 1:
            errors.append("judge_calibration.k_samples must be >= 1")

        if self.fraction is not None and not (0 < self.fraction <= 1):
            errors.append("judge_calibration.fraction must be in (0, 1]")
        if self.max_items is not None and self.max_items < 1:
            errors.append("judge_calibration.max_items must be >= 1")

        if self.sampling.strategy not in _VALID_SAMPLING_STRATEGIES:
            errors.append(
                f"judge_calibration.sampling.strategy must be one of "
                f"{_VALID_SAMPLING_STRATEGIES}, got '{self.sampling.strategy}'"
            )
        if self.sampling.sample_size < 1:
            errors.append("judge_calibration.sampling.sample_size must be >= 1")

        if self.human.num_raters < 1:
            errors.append("judge_calibration.human.num_raters must be >= 1")
        if self.human.gold not in _VALID_GOLD:
            errors.append(
                f"judge_calibration.human.gold must be one of {_VALID_GOLD}, "
                f"got '{self.human.gold}'"
            )

        if self.calibration.n_bins < 1:
            errors.append("judge_calibration.calibration.n_bins must be >= 1")

        # Confidence degeneracy guard: with k>1 samples but temperature 0 the
        # samples never vary, so the vote-fraction confidence is always 1.0 and
        # the calibration report is meaningless. Warn (don't fail).
        if self.k_samples > 1:
            for i, m in enumerate(self.models):
                if m.temperature == 0:
                    logger.warning(
                        "judge_calibration.models[%d] (%s) has temperature=0 with "
                        "k_samples=%d; samples will be identical and confidence "
                        "will always be 1.0. Set temperature > 0 for meaningful "
                        "calibration.",
                        i, m.model, self.k_samples,
                    )

        return errors


def _parse_sampling(data: Dict[str, Any]) -> SamplingConfig:
    data = data or {}
    return SamplingConfig(
        strategy=data.get("strategy", "random"),
        stratify_by=data.get("stratify_by"),
        sample_size=int(data.get("sample_size", 200)),
        seed=int(data.get("seed", 42)),
    )


def _parse_human(data: Dict[str, Any]) -> HumanConfig:
    data = data or {}
    return HumanConfig(
        num_raters=int(data.get("num_raters", 1)),
        gold=data.get("gold", "single"),
    )


def _parse_output(data: Dict[str, Any]) -> OutputConfig:
    data = data or {}
    files = data.get("files", {}) or {}
    return OutputConfig(
        dir=data.get("dir", "judge_calibration_output"),
        labels_file=files.get("labels", "llm_labels.jsonl"),
        report_json=files.get("report_json", "report.json"),
        report_html=files.get("report_html", "report.html"),
    )


def parse_judge_calibration_config(config_data: Dict[str, Any]) -> JudgeCalibrationConfig:
    """Parse the ``judge_calibration`` section into a JudgeCalibrationConfig."""
    jc = config_data.get("judge_calibration", {})
    if not jc:
        return JudgeCalibrationConfig(enabled=False)

    models = [_parse_model_config(m) for m in jc.get("models", [])]

    state_dir = jc.get("state_dir")
    if not state_dir:
        output_dir = config_data.get("output_annotation_dir", "annotation_output")
        state_dir = os.path.join(output_dir, ".judge_calibration")

    cal_data = jc.get("calibration", {}) or {}

    return JudgeCalibrationConfig(
        enabled=jc.get("enabled", False),
        prompt=jc.get("prompt", ""),
        models=models,
        k_samples=int(jc.get("k_samples", 5)),
        max_items=jc.get("max_items"),
        fraction=jc.get("fraction"),
        sampling=_parse_sampling(jc.get("sampling", {})),
        human=_parse_human(jc.get("human", {})),
        schemas=list(jc.get("schemas", []) or []),
        calibration=CalibrationConfig(n_bins=int(cal_data.get("n_bins", 10))),
        output=_parse_output(jc.get("output", {})),
        state_dir=state_dir,
    )
