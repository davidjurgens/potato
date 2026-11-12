"""Local speaker diarization — who spoke when.

Whisper reports what was said and when. It has no speaker model at all, and
neither does faster-whisper, so a transcript straight out of
:mod:`potato.server_utils.transcripts.transcribe` arrives undiarized. This
module supplies the missing half on the same terms: on your own machine, with
no cloud API and no account.

The engine is `sherpa-onnx <https://github.com/k2-fsa/sherpa-onnx>`_ (Apache
2.0), which runs a segmentation model and a speaker-embedding model through ONNX
Runtime and clusters the embeddings. It is a 9 MB wheel with no PyTorch
dependency, which is what makes it usable as an optional extra::

    pip install "potato-annotation[transcribe]"

**On pyannote.** The default segmentation model is an ONNX export of
pyannote-segmentation-3.0 (MIT-licensed weights). The ``pyannote.audio`` package
is not involved: no PyTorch, no Lightning, no Hugging Face token, and no gated
model agreement to accept. Both model files download once from the sherpa-onnx
release page and then work offline. Point ``segmentation_model`` at your own
ONNX file to avoid the lineage entirely.

Accuracy is worth stating plainly: clustering-based diarization does badly on
crosstalk, and it cannot tell two similar voices apart in a noisy room. Treat
the speaker labels as a first pass an annotator corrects, which is what the
``audio_dialogue`` display's speaker assignment is for.
"""

from __future__ import annotations

import logging
import os
import tarfile
import tempfile
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "DiarizationError",
    "is_available",
    "require_backend",
    "model_cache_dir",
    "ensure_models",
    "diarize_file",
    "assign_speakers",
    "speaker_label",
]


class DiarizationError(RuntimeError):
    """Raised when the diarization backend or its models are unusable."""


#: Segmentation model. An ONNX export of pyannote-segmentation-3.0, published
#: by the sherpa-onnx project. Distributed as a tarball holding ``model.onnx``
#: and an int8 quantization of it.
SEGMENTATION_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
SEGMENTATION_MEMBER = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"

#: Speaker-embedding model. NeMo TitaNet-small, trained on English; ~40 MB.
EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/nemo_en_titanet_small.onnx"
)

_INSTALL_HINT = (
    'Local diarization needs sherpa-onnx: pip install '
    '"potato-annotation[transcribe]"'
)


def is_available() -> bool:
    """Whether the diarization backend can be imported."""
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return True


def require_backend() -> None:
    """Raise :class:`DiarizationError` naming the extra if the backend is missing."""
    if not is_available():
        raise DiarizationError(_INSTALL_HINT)


def model_cache_dir() -> str:
    """Where downloaded diarization models live.

    ``POTATO_MODEL_CACHE`` overrides it, which is the hook for an air-gapped
    install: stage the two files on a machine with a network, copy the
    directory across, and nothing here reaches for the internet.
    """
    override = os.environ.get("POTATO_MODEL_CACHE")
    base = override or os.path.join(
        os.path.expanduser("~"), ".cache", "potato", "models")
    return os.path.join(base, "diarization")


def speaker_label(index: int) -> str:
    """``0`` becomes ``"SPEAKER_00"``.

    The WhisperX convention, so a transcript diarized here and one diarized
    upstream produce the same labels and the same speaker colours.
    """
    return "SPEAKER_%02d" % int(index)


def _download(url: str, destination: str) -> None:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    logger.info("Downloading %s", url)
    # Download to a sibling temp file and rename, so an interrupted download
    # never leaves a truncated model that later runs would happily load.
    handle, staging = tempfile.mkstemp(dir=os.path.dirname(destination))
    os.close(handle)
    try:
        urllib.request.urlretrieve(url, staging)
        # mkstemp creates 0600 and os.replace preserves it, which leaves a
        # model only the downloading user can read. On a shared install the
        # account that runs the server is often not the one that primed the
        # cache.
        os.chmod(staging, 0o644)
        os.replace(staging, destination)
    except Exception as e:  # noqa: BLE001 - re-raised with the URL
        raise DiarizationError("Could not download %s: %s" % (url, e)) from e
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


def ensure_models(
    *,
    cache_dir: Optional[str] = None,
    segmentation_model: Optional[str] = None,
    embedding_model: Optional[str] = None,
) -> Tuple[str, str]:
    """Return paths to the segmentation and embedding models, downloading once.

    Explicit paths are used as given and are never downloaded, so an offline
    install can point at staged copies.
    """
    directory = cache_dir or model_cache_dir()

    if segmentation_model:
        if not os.path.isfile(segmentation_model):
            raise DiarizationError(
                "No such segmentation model: %s" % segmentation_model)
        segmentation = segmentation_model
    else:
        segmentation = os.path.join(directory, "segmentation.onnx")
        if not os.path.isfile(segmentation):
            tarball = os.path.join(directory, os.path.basename(SEGMENTATION_URL))
            _download(SEGMENTATION_URL, tarball)
            try:
                with tarfile.open(tarball, "r:bz2") as archive:
                    member = archive.extractfile(SEGMENTATION_MEMBER)
                    if member is None:
                        raise DiarizationError(
                            "%s is missing from %s"
                            % (SEGMENTATION_MEMBER, tarball))
                    with open(segmentation, "wb") as out:
                        out.write(member.read())
            finally:
                if os.path.exists(tarball):
                    os.unlink(tarball)

    if embedding_model:
        if not os.path.isfile(embedding_model):
            raise DiarizationError(
                "No such embedding model: %s" % embedding_model)
        embedding = embedding_model
    else:
        embedding = os.path.join(directory, "embedding.onnx")
        if not os.path.isfile(embedding):
            _download(EMBEDDING_URL, embedding)

    return segmentation, embedding


# One diarizer per configuration, for the same reason the Whisper model is
# cached: a folder of interviews would otherwise rebuild it per file.
_DIARIZER_CACHE: Dict[tuple, Any] = {}


def _build_diarizer(
    segmentation: str,
    embedding: str,
    num_speakers: Optional[int],
    threshold: float,
    min_duration_on: float,
    min_duration_off: float,
    num_threads: int,
):
    key = (segmentation, embedding, num_speakers, threshold,
           min_duration_on, min_duration_off, num_threads)
    if key in _DIARIZER_CACHE:
        return _DIARIZER_CACHE[key]

    require_backend()
    import sherpa_onnx

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=segmentation),
            num_threads=num_threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=embedding, num_threads=num_threads),
        clustering=sherpa_onnx.FastClusteringConfig(
            # -1 means "decide from the data"; the threshold governs then, and
            # is ignored when a speaker count is given.
            num_clusters=num_speakers if num_speakers else -1,
            threshold=threshold,
        ),
        min_duration_on=min_duration_on,
        min_duration_off=min_duration_off,
    )
    if not config.validate():
        raise DiarizationError(
            "Diarization config rejected by sherpa-onnx. Check that the model "
            "files are complete: %s, %s" % (segmentation, embedding))

    _DIARIZER_CACHE[key] = sherpa_onnx.OfflineSpeakerDiarization(config)
    return _DIARIZER_CACHE[key]


def diarize_file(
    path: str,
    *,
    num_speakers: Optional[int] = None,
    threshold: float = 0.5,
    min_duration_on: float = 0.3,
    min_duration_off: float = 0.5,
    num_threads: int = 2,
    cache_dir: Optional[str] = None,
    segmentation_model: Optional[str] = None,
    embedding_model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return ``[{"start", "end", "speaker"}]`` for one audio or video file.

    Args:
        num_speakers: Fix the speaker count when you know it — a two-person
            interview diarizes far better told there are two people. ``None``
            infers the count from *threshold*.
        threshold: Clustering distance. Lower splits more readily, so raise it
            when one speaker is being reported as several and lower it when two
            people are being merged. Ignored when *num_speakers* is set.
        min_duration_on: Shortest speech run kept, in seconds.
        min_duration_off: Shortest silence that ends a run, in seconds.

    Raises:
        DiarizationError: backend missing, models unavailable, or decode failed.
    """
    if not os.path.isfile(path):
        raise DiarizationError("No such media file: %s" % path)

    segmentation, embedding = ensure_models(
        cache_dir=cache_dir,
        segmentation_model=segmentation_model,
        embedding_model=embedding_model,
    )
    diarizer = _build_diarizer(
        segmentation, embedding, num_speakers, threshold,
        min_duration_on, min_duration_off, num_threads)

    try:
        # faster-whisper's decoder is already a dependency of this extra, and
        # it demuxes video too, so diarization accepts everything
        # transcription does without adding a second audio library.
        from faster_whisper.audio import decode_audio

        samples = decode_audio(path, sampling_rate=diarizer.sample_rate)
    except Exception as e:  # noqa: BLE001 - re-raised with the filename
        raise DiarizationError("Could not read audio from %s: %s" % (path, e)) from e

    try:
        result = diarizer.process(samples).sort_by_start_time()
    except Exception as e:  # noqa: BLE001 - re-raised with the filename
        raise DiarizationError("Could not diarize %s: %s" % (path, e)) from e

    return [
        {"start": float(s.start), "end": float(s.end),
         "speaker": speaker_label(s.speaker)}
        for s in result
    ]


def assign_speakers(
    segments: Sequence[Dict[str, Any]],
    diarization: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Label transcript *segments* from *diarization*, by longest overlap.

    Whisper's segment boundaries and the diarizer's turn boundaries are
    produced independently and do not line up, so a segment is given the
    speaker it shares the most time with rather than the one holding its start.
    A segment overlapping nothing keeps ``speaker: None``, which the
    ``audio_dialogue`` display renders as an undiarized turn for the annotator
    to assign.

    Returns new dicts; the input is not modified.
    """
    labelled: List[Dict[str, Any]] = []

    for segment in segments:
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or 0.0)

        best_speaker = None
        best_overlap = 0.0
        for turn in diarization:
            overlap = min(end, turn["end"]) - max(start, turn["start"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]

        entry = dict(segment)
        entry["speaker"] = best_speaker
        labelled.append(entry)

    return labelled
