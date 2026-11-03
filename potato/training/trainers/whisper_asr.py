"""Fine-tune Whisper on the transcript turns annotators corrected.

For ``speech_transcript`` schemes. Each corrected turn is one example: the
turn's audio, cut from the item's recording by the turn's start and end and
resampled to 16 kHz, and the annotator's corrected text. A turn nobody
corrected is not an example: the scheme saves only the turns an annotator
touched, so an untouched one may be right or unread.

Prediction transcribes every turn of every held-out and unlabelled item. A
turn whose new text differs from the transcript's is a correction prelabel
in the scheme's own shape, ``{index, start, end, errors: ["asr_error"],
correction}``, with the model's mean token probability as ``confidence``.
Held-out scores are word and character error rates against the
corrections, beside the original transcript's error rate on the same turns.

With ``export_ct2`` (the default) and ctranslate2 installed, the run also
writes a CTranslate2 copy under ``ct2/``, so ``potato transcripts
--transcribe --asr-model <run>/ct2`` transcribes new recordings with the
fine-tuned model through faster-whisper.

Whisper's weights are MIT.
"""

from __future__ import annotations

import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-audio]'"
_NEEDS = ("torch", "transformers", "soundfile", "scipy")
DEFAULT_MODEL = "openai/whisper-small"
RATE = 16000
#: Whisper's input window.
MAX_CLIP_S = 30.0


def _local_file(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def _same_text(a: str, b: str) -> bool:
    from potato.training.audio_metrics import _words
    return _words(a) == _words(b)


class WhisperASRTrainer(Trainer):
    name: ClassVar[str] = "whisper-asr"
    description: ClassVar[str] = (
        "Fine-tunes Whisper on the transcript turns annotators corrected, "
        "and suggests corrections for the rest. Exports a faster-whisper copy.")
    kinds: ClassVar[Tuple[str, ...]] = ("transcript",)
    modalities: ClassVar[Tuple[str, ...]] = ("audio",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "MIT"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 5, "batch_size": 8,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.0, "warmup_ratio": 0.1, "patience": 2,
                "precision": "auto", "lora": False, "language": None,
                "max_new_tokens": 128, "export_ct2": True, "min_instances": 10}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "gradient_accumulation", "weight_decay",
                  "warmup_ratio", "patience", "precision", "lora", "min_instances")}
        props["epochs"] = dict(props["epochs"], default=5)
        props["batch_size"] = dict(props["batch_size"], default=8)
        props["lora"] = dict(props["lora"], default=False)
        props["min_instances"] = dict(props["min_instances"], default=10,
                                      description="Fewest corrected turns to train on.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A Whisper checkpoint: openai/whisper-tiny, "
                                          "-base, -small, -medium, -large-v3, "
                                          "-large-v3-turbo, or a local path."},
            "learning_rate": {"type": ["number", "null"], "default": None,
                              "description": "Defaults to 1e-5, or 1e-4 with LoRA."},
            "language": {"type": ["string", "null"], "default": None,
                         "description": "The recordings' language (en, fr, ...). "
                                        "Unset: detected once from the training turns."},
            "max_new_tokens": {"type": "integer", "minimum": 1, "default": 128},
            "export_ct2": {"type": "boolean", "default": True,
                           "description": "Also write a CTranslate2 copy for "
                                          "faster-whisper (needs ctranslate2)."},
        })
        return {"type": "object", "properties": props, "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles speech_transcript "
                            "corrections." % (schema.name, schema.kind))
        n = sum(len((row.get("targets") or {}).get(schema.name) or [])
                for row in bundle.read_split("train"))
        if n < int(params["min_instances"]):
            problems.append("Only %d corrected turns in the train split; this trainer needs "
                            "at least %d. Correct more, or lower min_instances."
                            % (n, int(params["min_instances"])))
        problems.extend(hf.quantize_unsupported(params))
        return problems

    # ------------------------------------------------------------ data

    def _clips(self, bundle: BundleRef, rows, schema: str, report: ProgressReporter,
               targets_only: bool) -> List[Dict[str, Any]]:
        """One entry per turn: its audio and, when corrected, its text."""
        from potato.training.trainers.hf_audio_tagger import load_audio
        out, missing, long_turns = [], 0, 0
        for row in rows:
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local_file(path):
                missing += 1
                continue
            corrected = {t["index"]: t for t in (row.get("targets") or {}).get(schema) or []}
            turns = list(corrected.values()) if targets_only else row.get("turns") or []
            if not turns:
                continue
            samples = load_audio(path, RATE)
            for turn in turns:
                start, end = float(turn["start"]), float(turn["end"])
                if end <= start:
                    continue
                if end - start > MAX_CLIP_S:
                    long_turns += 1
                    continue
                clip = samples[int(start * RATE):int(end * RATE)]
                if not len(clip):
                    continue
                entry = {"row": row, "index": int(turn["index"]), "start": start,
                         "end": end, "audio": clip, "asr_text": turn.get("text", "")}
                if int(turn["index"]) in corrected:
                    entry["text"] = corrected[int(turn["index"])]["text"]
                    entry["asr_text"] = corrected[int(turn["index"])].get("asr_text", "")
                out.append(entry)
        if missing:
            report.log("warning", "Left out %d item(s) with no local audio file" % missing)
        if long_turns:
            report.log("warning", "Left out %d turn(s) longer than Whisper's %d s window"
                                  % (long_turns, MAX_CLIP_S))
        return out

    def _load(self, params, spec, report, model_path, artifact_dir=None, card=None):
        import torch
        from transformers import AutoProcessor, WhisperForConditionalGeneration
        device = hf.pick_device(spec, report)
        dtype = torch.float32
        if device.startswith("cuda") and params.get("precision") != "fp32" \
                and torch.cuda.is_bf16_supported():
            dtype = torch.bfloat16
        if card is None:
            processor = AutoProcessor.from_pretrained(model_path)
            model = WhisperForConditionalGeneration.from_pretrained(model_path, dtype=dtype)
        else:
            processor = AutoProcessor.from_pretrained(os.path.join(artifact_dir, hf.MODEL_DIR))
            model = hf.load_pretrained(WhisperForConditionalGeneration, artifact_dir, card,
                                       device, dtype=dtype)
        if params.get("language"):
            processor.tokenizer.set_prefix_tokens(language=params["language"],
                                                  task="transcribe", predict_timestamps=False)
        return device, dtype, processor, model

    def _settle_language(self, model, processor, clips, params, device, dtype, report):
        """With no ``language``, a multilingual Whisper detects one per clip
        when it generates and puts its token after the start token, while
        the labels it trained on had none: trained on one prefix, asked to
        continue another. The recordings' language is detected once, on the
        base model, and used for both."""
        config = model.generation_config
        if params.get("language") or not getattr(config, "is_multilingual", False) \
                or not getattr(config, "lang_to_id", None):
            return
        import torch
        # Spread over the train turns, not the first sixteen: those are
        # often one recording.
        k = min(16, len(clips))
        sample = [clips[i * len(clips) // k] for i in range(k)]
        with torch.inference_mode():
            ids = model.detect_language(self._features(processor, sample, device, dtype))
        names = {v: k for k, v in config.lang_to_id.items()}
        votes: Dict[str, int] = {}
        for token_id in ids.view(-1).tolist():
            code = str(names.get(int(token_id), "")).strip("<|>")
            if code:
                votes[code] = votes.get(code, 0) + 1
        if not votes:
            return
        params["language"] = max(sorted(votes), key=votes.get)
        processor.tokenizer.set_prefix_tokens(language=params["language"], task="transcribe",
                                              predict_timestamps=False)
        share = votes[params["language"]] / float(sum(votes.values()))
        if share < 0.75:
            # One language for every turn; a mixed corpus needs it chosen.
            report.log("warning", "The sampled turns are in several languages (%s); "
                                  "training as %r. Set the language parameter, or run "
                                  "each language's items separately."
                       % (", ".join("%s %d" % (k, v) for k, v in sorted(
                           votes.items(), key=lambda kv: -kv[1])), params["language"]))
        else:
            report.log("info", "Detected language %r in %d of %d sampled turns; set the "
                               "language parameter to choose it instead"
                       % (params["language"], votes[params["language"]], len(sample)))

    def _features(self, processor, clips, device, dtype):
        features = processor.feature_extractor(
            [c["audio"] for c in clips], sampling_rate=RATE, return_tensors="pt").input_features
        return features.to(device, dtype)

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 1e-4 if params["lora"] else 1e-5
        schema = spec.primary_schema
        train = self._clips(bundle, bundle.read_split("train"), schema.name, report, True)
        val = self._clips(bundle, bundle.read_split("val"), schema.name, report, True)
        if not train:
            raise TrainerError("No corrected turns with local audio for %r" % schema.name)
        hf.seed_everything(spec.seed)
        report.status("running", "loading %s" % params["model_name"])
        device, dtype, processor, model = self._load(params, spec, report, params["model_name"])
        model = hf.place(model, device)
        # On the base model, before any adapter, on the device it runs on.
        self._settle_language(model, processor, train, params, device, dtype, report)
        model = hf.apply_lora(model, params["lora"], None, report)
        model = hf.place(model, device)
        tokenizer = processor.tokenizer
        start_id = model.config.decoder_start_token_id
        report.log("info", "%d corrected turns to train on (%.0f s of audio), %d val"
                   % (len(train), sum(c["end"] - c["start"] for c in train), len(val)))

        def loss_of(batch):
            labels = tokenizer([c["text"] for c in batch], padding=True,
                               return_tensors="pt")
            ids = labels.input_ids.masked_fill(labels.attention_mask == 0, -100)
            # The model prepends the start token itself.
            if (ids[:, 0] == start_id).all():
                ids = ids[:, 1:]
            return model(input_features=self._features(processor, batch, device, dtype),
                         labels=ids.to(device)).loss

        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        selected = {"best": None, "saved": False}

        def save():
            model.save_pretrained(model_dir)
            processor.save_pretrained(model_dir)
            # transformers 5 writes the feature extractor into
            # processor_config.json; faster-whisper and the CTranslate2
            # converter read preprocessor_config.json.
            processor.feature_extractor.save_pretrained(model_dir)

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.audio_metrics import score_transcripts
            texts = self._transcribe(model, processor, val, params, device, dtype)
            gold, guesses = [], []
            for clip, (text, _) in zip(val, texts):
                gold.append([{"index": clip["index"], "text": clip["text"],
                              "asr_text": clip["asr_text"]}])
                guesses.append([{"index": clip["index"], "correction": text}])
            metrics = score_transcripts(gold, guesses)
            score = metrics.get("word_accuracy", 0.0)
            report.metric("val", "wer", metrics.get("wer", 1.0), step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                save()
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, train, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            save()
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        card = {"trainer": self.name, "schema": schema.name, "kind": schema.kind,
                "base_model": params["model_name"], "lora": params["lora"],
                "language": params.get("language"), "label_order": [],
                "max_new_tokens": int(params["max_new_tokens"]),
                "model_version": version, "device": device, "n_train": len(train),
                "bundle_digest": bundle.digest, "selected_epoch": summary["best_epoch"]}
        if params.get("export_ct2"):
            card["ct2"] = self._export_ct2(spec, params, model_dir, report)
        hf.write_card(spec.workdir, card)
        metrics = {"n_train": float(len(train)), "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=[], selected_on="val" if val else "")

    def _export_ct2(self, spec, params, model_dir, report) -> Optional[str]:
        """A CTranslate2 copy of the selected model for faster-whisper, or
        None (logged) when ctranslate2 is missing or the conversion fails."""
        if hf.missing(["ctranslate2"]):
            report.log("info", "ctranslate2 is not installed; no faster-whisper copy written")
            return None
        source = model_dir
        try:
            if params.get("lora"):
                # The converter reads full weights: merge the adapter first.
                from peft import PeftModel
                from transformers import WhisperForConditionalGeneration
                base = WhisperForConditionalGeneration.from_pretrained(params["model_name"])
                merged = PeftModel.from_pretrained(base, model_dir).merge_and_unload()
                source = os.path.join(spec.workdir, "merged")
                merged.save_pretrained(source)
                from transformers import AutoProcessor
                processor = AutoProcessor.from_pretrained(model_dir)
                processor.save_pretrained(source)
                processor.feature_extractor.save_pretrained(source)
            from ctranslate2.converters import TransformersConverter
            out = os.path.join(spec.workdir, "ct2")
            copy = [name for name in ("tokenizer.json", "preprocessor_config.json")
                    if os.path.isfile(os.path.join(source, name))]
            TransformersConverter(source, copy_files=copy).convert(
                out, quantization="int8", force=True)
            report.log("info", "Wrote a faster-whisper copy to ct2/")
            return "ct2"
        except Exception as exc:  # noqa: BLE001 - the model is fitted either way
            report.log("warning", "Could not write the faster-whisper copy: %s" % exc)
            return None

    # ------------------------------------------------------------ predict

    def _transcribe(self, model, processor, clips, params, device, dtype):
        """``(text, mean token probability)`` per clip."""
        import torch
        model.eval()
        out = []
        size = max(1, int(params.get("batch_size", 8)))
        kwargs = {"max_new_tokens": int(params.get("max_new_tokens", 128)),
                  "return_dict_in_generate": True, "output_scores": True}
        if params.get("language"):
            kwargs.update(language=params["language"], task="transcribe")
        for start in range(0, len(clips), size):
            batch = clips[start:start + size]
            with torch.inference_mode():
                generated = model.generate(
                    input_features=self._features(processor, batch, device, dtype), **kwargs)
            texts = processor.batch_decode(generated.sequences, skip_special_tokens=True)
            try:
                scores = model.compute_transition_scores(
                    generated.sequences, generated.scores, normalize_logits=True)
                probabilities = [float(torch.exp(row[torch.isfinite(row)].mean()))
                                 if torch.isfinite(row).any() else None for row in scores]
            except Exception:  # noqa: BLE001
                probabilities = [None] * len(batch)
            out.extend((t.strip(), p) for t, p in zip(texts, probabilities))
        return out

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        card = hf.read_card(artifact_dir)
        params = dict(self.default_params(), language=card.get("language"),
                      max_new_tokens=card.get("max_new_tokens", 128))
        device, dtype, processor, model = self._load(params, spec, report, None,
                                                     artifact_dir, card)
        schema = spec.primary_schema.name
        items = list(items)

        class _Media:
            @staticmethod
            def resolve_media(reference):
                return reference

        for n, item in enumerate(items):
            row = dict(item.data, media=item.media)
            clips = self._clips(_Media, [row], schema, report, targets_only=False)
            report.progress("predict", n + 1, len(items))
            if not clips:
                continue
            entries, confidences = [], []
            for clip, (text, probability) in zip(
                    clips, self._transcribe(model, processor, clips, params, device, dtype)):
                if not text or _same_text(text, clip["asr_text"]):
                    continue
                entry = {"index": clip["index"], "start": clip["start"], "end": clip["end"],
                         "errors": ["asr_error"], "correction": text, "source": "ai"}
                if probability is not None:
                    entry["confidence"] = round(probability, 4)
                    confidences.append(probability)
                entries.append(entry)
            if not entries:
                continue
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=schema, payload=entries,
                confidence=round(min(confidences), 4) if confidences else None)
            if report.should_stop():
                return
