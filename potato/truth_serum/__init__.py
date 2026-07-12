"""
Truth Serum: surprisingly-popular scoring for annotation.

Majority vote fails precisely on hard items, where a confident crowd is wrong
and an informed minority is right. Truth Serum adds one micro-question after
each label — "What percentage of other annotators will choose the same label
as you?" — and applies the surprisingly-popular principle (Prelec 2004;
Prelec, Seung & McCoy, Nature 2017): the label whose actual popularity most
exceeds its predicted popularity is the best available estimate of the truth,
with no gold labels required.

This implementation uses the simplified own-answer-prediction variant:
annotators predict the popularity of the label they themselves chose. Item
verdicts are computed once ``min_annotators`` predictions exist.

Byproducts:
- Item-level verdicts where the surprisingly-popular label differs from the
  majority label (review-queue gold)
- Per-annotator calibration error (how well they predict their peers)
- Per-annotator SP-alignment (how often their label matches the SP verdict)
"""

from potato.truth_serum.config import TruthSerumConfig, parse_truth_serum_config
from potato.truth_serum.manager import (
    TruthSerumManager,
    clear_truth_serum_manager,
    get_truth_serum_manager,
    init_truth_serum_manager,
)
from potato.truth_serum.routes import truth_serum_bp

__all__ = [
    "TruthSerumConfig",
    "parse_truth_serum_config",
    "TruthSerumManager",
    "init_truth_serum_manager",
    "get_truth_serum_manager",
    "clear_truth_serum_manager",
    "truth_serum_bp",
]
