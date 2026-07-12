"""Pluggable local speech-to-text backends for Think-Aloud Mode.

All backends run on the local machine — no cloud APIs, no per-token cost.

- ``faster_whisper``: CTranslate2 Whisper (``pip install faster-whisper``).
  Decodes complete webm/ogg/wav blobs via PyAV, so the frontend restarts
  MediaRecorder per chunk to keep every blob independently decodable.
- ``mock``: echoes the ``mock_text`` provided with the request. For tests and
  development without audio hardware.

Adding a backend (e.g. Vosk): subclass :class:`STTBackend`, implement
``transcribe(audio_bytes, mock_text=None) -> str``, register in ``create_stt``.
"""

import io
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class STTError(RuntimeError):
    """Raised when a backend is unavailable or transcription fails fatally."""


class STTBackend(ABC):
    name = "base"

    @abstractmethod
    def transcribe(self, audio_bytes: bytes,
                   mock_text: Optional[str] = None) -> str:
        """Return the transcript for one complete audio blob ('' if silent)."""


class MockSTT(STTBackend):
    """Echoes ``mock_text``; ignores audio. For tests/dev."""

    name = "mock"

    def transcribe(self, audio_bytes: bytes,
                   mock_text: Optional[str] = None) -> str:
        return mock_text or ""


class FasterWhisperSTT(STTBackend):
    """Local Whisper via CTranslate2. Model loads once, lazily."""

    name = "faster_whisper"

    def __init__(self, model_size: str = "tiny.en", language: str = "en") -> None:
        try:
            from faster_whisper import WhisperModel  # noqa: F401
        except ImportError as e:
            raise STTError(
                "Think-Aloud needs the faster-whisper package for local "
                "speech-to-text: pip install faster-whisper"
            ) from e
        self._model_size = model_size
        self._language = language
        self._model = None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            logger.info("Loading Whisper model '%s' (first use)...", self._model_size)
            self._model = WhisperModel(self._model_size, device="cpu",
                                       compute_type="int8")
        return self._model

    def transcribe(self, audio_bytes: bytes,
                   mock_text: Optional[str] = None) -> str:
        if not audio_bytes:
            return ""
        model = self._get_model()
        language = None if self._language == "auto" else \
            self._language.split(".")[0].split("-")[0]
        try:
            segments, _info = model.transcribe(
                io.BytesIO(audio_bytes),
                language=language,
                vad_filter=True,
                beam_size=1,
            )
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            # A malformed chunk (e.g. truncated container) shouldn't kill the
            # session; log and treat as silence.
            logger.warning("Chunk transcription failed (%s); treating as silence", e)
            return ""


def create_stt(kind: str, model: str = "tiny.en", language: str = "en") -> STTBackend:
    """Instantiate a backend. ``auto`` prefers faster_whisper."""
    if kind == "mock":
        return MockSTT()
    if kind in ("faster_whisper", "auto"):
        try:
            return FasterWhisperSTT(model_size=model, language=language)
        except STTError:
            if kind == "faster_whisper":
                raise
            raise STTError(
                "No local STT backend available. Install one with: "
                "pip install faster-whisper  (or set thinkaloud.stt: mock "
                "for development)"
            )
    raise STTError(f"Unknown STT backend '{kind}'")
