"""Configuration parsing for Think-Aloud Mode (``thinkaloud:`` YAML block)."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_FILLERS = ["um", "uh", "hmm", "er", "like", "i guess", "maybe",
                   "i think", "sort of", "kind of"]

VALID_STT = ("faster_whisper", "mock", "auto")


@dataclass
class ThinkAloudConfig:
    """Parsed ``thinkaloud`` configuration.

    Attributes:
        enabled: Master switch.
        schema: Scheme whose labels can be committed by voice.
            Defaults to the first radio scheme.
        stt: Speech-to-text backend: ``faster_whisper`` (local), ``mock``
            (tests), or ``auto`` (faster_whisper if importable, else error
            at first use with a clear message).
        model: Whisper model size for faster_whisper (``tiny.en`` default —
            39 MB, CPU real-time).
        chunk_seconds: Frontend MediaRecorder restart interval. Each chunk is
            a complete audio file (required for independent decoding).
        stems: Optional override of the accepted label-phrase stem regexes.
        fillers: Filler lexicon for the deterministic hesitation signal.
        require_spoken_label: Nudge on Next when no label was committed.
        language: Whisper language hint.
    """

    enabled: bool = False
    schema: Optional[str] = None
    stt: str = "auto"
    model: str = "tiny.en"
    chunk_seconds: int = 6
    stems: Optional[List[str]] = None
    fillers: List[str] = field(default_factory=lambda: list(DEFAULT_FILLERS))
    require_spoken_label: bool = True
    language: str = "en"


def parse_thinkaloud_config(config: Dict[str, Any]) -> ThinkAloudConfig:
    block = config.get("thinkaloud") or {}
    ta = ThinkAloudConfig(
        enabled=bool(block.get("enabled", False)),
        schema=block.get("schema"),
        stt=str(block.get("stt", "auto")),
        model=str(block.get("model", "tiny.en")),
        chunk_seconds=int(block.get("chunk_seconds", 6)),
        stems=block.get("stems"),
        fillers=list(block.get("fillers", DEFAULT_FILLERS)),
        require_spoken_label=bool(block.get("require_spoken_label", True)),
        language=str(block.get("language", "en")),
    )

    if ta.stt not in VALID_STT:
        logger.warning("thinkaloud.stt '%s' unknown; using 'auto' (valid: %s)",
                       ta.stt, VALID_STT)
        ta.stt = "auto"
    if not 2 <= ta.chunk_seconds <= 30:
        logger.warning("thinkaloud.chunk_seconds must be 2-30; using 6")
        ta.chunk_seconds = 6

    if ta.enabled and not ta.schema:
        for scheme in config.get("annotation_schemes", []) or []:
            if scheme.get("annotation_type") == "radio":
                ta.schema = scheme.get("name")
                break
        if ta.schema:
            logger.info("thinkaloud.schema not set; defaulting to '%s'", ta.schema)
        else:
            logger.warning("thinkaloud enabled but no radio scheme found; "
                           "voice labeling will be inactive")

    return ta
