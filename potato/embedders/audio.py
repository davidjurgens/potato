"""
CLAP audio embeddings.

CLAP is to audio what CLIP is to images: a shared audio/text space, so a corpus
map of recordings can later be checked against text descriptions with no second
model. Everything is lazy — naming this backend costs nothing until it runs.

    embeddings:
      backend: audio
      model: laion/clap-htsat-unfused
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

from potato.embedders.base import EmbeddingBackend, probe, require
from potato.embedders.image import ImageEmbeddingBackend  # cache helpers only

logger = logging.getLogger(__name__)

DEFAULT_AUDIO_MODEL = "laion/clap-htsat-unfused"

#: CLAP's training rate. Resampling to it is not optional: feeding 44.1 kHz
#: audio to a 48 kHz model produces vectors that are quietly wrong rather than
#: an error.
TARGET_SAMPLE_RATE = 48000


class AudioEmbeddingBackend(EmbeddingBackend):
    name = "audio"
    modality = "audio"
    default_model = DEFAULT_AUDIO_MODEL
    source_fields = ("audio_url", "audio", "audio_path", "sound", "speech")
    extensions = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus",
                  ".wma")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = None
        self._processor = None
        self._cache = None
        self.max_seconds = float(self.options.get("max_seconds", 30))

    def available(self) -> Tuple[bool, Optional[str]]:
        ok, reason = probe("transformers", "transformers", "Audio embeddings")
        if not ok:
            return ok, reason
        import importlib.util
        if (importlib.util.find_spec("soundfile") is None
                and importlib.util.find_spec("librosa") is None):
            return False, ("Audio embeddings need an audio reader: "
                           "pip install soundfile (or librosa)")
        return True, None

    # -- model -----------------------------------------------------------

    def _load(self):
        if self._model is None:
            require("transformers", "transformers", "Audio embeddings")
            from transformers import ClapModel, ClapProcessor
            logger.info("embedders: loading audio model %s", self.model)
            self._model = ClapModel.from_pretrained(self.model)
            self._processor = ClapProcessor.from_pretrained(self.model)
            self._model.eval()
        return self._model, self._processor

    def _cache_store(self):
        if self._cache is None and self.cache_dir:
            from potato.vision_features import EmbeddingCache
            self._cache = EmbeddingCache(self.cache_dir, f"clap-{self.model}")
        return self._cache

    # -- reading ---------------------------------------------------------

    def _read(self, reference: str):
        """One mono waveform at CLAP's sample rate, or None."""
        numpy = require("numpy", "numpy", "Audio embeddings")
        path = reference
        if self.media_root and not str(reference).startswith(
                ("http://", "https://", "/")):
            import os
            path = os.path.join(self.media_root, reference)
        try:
            try:
                import librosa
                audio, _ = librosa.load(path, sr=TARGET_SAMPLE_RATE, mono=True)
            except ImportError:
                import soundfile
                audio, rate = soundfile.read(path, dtype="float32")
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                if rate != TARGET_SAMPLE_RATE:
                    # No resampler available: refuse rather than embed audio
                    # the model will interpret at the wrong speed.
                    raise RuntimeError(
                        f"{path} is {rate} Hz; install librosa to resample to "
                        f"{TARGET_SAMPLE_RATE} Hz")
        except Exception as exc:
            logger.debug("Could not read audio %s: %s", reference, exc)
            return None
        limit = int(self.max_seconds * TARGET_SAMPLE_RATE)
        return numpy.asarray(audio[:limit], dtype="float32")

    # -- work ------------------------------------------------------------

    def embed(self, references: Sequence[str]):
        numpy = require("numpy", "numpy", "Audio embeddings")
        refs = list(references)
        self.failures = []
        if not refs:
            return numpy.zeros((0, 1))

        from potato.vision_features import fingerprint

        cache = self._cache_store()
        vectors: List = [None] * len(refs)
        pending = []
        for index, reference in enumerate(refs):
            cached = cache.get(fingerprint(reference)) if cache else None
            if cached is not None:
                vectors[index] = cached
            else:
                pending.append(index)

        if pending:
            model, processor = self._load()
            import torch
            waveforms, loaded = [], []
            for index in pending:
                audio = self._read(refs[index])
                if audio is None:
                    self.failures.append(refs[index])
                    continue
                waveforms.append(audio)
                loaded.append(index)
            if waveforms:
                inputs = processor(audios=waveforms,
                                   sampling_rate=TARGET_SAMPLE_RATE,
                                   return_tensors="pt", padding=True)
                with torch.no_grad():
                    features = model.get_audio_features(**inputs)
                encoded = features.cpu().numpy()
                for position, index in enumerate(loaded):
                    vectors[index] = encoded[position]
                    if cache:
                        cache.put(fingerprint(refs[index]), encoded[position])

        width = next((len(v) for v in vectors if v is not None), 1)
        # A zero row, not a dropped row: callers index against the input list.
        return numpy.vstack([v if v is not None else numpy.zeros(width)
                             for v in vectors])
