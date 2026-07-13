"""
Psychometrics: measurement-grade annotation. Labels with error bars.

Every annotation study is a measurement instrument; this package treats it
like one. A multiclass GLAD model (item response theory for annotation,
Whitehill et al. 2009) is fit live over the raw labels — no gold labels, no
LLM — jointly inferring:

- each item's true label as a posterior distribution (labels with error bars),
- each annotator's ability (with standard errors),
- each item's difficulty, and a discrimination diagnostic that flags items
  where the *best* annotators disagree with the crowd — almost always a
  codebook bug rather than an annotator problem.

On top of the model:

- **Adaptive routing** (``assignment_strategy: psychometric``): items are
  served to whichever annotator's judgment carries the most information,
  and items past a confidence threshold stop consuming budget.
- **A live dashboard** (``/psychometrics/dashboard``): ability chart,
  difficulty map, codebook-bug flags, and saved-judgment stats.
- **A study designer** (``python -m potato.psychometrics.design``):
  Monte Carlo power analysis answering "how many annotators per item?"
  before any money is spent.
- **An enriched export** (``/psychometrics/api/export``): every label with
  its posterior probability, sensitivity band, and provenance.
"""

# NOTE: potato.psychometrics.design is deliberately NOT imported here so
# that `python -m potato.psychometrics.design` runs without a double-import
# warning; import it directly where needed.
from potato.psychometrics.config import (
    PsychometricsConfig,
    parse_psychometrics_config,
)
from potato.psychometrics.irt import AbilityEstimate, IRTModel, ItemEstimate
from potato.psychometrics.manager import (
    PsychometricsManager,
    clear_psychometrics_manager,
    get_psychometrics_manager,
    init_psychometrics_manager,
)
from potato.psychometrics.routes import psychometrics_bp

__all__ = [
    "PsychometricsConfig",
    "parse_psychometrics_config",
    "IRTModel",
    "AbilityEstimate",
    "ItemEstimate",
    "PsychometricsManager",
    "init_psychometrics_manager",
    "get_psychometrics_manager",
    "clear_psychometrics_manager",
    "psychometrics_bp",
]
