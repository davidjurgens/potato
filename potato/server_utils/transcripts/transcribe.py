"""Local speech-to-text for audio and video files.

Every other module in this package *reads* a transcript somebody else produced.
This one produces the transcript, on the annotator's own machine, with no cloud
API and no per-minute charge.

The engine is `faster-whisper <https://github.com/SYSTRAN/faster-whisper>`_ —
Whisper compiled through CTranslate2, several times quicker than the reference
implementation on CPU. It is an optional dependency::

    pip install "potato-annotation[transcribe]"

Output is deliberately the plain-Whisper JSON shape, ``{"segments": [...]}``,
because :func:`potato.server_utils.transcripts.normalize_transcript` already
accepts it. Transcribing a file and reading a Whisper JSON file therefore take
the same path through the rest of the package, and a transcript produced here
can be written to disk and re-read later without conversion.

**No diarization.** Whisper reports what was said and when; it does not report
who said it. Every segment comes back with ``speaker: None``, which the
``audio_dialogue`` display renders as an undiarized turn the annotator assigns a
speaker to. For automatic speaker labels, run WhisperX or pyannote upstream and
ingest their output through the normalizer instead.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TranscriptionError",
    "MODEL_SIZES",
    "AUDIO_EXTENSIONS",
    "is_available",
    "require_backend",
    "looks_like_media",
    "transcribe_file",
    "cache_path_for",
]


class TranscriptionError(RuntimeError):
    """Raised when the ASR backend is missing or a file cannot be transcribed."""


#: Whisper model sizes, smallest first. The ``.en`` variants are English-only
#: and noticeably better than the multilingual model of the same size on
#: English audio. ``base`` is the default: roughly real-time on a laptop CPU.
MODEL_SIZES = (
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large-v3", "large-v3-turbo",
)

#: Extensions treated as transcribable media. Video is included because the
#: decoder pulls the audio track out; there is no need to demux first.
AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac", ".wma",
    ".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v",
})

_INSTALL_HINT = (
    'Local transcription needs faster-whisper: pip install '
    '"potato-annotation[transcribe]"'
)


def is_available() -> bool:
    """Whether the ASR backend can be imported."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def require_backend() -> None:
    """Raise :class:`TranscriptionError` naming the extra if ASR is missing."""
    if not is_available():
        raise TranscriptionError(_INSTALL_HINT)


def looks_like_media(path: str) -> bool:
    """Whether *path* has an extension we would try to transcribe."""
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def cache_path_for(media_path: str, cache_dir: Optional[str] = None) -> str:
    """Where the transcript for *media_path* is written and looked for.

    Transcription is the slowest thing in any pipeline that uses it, and a
    directory of interviews gets re-run whenever the surrounding config
    changes. The cache is keyed on the media basename, so ``talk_01.mp3``
    always maps to ``talk_01.whisper.json``.
    """
    stem = os.path.splitext(os.path.basename(media_path))[0]
    directory = cache_dir or os.path.dirname(os.path.abspath(media_path))
    return os.path.join(directory, stem + ".whisper.json")


# Models are expensive to construct and cheap to keep, and a directory of two
# hundred files would otherwise pay the load once per file.
_MODEL_CACHE: Dict[tuple, Any] = {}


def _load_model(model: str, device: str, compute_type: str):
    key = (model, device, compute_type)
    if key not in _MODEL_CACHE:
        require_backend()
        from faster_whisper import WhisperModel

        logger.info("Loading Whisper model '%s' on %s (first use)", model, device)
        try:
            _MODEL_CACHE[key] = WhisperModel(
                model, device=device, compute_type=compute_type)
        except Exception as e:  # noqa: BLE001 - surfaced with context below
            raise TranscriptionError(
                "Could not load Whisper model '%s' on device '%s': %s. "
                "Model weights download on first use, so this also fails on a "
                "machine with no network that has never run the model before."
                % (model, device, e)
            ) from e
    return _MODEL_CACHE[key]


def transcribe_file(
    path: str,
    *,
    model: str = "base",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    vad_filter: bool = True,
    word_timestamps: bool = False,
    beam_size: int = 5,
) -> Dict[str, Any]:
    """Transcribe one audio or video file.

    Args:
        path: Media file to read. Video is accepted; the audio track is used.
        model: A :data:`MODEL_SIZES` name, or a path to a CTranslate2 model
            directory for an offline install.
        language: ISO code (``"en"``, ``"de"``). ``None`` auto-detects, which
            costs one extra pass over the first 30 seconds.
        device: ``"cpu"`` or ``"cuda"``.
        compute_type: ``"int8"`` on CPU, ``"float16"`` on GPU.
        vad_filter: Drop non-speech with Silero VAD before decoding. Cuts the
            hallucinated text Whisper produces over silence.
        word_timestamps: Also return per-word timings. Roughly 20% slower, and
            needed only if the task annotates below the segment level.
        beam_size: Decoder beam width. 1 is fastest, 5 is the Whisper default.

    Returns:
        ``{"segments": [...], "language": ..., "duration": ...}`` — the plain
        Whisper JSON shape, ready for ``normalize_transcript``. Segments carry
        ``start`` and ``end`` in **seconds**, matching the rest of the package.

    Raises:
        TranscriptionError: backend missing, file missing, or decode failed.
    """
    if not os.path.isfile(path):
        raise TranscriptionError("No such media file: %s" % path)

    whisper = _load_model(model, device, compute_type)

    try:
        segments, info = whisper.transcribe(
            path,
            language=language,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            beam_size=beam_size,
        )
        # faster-whisper streams segments lazily; decoding happens here.
        collected = list(segments)
    except Exception as e:  # noqa: BLE001 - re-raised with the filename
        raise TranscriptionError("Could not transcribe %s: %s" % (path, e)) from e

    out_segments: List[Dict[str, Any]] = []
    for index, segment in enumerate(collected):
        text = (segment.text or "").strip()
        if not text:
            continue
        entry: Dict[str, Any] = {
            "id": index,
            "start": float(segment.start),
            "end": float(segment.end),
            "text": text,
        }
        words = getattr(segment, "words", None)
        if word_timestamps and words:
            entry["words"] = [
                {"start": float(w.start), "end": float(w.end),
                 "word": w.word, "probability": float(getattr(w, "probability", 0.0))}
                for w in words
                if w.start is not None and w.end is not None
            ]
        out_segments.append(entry)

    return {
        "segments": out_segments,
        "language": getattr(info, "language", language),
        "duration": float(getattr(info, "duration", 0.0) or 0.0),
    }
