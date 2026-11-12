"""Local speech-to-text for audio and video files.

Every other module in this package *reads* a transcript somebody else produced.
This one produces the transcript, on the annotator's own machine, with no cloud
API and no per-minute charge.

Two engines run the same Whisper models (a size name, or a CTranslate2
directory such as a ``whisper-asr`` run's ``ct2/``):

- `WhisperX <https://github.com/m-bain/whisperX>`_, used when it is installed
  and works here: batched decoding over voice-activity segments, and, with
  ``word_timestamps``, word times from forced alignment. A separate install
  (``pip install whisperx``): it pins its own torch.
- `faster-whisper <https://github.com/SYSTRAN/faster-whisper>`_, Whisper
  compiled through CTranslate2, from the ``transcribe`` extra::

    pip install "potato-annotation[transcribe]"

``engine="auto"`` (the default) takes WhisperX and falls back to
faster-whisper when WhisperX is missing, does not import (a torch it was not
built for), cannot run on the device (neither engine has Apple's Metal), or
fails to load the model or to transcribe a file. The log says which engine
ran and why it fell back; the result says so in ``engine``.

Output is deliberately the plain-Whisper JSON shape, ``{"segments": [...]}``,
because :func:`potato.server_utils.transcripts.normalize_transcript` already
accepts it. Transcribing a file and reading a Whisper JSON file therefore take
the same path through the rest of the package, and a transcript produced here
can be written to disk and re-read later without conversion.

**No diarization here.** Whisper reports what was said and when; it does not
report who said it (WhisperX's own diarization needs gated pyannote weights
and is not used). Every segment comes back with ``speaker: None``, which the
``audio_dialogue`` display renders as an undiarized turn the annotator assigns a
speaker to. For automatic speaker labels, run WhisperX or pyannote upstream and
ingest their output through the normalizer instead.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TranscriptionError",
    "ENGINES",
    "whisperx_status",
    "expected_engine",
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


#: ``auto`` is WhisperX when it works here, otherwise faster-whisper.
ENGINES = ("auto", "whisperx", "faster-whisper")

_WHISPERX_HINT = "WhisperX is a separate install: pip install whisperx"


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


_WHISPERX_STATUS: Optional[tuple] = None


def whisperx_status() -> tuple:
    """``(usable, why not)``: whether WhisperX imports. Any exception counts,
    not only ImportError: a WhisperX whose pyannote needs an older torchaudio
    raises AttributeError on import. Checked once per process."""
    global _WHISPERX_STATUS
    if _WHISPERX_STATUS is None:
        try:
            import whisperx  # noqa: F401
            import whisperx.asr  # noqa: F401
            _WHISPERX_STATUS = (True, "")
        except ImportError:
            _WHISPERX_STATUS = (False, "WhisperX is not installed")
        except Exception as e:  # noqa: BLE001 - a broken install is a reason, not a crash
            _WHISPERX_STATUS = (False, "WhisperX does not import here (%s: %s)"
                                % (type(e).__name__, e))
    return _WHISPERX_STATUS


def is_available(engine: str = "auto") -> bool:
    """Whether *engine* (or, for ``auto``, either engine) can be imported."""
    if engine == "whisperx":
        return whisperx_status()[0]
    if engine == "faster-whisper":
        return _faster_whisper_available()
    return whisperx_status()[0] or _faster_whisper_available()


def require_backend(engine: str = "auto") -> None:
    """Raise :class:`TranscriptionError` naming the install if *engine* is missing."""
    if not is_available(engine):
        if engine == "whisperx":
            raise TranscriptionError("%s. %s" % (whisperx_status()[1], _WHISPERX_HINT))
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
    key = ("faster-whisper", model, device, compute_type)
    if key not in _MODEL_CACHE:
        require_backend("faster-whisper")
        from faster_whisper import WhisperModel

        logger.info("Loading Whisper model '%s' on %s (first use)", model, device)
        try:
            _MODEL_CACHE[key] = WhisperModel(
                model, device=device, compute_type=compute_type)
        except Exception as e:  # noqa: BLE001 - surfaced with context below
            text = str(e).rstrip(". ")
            # The download hint only where a download could be the cause: a
            # device or compute type the machine has not is not one.
            hint = "" if (os.path.isdir(str(model)) or re.search(
                r"device|compute.?type|cuda|mps", text, re.I)) else (
                " Model weights download on first use, so this also fails on a "
                "machine with no network that has never run the model before.")
            raise TranscriptionError(
                "Could not load Whisper model '%s' on device '%s': %s.%s"
                % (model, device, text, hint)
            ) from e
    return _MODEL_CACHE[key]


def _clamp(start: Any, end: Any, duration: float) -> tuple:
    """Segment times inside the recording. tiny.en has ended a segment of a
    2.7 s file at 7.0 s."""
    start, end = float(start), float(end)
    if duration > 0:
        start, end = min(max(0.0, start), duration), min(max(0.0, end), duration)
    return start, max(start, end)


class _WhisperXUnusable(Exception):
    """WhisperX cannot run this model on this device: no file will work."""


#: (model, device, compute_type) WhisperX could not load, and why: later
#: files go straight to faster-whisper instead of failing the same way.
_WHISPERX_REFUSED: Dict[tuple, str] = {}
#: (language, device) to the loaded alignment model, or to why it could not
#: load: a directory of files loads it, or fails to, once.
_ALIGNERS: Dict[tuple, Any] = {}
_ANNOUNCED: set = set()


def _announce(message: str, *args: Any, level: int = logging.INFO) -> None:
    """Log *message* once per process: a directory of 200 files says it once."""
    text = message % args if args else message
    if text not in _ANNOUNCED:
        _ANNOUNCED.add(text)
        logger.log(level, text)


def _load_whisperx(model: str, device: str, compute_type: str,
                   language: Optional[str], beam_size: int):
    key = ("whisperx", model, device, compute_type, language, beam_size)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    if device not in ("cpu", "cuda"):
        raise _WhisperXUnusable("WhisperX runs on cpu or cuda, not %s" % device)
    import whisperx
    logger.info("Loading Whisper model '%s' in WhisperX on %s (first use)", model, device)
    try:
        _MODEL_CACHE[key] = whisperx.load_model(
            model, device, compute_type=compute_type, language=language,
            asr_options={"beam_size": beam_size})
    except Exception as e:  # noqa: BLE001
        raise _WhisperXUnusable("WhisperX could not load '%s': %s: %s"
                                % (model, type(e).__name__, e)) from e
    return _MODEL_CACHE[key]


def _transcribe_whisperx(path: str, *, model: str, language: Optional[str], device: str,
                         compute_type: str, word_timestamps: bool, beam_size: int,
                         batch_size: int = 8) -> Dict[str, Any]:
    import whisperx
    if language and language != "en" and os.path.basename(str(model).rstrip("/")).endswith(".en"):
        # As faster-whisper does: an English-only model transcribes English.
        _announce("%s is English-only; transcribing as en, not %s", model, language,
                  level=logging.WARNING)
        language = "en"
    pipeline = _load_whisperx(model, device, compute_type, language, beam_size)
    audio = whisperx.load_audio(path)
    result = pipeline.transcribe(audio, batch_size=batch_size, language=language)
    detected = result.get("language") or language
    segments = list(result.get("segments") or [])
    aligned = False
    if word_timestamps and segments and detected:
        key = (detected, device)
        if key not in _ALIGNERS:
            try:
                _ALIGNERS[key] = whisperx.load_align_model(detected, device)
            except Exception as e:  # noqa: BLE001 - segment times are still good
                _ALIGNERS[key] = "%s: %s" % (type(e).__name__, e)
        aligner = _ALIGNERS[key]
        if isinstance(aligner, str):
            _announce("WhisperX could not load a word-alignment model for language %r "
                      "(%s); segments keep their times, without word times",
                      detected, aligner, level=logging.WARNING)
        else:
            try:
                segments = list(whisperx.align(segments, aligner[0], aligner[1], audio, device)
                                .get("segments") or segments)
                aligned = True
            except Exception as e:  # noqa: BLE001
                logger.warning("WhisperX could not align the words of %s (%s: %s); its "
                               "segments keep their times", path, type(e).__name__, e)
    duration = float(len(audio)) / 16000.0
    out_segments: List[Dict[str, Any]] = []
    untimed = 0
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        if segment.get("start") is None or segment.get("end") is None:
            untimed += 1
            continue
        start, end = _clamp(segment["start"], segment["end"], duration)
        entry: Dict[str, Any] = {"id": len(out_segments), "start": start, "end": end,
                                 "text": text}
        if aligned and segment.get("words"):
            # A word alignment could not place (a number, a symbol) has no
            # times; it is left out rather than given its neighbour's.
            entry["words"] = [
                {"start": float(w["start"]), "end": float(w["end"]),
                 "word": str(w.get("word", "")), "probability": float(w.get("score") or 0.0)}
                for w in segment["words"]
                if w.get("start") is not None and w.get("end") is not None]
        out_segments.append(entry)
    if untimed:
        logger.warning("WhisperX gave %d segment(s) of %s no times; left out", untimed, path)
    return {"segments": out_segments, "language": detected,
            "duration": duration, "engine": "whisperx"}


def expected_engine(engine: str, model: str, device: str = "cpu",
                    compute_type: str = "int8") -> str:
    """The engine :func:`transcribe_file` would use for these settings now:
    *engine* itself when one is named; under ``auto``, WhisperX when it
    imports, runs on *device* and has not refused this model, else
    faster-whisper. What a cached transcript is checked against."""
    if engine != "auto":
        return engine
    if (whisperx_status()[0] and device in ("cpu", "cuda")
            and (model, device, compute_type) not in _WHISPERX_REFUSED):
        return "whisperx"
    return "faster-whisper"


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
    engine: str = "auto",
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
        engine: ``"auto"`` (WhisperX when it works here, else faster-whisper),
            ``"whisperx"`` or ``"faster-whisper"``. A named engine that cannot
            run raises instead of falling back.

    Returns:
        ``{"segments": [...], "language": ..., "duration": ..., "engine": ...}``
        — the plain Whisper JSON shape, ready for ``normalize_transcript``.
        Segments carry ``start`` and ``end`` in **seconds**, matching the
        rest of the package.

    Raises:
        TranscriptionError: backend missing, file missing, or decode failed.
    """
    if engine not in ENGINES:
        raise TranscriptionError("engine must be one of %s, not %r" % (", ".join(ENGINES), engine))
    if not os.path.isfile(path):
        raise TranscriptionError("No such media file: %s" % path)

    file_fallback = ""
    if engine in ("auto", "whisperx"):
        usable, why = whisperx_status()
        refused = _WHISPERX_REFUSED.get((model, device, compute_type))
        if usable and not refused:
            if not vad_filter:
                _announce("WhisperX always runs voice-activity detection; vad_filter=False "
                          "applies to faster-whisper only")
            try:
                payload = _transcribe_whisperx(
                    path, model=model, language=language, device=device,
                    compute_type=compute_type, word_timestamps=word_timestamps,
                    beam_size=beam_size)
                _announce("Transcribing with WhisperX")
                return payload
            except _WhisperXUnusable as e:
                _WHISPERX_REFUSED[(model, device, compute_type)] = str(e)
                why = str(e)
                file_fallback = why
            except Exception as e:  # noqa: BLE001 - this file falls back
                if engine == "whisperx":
                    raise TranscriptionError("Could not transcribe %s with WhisperX: %s"
                                             % (path, e)) from e
                logger.warning("WhisperX could not transcribe %s (%s: %s); using "
                               "faster-whisper for it", path, type(e).__name__, e)
                why = ""
                file_fallback = "%s: %s" % (type(e).__name__, e)
        else:
            why = refused or why
            if usable and refused:
                # WhisperX imports here but refused this model: every file
                # says so, so a later process (which forgets the refusal)
                # takes its faster-whisper transcript from the cache too.
                file_fallback = refused
        if engine == "whisperx":
            # The install hint only when WhisperX does not import.
            raise TranscriptionError("%s. %s" % (why, _WHISPERX_HINT) if not usable else why)
        if why:
            _announce("%s; transcribing with faster-whisper", why, level=logging.WARNING)

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

    duration = float(getattr(info, "duration", 0.0) or 0.0)
    out_segments: List[Dict[str, Any]] = []
    for segment in collected:
        text = (segment.text or "").strip()
        if not text:
            continue
        start, end = _clamp(segment.start, segment.end, duration)
        entry: Dict[str, Any] = {
            "id": len(out_segments),
            "start": start,
            "end": end,
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

    payload = {
        "segments": out_segments,
        "language": getattr(info, "language", language),
        "duration": duration,
        "engine": "faster-whisper",
    }
    if file_fallback:
        # WhisperX was tried on this file and failed: a cache entry that
        # says so stands for an auto run as well as a faster-whisper one.
        payload["whisperx_failed"] = file_fallback
    return payload
