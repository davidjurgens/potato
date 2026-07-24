"""
Think-Aloud Mode: voice rationales with rule-based label detection. No LLM.

Annotators speak freely while annotating; the verbatim transcript is stored as
the rationale artifact (deliberately un-summarized — think-aloud protocols are
the research artifact, and paraphrasing them would contaminate the data). To
commit a label by voice, the annotator uses a set phrasing ("I label this
Polite", "my answer is X"); a rule-based parser with fuzzy label matching
detects it and selects the corresponding option in the UI. Moving on without a
committed label triggers a re-prompt nudge showing the expected phrasing.

Speech-to-text runs fully locally through a pluggable backend (faster-whisper
by default; a mock backend for tests). Hesitation signals — silent chunks and
filler-word counts — are computed deterministically from timings and a fixed
lexicon. Zero LLM, zero cloud, zero per-token cost.
"""

from potato.thinkaloud.config import ThinkAloudConfig, parse_thinkaloud_config
from potato.thinkaloud.manager import (
    ThinkAloudManager,
    clear_thinkaloud_manager,
    get_thinkaloud_manager,
    init_thinkaloud_manager,
)
from potato.thinkaloud.parser import LabelDetection, LabelPhraseParser
from potato.thinkaloud.routes import thinkaloud_bp

__all__ = [
    "ThinkAloudConfig",
    "parse_thinkaloud_config",
    "LabelPhraseParser",
    "LabelDetection",
    "ThinkAloudManager",
    "init_thinkaloud_manager",
    "get_thinkaloud_manager",
    "clear_thinkaloud_manager",
    "thinkaloud_bp",
]
