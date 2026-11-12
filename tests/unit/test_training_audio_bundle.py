"""Audio schemes in a training bundle: corrected transcript turns, speaker
turns, and spectrogram boxes rendered as image boxes; scored, and turned
back into the scheme's own answer."""

import json
import os

import pytest

from potato.training import registry, spectrograms
from potato.training.base import BundleRef
from potato.training.dataset import build_bundle
from potato.training.evaluation import HEADLINE, score_split
from tests.unit.test_training_trainers import _context

HAVE = __import__("importlib").util.find_spec
needs_audio = pytest.mark.skipif(not (HAVE("numpy") and HAVE("soundfile")),
                                 reason="numpy/soundfile absent")


def _wav(path, seconds=2.0, rate=16000, tone=None):
    import numpy
    import soundfile
    t = numpy.arange(int(seconds * rate)) / rate
    samples = 0.005 * numpy.random.default_rng(0).standard_normal(len(t))
    for start, end, hz in tone or []:
        inside = (t >= start) & (t < end)
        samples[inside] += 0.5 * numpy.sin(2 * numpy.pi * hz * t[inside])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    soundfile.write(path, samples.astype("float32"), rate)
    return path


# ------------------------------------------------------------ transcripts

TRANSCRIPT = {"annotation_type": "speech_transcript", "name": "st", "description": ""}


def transcript_project(tmp, n=6):
    items, annotations = {}, []
    for i in range(n):
        iid = "t%d" % i
        _wav(str(tmp / "audio" / ("t%d.wav" % i)), seconds=3.0)
        items[iid] = {"id": iid, "audio": "audio/t%d.wav" % i, "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "A", "text": "the bat sat"},
            {"start": 1.0, "end": 2.5, "speaker": "B", "text": "on the mat"}]}
        if i < n - 1:     # the last item nobody has corrected yet
            annotations.append({"instance_id": iid, "user_id": "a", "labels": {"st": {
                "st": json.dumps([{"index": 0, "start": 0.0, "end": 1.0,
                                   "errors": ["asr_error"], "correction": "the cat sat"}])}}})
    return _context(tmp, [TRANSCRIPT], items, annotations)


@needs_audio
def test_transcript_rows_carry_every_turn_and_the_corrected_ones(tmp_path):
    config, context = transcript_project(tmp_path)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["st"],
                                    split_spec={"train": 1.0}, include_unlabeled=True)
    assert bundle.manifest["schemas"][0]["kind"] == "transcript"
    assert bundle.manifest["modality"] == "audio" and not stats.warnings
    row = next(r for r in bundle.read_split("train") if r["instance_id"] == "t0")
    assert row["targets"]["st"] == [{"index": 0, "start": 0.0, "end": 1.0,
                                     "text": "the cat sat", "asr_text": "the bat sat"}]
    assert [t["text"] for t in row["turns"]] == ["the bat sat", "on the mat"]
    assert os.path.isfile(os.path.join(bundle.root, "media", row["media"]))
    # The uncorrected item is predicted on, with its turns and recording.
    (unlabeled,) = bundle.read_split("unlabeled")
    assert unlabeled["instance_id"] == "t5" and len(unlabeled["turns"]) == 2
    assert unlabeled.get("media")


def test_the_audio_trainers_are_offered_by_scheme():
    def names(scheme, modality):
        return sorted(t.name for t in registry.trainers_for_schema(scheme, modality))
    assert names(TRANSCRIPT, "audio") == ["whisper-asr"]
    tiered = {"annotation_type": "tiered_annotation", "name": "t", "tiers": []}
    assert names(tiered, "audio") == ["diarization"]
    audio = {"annotation_type": "audio_annotation", "name": "a", "mode": "label"}
    assert names(audio, "audio") == ["diarization", "hf-audio-tagger"]
    video = {"annotation_type": "video_annotation", "name": "v", "mode": "segment"}
    assert "diarization" not in names(video, "video")
    boxes = {"annotation_type": "spectrogram_annotation", "name": "s", "labels": ["call"]}
    assert names(boxes, "image") == ["torchvision-detect", "ultralytics-detect"]


def test_transcripts_are_scored_by_word_error_rate():
    rows = [{"instance_id": "t0", "targets": {"st": [
        {"index": 0, "text": "the cat sat", "asr_text": "the bat sat"},
        {"index": 1, "text": "on the mat", "asr_text": "on a mat"}]}}]
    fixed = {("t0", "st"): [{"index": 0, "correction": "the cat sat"},
                            {"index": 1, "correction": "on the mat"}]}
    metrics, n = score_split(rows, fixed, "st", "transcript")
    assert n == 1 and metrics[HEADLINE["transcript"]] == 1.0
    assert metrics["wer_asr"] == pytest.approx(2 / 6)
    # No prediction: the turns keep the ASR's text.
    metrics, _ = score_split(rows, {}, "st", "transcript")
    assert metrics["word_accuracy"] == pytest.approx(1 - 2 / 6)


# ------------------------------------------------------------ speakers

def test_speaker_turns_from_a_tiered_scheme(tmp_path):
    scheme = {"annotation_type": "tiered_annotation", "name": "tiers", "description": "",
              "source_field": "audio", "tiers": [{"name": "words"}, {"name": "Speaker"}]}
    answer = {"annotations": {
        "words": [{"start_time": 0, "end_time": 500, "label": "hello"}],
        "Speaker": [{"start_time": 0, "end_time": 1500, "label": "Ana"},
                    {"start_time": 1500, "end_time": 2000, "label": "Ben"}]}}
    items = {"m0": {"id": "m0", "audio": "x.wav"}}
    annotations = [{"instance_id": "m0", "user_id": "a",
                    "labels": {"tiers": {"_data": json.dumps(answer)}}}]
    _, context = _context(tmp_path, [scheme], items, annotations)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["tiers"],
                                split_spec={"train": 1.0}, include_media=False)
    (row,) = bundle.read_split("train")
    # The speaker tier, not the first one, though both carry labels.
    assert row["targets"]["tiers"] == [
        {"start": 0.0, "end": 1.5, "speaker": "Ana", "tier": "Speaker"},
        {"start": 1.5, "end": 2.0, "speaker": "Ben", "tier": "Speaker"}]
    assert bundle.manifest["labels"]["tiers"] == ["Ana", "Ben"]


def test_speaker_turns_are_scored_by_der_whatever_the_names():
    rows = [{"instance_id": "m0", "targets": {"s": [
        {"start": 0.0, "end": 2.0, "speaker": "Ana"}, {"start": 2.0, "end": 4.0, "speaker": "Ben"}]}}]
    renamed = {("m0", "s"): {"segments": [
        {"start_time": 0.0, "end_time": 2.0, "label": "SPEAKER_01"},
        {"start_time": 2.0, "end_time": 4.0, "label": "SPEAKER_00"}]}}
    metrics, _ = score_split(rows, renamed, "s", "segments")
    assert metrics[HEADLINE["segments"]] == 1.0 and metrics["der"] == 0.0
    merged = {("m0", "s"): {"segments": [{"start_time": 0.0, "end_time": 4.0, "label": "x"}]}}
    metrics, _ = score_split(rows, merged, "s", "segments")
    assert metrics["der"] == pytest.approx(0.5)


# ------------------------------------------------------------ spectrograms

BOXES = {"annotation_type": "spectrogram_annotation", "name": "calls", "description": "",
         "labels": ["call"], "source_field": "audio", "max_freq": 6000, "fft_size": 512}


def spectrogram_project(tmp, n=4, seconds=6.0):
    items, annotations = {}, []
    for i in range(n):
        iid = "s%d" % i
        start = 1.0 + i * 0.5
        _wav(str(tmp / "audio" / ("s%d.wav" % i)), seconds=seconds,
             tone=[(start, start + 1.0, 3000)])
        items[iid] = {"id": iid, "audio": "audio/s%d.wav" % i}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {"calls": {
            "_data": json.dumps([{"start_s": start, "end_s": start + 1.0, "low_hz": 2800,
                                  "high_hz": 3200, "label": "call"},
                                 {"start_s": 0.1, "end_s": 0.5, "low_hz": None,
                                  "high_hz": None, "label": "call"}])}}})
    return _context(tmp, [BOXES], items, annotations)


@needs_audio
def test_spectrogram_rows_are_images_with_image_boxes(tmp_path):
    config, context = spectrogram_project(tmp_path)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["calls"],
                                    split_spec={"train": 1.0})
    assert bundle.manifest["schemas"][0]["kind"] == "acoustic"
    assert bundle.manifest["modality"] == "image" and not stats.warnings
    row = next(r for r in bundle.read_split("train") if r["instance_id"] == "s0")
    assert row["media"].startswith("spectrograms/") and row["media"].endswith(".png")
    assert os.path.isfile(os.path.join(bundle.root, "media", row["media"]))
    assert row["spectrogram"]["max_hz"] == 6000 and row["spectrogram"]["width"] == 600
    tone, band = row["targets"]["calls"]
    assert tone["coordinates"] == pytest.approx(
        {"x": 1 / 6, "y": (6000 - 3200) / 6000, "width": 1 / 6, "height": 400 / 6000})
    # A time-only box spans the whole band.
    assert band["coordinates"]["y"] == 0.0 and band["coordinates"]["height"] == 1.0
    # The recordings themselves are not in the bundle; the images stand in.
    assert not os.path.exists(os.path.join(bundle.root, "media", "audio"))
    assert bundle.manifest["labels"]["calls"] == ["call"]


@needs_audio
def test_spectrogram_predictions_go_back_to_seconds_and_hertz(tmp_path):
    config, context = spectrogram_project(tmp_path, n=2)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["calls"],
                                split_spec={"train": 1.0})
    row = next(r for r in bundle.read_split("train") if r["instance_id"] == "s0")
    path = str(tmp_path / "predictions.jsonl")
    with open(path, "w") as fh:
        fh.write(json.dumps({"instance_id": "s0", "schema_name": "calls", "confidence": 0.9,
                             "payload": [dict(row["targets"]["calls"][0], confidence=0.9)]}) + "\n")
        fh.write(json.dumps({"instance_id": "s1", "schema_name": "calls",
                             "payload": [{"type": "polygon", "coordinates": []}]}) + "\n")
    assert spectrograms.finalize_file(bundle, path, "m1") == 1
    (record,) = [json.loads(line) for line in open(path)]
    assert record["payload"] == [{"start_s": 1.0, "end_s": 2.0, "low_hz": 2800.0,
                                  "high_hz": 3200.0, "label": "call", "source": "ai",
                                  "ai_model": "m1", "confidence": 0.9}]


@needs_audio
def test_a_long_recording_is_tiled_and_its_boxes_mapped_from_the_whole(tmp_path):
    config, context = spectrogram_project(tmp_path, n=2, seconds=20.0)
    config["model_training"] = {"tiling": {"enabled": True, "tile_size": 512, "overlap": 64}}
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["calls"],
                                split_spec={"train": 1.0})
    assert bundle.manifest.get("tiling")
    tiles = [r for r in bundle.read_split("train") if r.get("parent_id") == "s0"]
    # Windows 512 wide on a 2000 x 256 image: the ones with a call, plus a
    # share of background windows.
    assert tiles and all(r["tile"]["h"] == 256 and r["tile"]["w"] == 512 for r in tiles)
    assert any(r["targets"]["calls"] for r in tiles)
    from potato.training.tiling import scoring_rows
    (parent,) = [r for r in scoring_rows(bundle, "train") if r["instance_id"] == "s0"]
    path = str(tmp_path / "p.jsonl")
    with open(path, "w") as fh:
        fh.write(json.dumps({"instance_id": "s0", "schema_name": "calls",
                             "payload": parent["targets"]["calls"][:1]}) + "\n")
    spectrograms.finalize_file(bundle, path)
    (record,) = [json.loads(line) for line in open(path)]
    assert record["payload"][0]["start_s"] == pytest.approx(1.0, abs=0.01)
    assert record["payload"][0]["end_s"] == pytest.approx(2.0, abs=0.01)


def test_finalize_leaves_a_bundle_without_spectrograms_alone(tmp_path):
    os.makedirs(tmp_path / "b")
    (tmp_path / "b" / "train.jsonl").write_text(json.dumps({"instance_id": "x"}) + "\n")
    bundle = BundleRef(root=str(tmp_path / "b"), manifest={
        "splits": {"train": {"path": "train.jsonl"}}})
    path = tmp_path / "p.jsonl"
    path.write_text('{"instance_id": "x", "payload": [{"type": "bbox"}]}\n')
    assert spectrograms.finalize_file(bundle, str(path)) == 0
    assert path.read_text() == '{"instance_id": "x", "payload": [{"type": "bbox"}]}\n'


# ------------------------------------------------------------ prelabels

def test_transcript_corrections_as_prelabels():
    from potato.server_utils.prelabel_values import prelabel_values
    scheme = dict(TRANSCRIPT, error_types=["asr_error", "disfluency"])
    item = {"segments": [{"start": 0.0, "end": 1.0, "text": "the bat sat"},
                         {"start": 1.0, "end": 2.0, "text": "on the mat"}]}
    payload = [{"index": 0, "start": 9, "end": 9, "errors": ["asr_error", "made_up"],
                "correction": " the cat sat ", "source": "ai", "confidence": 0.7},
               {"index": 5, "correction": "past the end"},
               {"index": 1, "correction": "   "},
               {"index": "x", "correction": "bad index"}]
    (value,) = prelabel_values(scheme, payload, item).values()
    # The item's times, the scheme's error types, and the shape the widget saves.
    assert json.loads(value) == [{"index": 0, "start": 0.0, "end": 1.0,
                                  "errors": ["asr_error"], "correction": "the cat sat"}]
    assert prelabel_values(scheme, [{"index": 5, "correction": "x"}], item) is None


def test_transcript_prelabels_take_each_turn_once_with_the_widgets_pills():
    """Audit 103: errors listed twice made a pill that could not be cleared,
    1.7 and True were read as turn 1, and error_types: [] fell back to the
    defaults the page does not show."""
    from potato.server_utils.prelabel_values import prelabel_values
    item = {"segments": [{"start": 0.0, "end": 1.0, "text": "a"},
                         {"start": 1.0, "end": 2.0, "text": "b"}]}
    payload = [{"index": 0, "errors": ["asr_error", "asr_error"], "correction": "x"},
               {"index": 0, "errors": [], "correction": "again"},
               {"index": 1.7, "correction": "y"}, {"index": True, "correction": "z"},
               {"index": 1.0, "errors": ["disfluency"], "correction": "w"}]
    (value,) = prelabel_values(TRANSCRIPT, payload, item).values()
    assert [(e["index"], e["errors"], e["correction"]) for e in json.loads(value)] == [
        (0, ["asr_error"], "x"), (1, ["disfluency"], "w")]
    none_offered = dict(TRANSCRIPT, error_types=[])
    (value,) = prelabel_values(none_offered, payload, item).values()
    assert all(e["errors"] == [] for e in json.loads(value))


def test_transcript_turns_are_the_pages_turns(tmp_path):
    """Audit 103: the turns were read without the scheme's keys or the task
    directory, so a transcript file the item names was one turn of its path,
    and a text_key other than "text" gave every turn empty ASR text."""
    from potato.training.audio import transcript_turns
    os.makedirs(tmp_path / "side")
    (tmp_path / "side" / "t.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nthe bat sat\n\n"
        "2\n00:00:01,000 --> 00:00:02,500\non the mat\n")
    turns = transcript_turns(TRANSCRIPT, {"segments": "side/t.srt"}, str(tmp_path))["turns"]
    assert [(t["start"], t["end"], t["text"]) for t in turns] == [
        (0.0, 1.0, "the bat sat"), (1.0, 2.5, "on the mat")]
    words = dict(TRANSCRIPT, text_key="words", speaker_key="who")
    turns = transcript_turns(words, {"segments": [
        {"start": 0, "end": 1, "who": "A", "words": "hello there"}]})["turns"]
    assert turns[0]["text"] == "hello there" and turns[0]["speaker"] == "A"


def test_audit_103_follow_ups():
    from potato.server_utils.prelabel_values import prelabel_values
    from potato.training import audio
    # N1: nothing labelled says so.
    problems = []
    assert audio.speaker_turns({"_data": json.dumps({"annotations": {"speaker": []}})},
                               problems=problems) is None
    assert problems == ["the 'speaker' tier has no labelled turn"]
    problems = []
    audio.speaker_turns({"_data": json.dumps({"annotations": {}})}, problems=problems)
    assert problems == ["no tier has a labelled turn"]
    # N3: an unreadable transcript file's stand-in turn is no turn to correct.
    unread = {"segments": "side/missing.srt"}
    assert prelabel_values(TRANSCRIPT, [{"index": 0, "correction": "x"}], unread) is None
    # R1: turns without times are turns; the widget shows them.
    untimed = {"segments": [{"speaker": "A", "text": "hi"}, {"speaker": "B", "text": "yo"}]}
    (value,) = prelabel_values(TRANSCRIPT, [{"index": 0, "correction": "hey"},
                                            {"index": "1", "correction": "you"}],
                               untimed).values()
    assert [(e["index"], e["correction"]) for e in json.loads(value)] == [(0, "hey"), (1, "you")]
    # And with no item to check against, a prediction without times is kept.
    (value,) = prelabel_values(TRANSCRIPT, [{"index": 0, "correction": "hey"}]).values()
    assert json.loads(value)[0]["correction"] == "hey"
    # R2: a transcript written inline as one line is a turn, not a path.
    inline = {"segments": "hello wrold this is one turn"}
    (value,) = prelabel_values(TRANSCRIPT, [{"index": 0, "correction": "hello world"}],
                               inline).values()
    assert json.loads(value)[0]["correction"] == "hello world"
    # N5: "²" is a digit but no index.
    assert prelabel_values(TRANSCRIPT, [{"index": "²", "correction": "y"}], untimed) is None


def test_the_language_sample_spreads_over_every_turn():
    """N2: with 17 to 31 turns the stride was 1 and the sample the first 16."""
    import types
    from potato.training.trainers.whisper_asr import WhisperASRTrainer
    torch = pytest.importorskip("torch")
    seen = []

    class Features:
        def __init__(self, audio):
            seen.extend(a[0] for a in audio)
            self.input_features = torch.zeros(len(audio), 1, 1)

    processor = types.SimpleNamespace(feature_extractor=lambda audio, **kw: Features(audio),
                                      tokenizer=types.SimpleNamespace(set_prefix_tokens=lambda **kw: None))
    model = types.SimpleNamespace(
        generation_config=types.SimpleNamespace(is_multilingual=True, lang_to_id={"<|en|>": 1}),
        detect_language=lambda f: torch.ones(f.shape[0], dtype=torch.long))
    clips = [{"audio": [float(i)]} for i in range(20)]
    WhisperASRTrainer()._settle_language(model, processor, clips, {"language": None}, "cpu",
                                         torch.float32, types.SimpleNamespace(log=lambda *a: None))
    assert len(seen) == 16 and max(seen) >= 18
