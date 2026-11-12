"""whisper-asr, diarization and a detector on spectrograms, run through the
worker on tiny models built here (nothing is downloaded)."""

import json
import os

import pytest

from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from tests.unit.test_training_trainers import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec
needs_torch = pytest.mark.skipif(
    not all(HAVE(m) for m in ("torch", "transformers", "soundfile", "scipy")),
    reason="torch/transformers/soundfile/scipy absent")

WORDS = ("alpha", "bravo", "charlie")


def whisper_project(tmp, n=30):
    from tests.helpers.tiny_hf import spoken_recordings
    recordings = spoken_recordings(str(tmp / "audio"), n, WORDS)
    items, annotations = {}, []
    for i, (path, turns) in enumerate(recordings):
        iid = "w%02d" % i
        # The ASR got every turn wrong: it heard "delta".
        items[iid] = {"id": iid, "audio": os.path.relpath(path, tmp), "segments": [
            {"start": t["start"], "end": t["end"], "speaker": "A", "text": "delta"}
            for t in turns]}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {"st": {"st": json.dumps(
            [{"index": k, "start": t["start"], "end": t["end"], "errors": ["asr_error"],
              "correction": t["text"]} for k, t in enumerate(turns)])}}})
    scheme = {"annotation_type": "speech_transcript", "name": "st", "description": ""}
    return _context(tmp, [scheme], items, annotations)


@needs_torch
def test_whisper_learns_the_corrections_and_suggests_them(tmp_path):
    from tests.helpers.tiny_hf import tiny_whisper
    model = tiny_whisper(str(tmp_path / "whisper"), list(WORDS) + ["delta"])
    config, context = whisper_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["st"], split_seed=1)
    spec = _spec(tmp_path, config, bundle, "whisper-asr", "st",
                 {"model_name": model, "epochs": 30, "batch_size": 4, "learning_rate": 3e-3,
                  "patience": 30, "min_instances": 4, "max_new_tokens": 8,
                  "export_ct2": False})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith("word_accuracy")
    # The ASR's "delta" is wrong on every turn; the model does better.
    split = metrics["heldout_metric"].split()[0]
    assert metrics["%s_wer_asr" % split] == 1.0
    assert metrics["heldout_score"] > 0.6, metrics
    # No language given, and the model is multilingual: detected once and
    # used for both the labels and generation, or the two prefixes differ.
    assert any("Detected language 'en'" in e.get("msg", "") for e in report.of_type("log"))
    records = _predictions(spec)
    assert records
    entry = records[0]["payload"][0]
    assert set(entry) >= {"index", "start", "end", "errors", "correction", "source"}
    assert entry["errors"] == ["asr_error"] and entry["source"] == "ai"
    assert entry["correction"] in WORDS


def speaker_project(tmp, n=16, tiered=False):
    from tests.helpers.tiny_hf import speaker_recordings
    recordings = speaker_recordings(str(tmp / "audio"), n)
    items, annotations = {}, []
    for i, (path, turns) in enumerate(recordings):
        iid = "m%02d" % i
        items[iid] = {"id": iid, "audio": os.path.relpath(path, tmp)}
        if tiered:
            answer = {"annotations": {"speaker": [
                {"start_time": t["start"] * 1000, "end_time": t["end"] * 1000,
                 "label": t["speaker"]} for t in turns]}}
        else:
            answer = {"segments": [{"start_time": t["start"], "end_time": t["end"],
                                    "label": t["speaker"]} for t in turns]}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"who": {"_data": json.dumps(answer)}}})
    if tiered:
        scheme = {"annotation_type": "tiered_annotation", "name": "who", "description": "",
                  "source_field": "audio", "tiers": [{"name": "speaker"}]}
    else:
        scheme = {"annotation_type": "audio_annotation", "name": "who", "description": "",
                  "mode": "label", "labels": ["A", "B"], "source_field": "audio"}
    return _context(tmp, [scheme], items, annotations)


@needs_torch
@pytest.mark.parametrize("tiered", [False, True])
def test_diarization_is_scored_by_der_and_answers_in_the_schemes_shape(tmp_path, tiered):
    from tests.helpers.tiny_hf import tiny_wav2vec2
    encoder = tiny_wav2vec2(str(tmp_path / "enc"))
    config, context = speaker_project(tmp_path, tiered=tiered)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["who"], split_seed=2)
    spec = _spec(tmp_path, config, bundle, "diarization", "who",
                 {"model_name": encoder, "epochs": 30, "batch_size": 4, "chunk_s": 3.0,
                  "max_speakers": 2, "min_instances": 2, "learning_rate": 2e-3})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    # An audio scheme's labels are speakers here: scored as a diarization.
    assert metrics["heldout_metric"].endswith("diarization_accuracy")
    split = metrics["heldout_metric"].split()[0]
    assert "%s_der" % split in metrics and "%s_f1" % split not in metrics
    # The speakers swap names from one file to the next; a model of names
    # would be wrong half the time.
    assert metrics["heldout_score"] > 0.7, metrics
    records = _predictions(spec)
    for record in records:
        payload = record["payload"]
        if tiered:
            turns = payload["annotations"]["speaker"]
            assert all(t["end_time"] > t["start_time"] for t in turns)
        else:
            assert all(s["end_time"] > s["start_time"] and s["source"] == "ai"
                       for s in payload["segments"])


@needs_torch
@pytest.mark.skipif(not HAVE("torchvision"), reason="torchvision absent")
def test_a_detector_on_spectrograms_writes_boxes_in_seconds_and_hertz(tmp_path):
    from tests.unit.test_training_audio_bundle import spectrogram_project
    config, context = spectrogram_project(tmp_path, n=8)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["calls"], split_seed=1)
    spec = _spec(tmp_path, config, bundle, "torchvision-detect", "calls",
                 {"pretrained": False, "epochs": 1, "min_size": 64, "batch_size": 4,
                  "min_instances": 2, "score_threshold": 0.0, "max_detections": 3})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_metric"].endswith("map_50")
    records = _predictions(spec)
    assert records
    for box in records[0]["payload"]:
        assert set(box) >= {"start_s", "end_s", "low_hz", "high_hz", "label", "source"}
        assert 0 <= box["start_s"] <= box["end_s"] <= 6.0
        assert 0 <= box["low_hz"] <= box["high_hz"] <= 6000


@needs_torch
@pytest.mark.skipif(not (HAVE("ctranslate2") and HAVE("faster_whisper")),
                    reason="ctranslate2/faster-whisper absent")
def test_the_faster_whisper_copy_loads_and_transcribes(tmp_path):
    """transformers 5 saves the feature extractor as processor_config.json;
    the converter wanted preprocessor_config.json, and on burger the copy
    was never written."""
    from faster_whisper import WhisperModel
    from tests.helpers.tiny_hf import tiny_whisper
    model = tiny_whisper(str(tmp_path / "whisper"), list(WORDS) + ["delta"])
    config, context = whisper_project(tmp_path, n=8)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["st"], split_seed=1)
    spec = _spec(tmp_path, config, bundle, "whisper-asr", "st",
                 {"model_name": model, "epochs": 1, "batch_size": 4, "min_instances": 2,
                  "max_new_tokens": 4})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert not [e for e in report.of_type("log") if "faster-whisper copy" in e.get("msg", "")
                and e.get("level") == "warning"]
    ct2 = os.path.join(spec.workdir, "ct2")
    assert os.path.isfile(os.path.join(ct2, "model.bin"))
    assert os.path.isfile(os.path.join(ct2, "preprocessor_config.json"))
    path = next(p for p, _ in __import__("tests.helpers.tiny_hf", fromlist=["x"]).spoken_recordings(
        str(tmp_path / "more"), 1, WORDS))
    segments, _ = WhisperModel(ct2, device="cpu").transcribe(path, without_timestamps=True)
    list(segments)      # transcribes without error; a 1-epoch model says anything


@needs_torch
def test_whisper_detects_the_language_on_the_device_it_trains_on(tmp_path):
    """On burger the language was detected before the model moved to the GPU,
    and the first run without a language failed with a device mismatch. A
    CPU run cannot show it; Metal can."""
    import torch
    if not torch.backends.mps.is_available():
        pytest.skip("needs a second device (Apple Metal)")
    from potato.training.base import ResourceLimits
    from tests.helpers.tiny_hf import tiny_whisper
    model = tiny_whisper(str(tmp_path / "whisper"), list(WORDS) + ["delta"])
    config, context = whisper_project(tmp_path, n=8)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["st"], split_seed=1)
    spec = _spec(tmp_path, config, bundle, "whisper-asr", "st",
                 {"model_name": model, "epochs": 1, "batch_size": 4, "min_instances": 2,
                  "max_new_tokens": 4, "export_ct2": False})
    spec = spec.__class__(**dict(spec.__dict__, limits=ResourceLimits(device="mps")))
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert any("Detected language" in e.get("msg", "") for e in report.of_type("log"))


@needs_torch
def test_mixed_languages_are_warned_about_not_settled_quietly():
    """Audit 103: 7 en, 5 fr and 4 de turns trained as en at info level."""
    import types
    import torch
    from potato.training.trainers.whisper_asr import WhisperASRTrainer
    ids = {"<|en|>": 1, "<|fr|>": 2, "<|de|>": 3}
    detected = [1] * 7 + [2] * 5 + [3] * 4

    class Features:
        def __init__(self, n):
            self.input_features = torch.zeros(n, 1, 1)

    prefixes = {}
    processor = types.SimpleNamespace(
        feature_extractor=lambda audio, **kw: Features(len(audio)),
        tokenizer=types.SimpleNamespace(set_prefix_tokens=lambda **kw: prefixes.update(kw)))
    model = types.SimpleNamespace(
        generation_config=types.SimpleNamespace(is_multilingual=True, lang_to_id=ids),
        detect_language=lambda features: torch.tensor(detected[:features.shape[0]]))
    logs = []
    report = types.SimpleNamespace(log=lambda level, msg: logs.append((level, msg)))
    params = {"language": None}
    clips = [{"audio": [0.0]} for _ in range(16)]
    WhisperASRTrainer()._settle_language(model, processor, clips, params, "cpu",
                                         torch.float32, report)
    assert params["language"] == "en" and prefixes["language"] == "en"
    (level, msg), = logs
    assert level == "warning" and "en 7, fr 5, de 4" in msg


def test_a_kernel_failure_without_nvrtc_in_it_keeps_its_text():
    import types
    from unittest.mock import patch
    from potato.training.trainers import _hf_common as hf
    torch = pytest.importorskip("torch")
    spec = types.SimpleNamespace(limits=types.SimpleNamespace(device="auto"))
    with patch.object(torch.cuda, "is_available", return_value=True), \
            patch.object(torch, "ones", side_effect=RuntimeError("CUDA error: no kernel image")):
        (problem,) = hf.jit_kernel_problems(spec)
    assert "RuntimeError: CUDA error: no kernel image" in problem
    # Not an NVRTC failure: no NVRTC advice, and no "CUDA None".
    assert "NVRTC" not in problem and "None" not in problem
