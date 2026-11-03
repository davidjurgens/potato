"""Targets and held-out metrics for transcripts, speaker turns and
spectrogram boxes, against values worked by hand."""

import json
import os

import pytest

from potato.training import audio, audio_metrics, spectrograms


SCHEME = {"annotation_type": "speech_transcript", "name": "st", "segments_key": "segments"}
ITEM = {"audio": "talk.wav", "segments": [
    {"start": 0.0, "end": 2.0, "speaker": "A", "text": "the bat sat"},
    {"start": 2.0, "end": 4.5, "speaker": "B", "text": "on the mat"},
    {"start": 4.5, "end": 4.5, "speaker": "B", "text": "empty"}]}


def test_transcript_targets_are_the_corrected_turns():
    answer = json.dumps([{"index": 0, "errors": ["asr_error"], "correction": "the cat sat"},
                         {"index": 1, "errors": ["speaker_error"], "correction": ""},
                         {"index": 2, "correction": "zero length"}])
    target = audio.transcript_target(SCHEME, {"st": answer}, ITEM)
    # A flag without a correction is not a transcript; a zero-length turn has
    # no audio to learn from.
    assert target == [{"index": 0, "start": 0.0, "end": 2.0, "text": "the cat sat",
                       "asr_text": "the bat sat"}]
    assert audio.transcript_target(SCHEME, {"st": "[]"}, ITEM) is None


def test_speaker_turns_from_a_tiered_answer_in_seconds():
    answer = {"annotations": {"words": [{"start_time": 0, "end_time": 900, "label": ""}],
                              "speaker": [
                                  {"start_time": 1200.0, "end_time": 3400.0, "label": "A"},
                                  {"start_time": 0.0, "end_time": 1200.0, "label": "B"}]}}
    turns = audio.speaker_turns({"_data": json.dumps(answer)})
    assert turns == [{"start": 0.0, "end": 1.2, "speaker": "B", "tier": "speaker"},
                     {"start": 1.2, "end": 3.4, "speaker": "A", "tier": "speaker"}]
    assert audio.speaker_turns({"_data": json.dumps(answer)}, tier="words") is None


def test_acoustic_targets():
    stored = {"_data": json.dumps([
        {"start_s": 2.0, "end_s": 1.0, "low_hz": 900, "high_hz": 300, "label": "call",
         "source": "ai"},
        {"start_s": 3.0, "end_s": 4.0, "low_hz": None, "high_hz": None, "label": "noise"},
        {"start_s": 5.0, "end_s": 6.0, "label": ""}])}
    assert audio.acoustic_target(stored) == [
        {"start_s": 1.0, "end_s": 2.0, "low_hz": 300.0, "high_hz": 900.0, "label": "call"},
        {"start_s": 3.0, "end_s": 4.0, "low_hz": None, "high_hz": None, "label": "noise"}]


def test_word_and_character_error_rates():
    gold = [[{"index": 0, "text": "the cat sat", "asr_text": "the bat sat"},
             {"index": 1, "text": "on the mat", "asr_text": "on the mat"}]]
    # Turn 0 fixed, turn 1 left alone (scored as the ASR text, correct).
    perfect = audio_metrics.score_transcripts(gold, [[{"index": 0, "correction": "The cat, sat"}]])
    assert perfect["wer"] == 0.0 and perfect["word_accuracy"] == 1.0
    assert perfect["wer_asr"] == pytest.approx(1 / 6)
    # "the hat" for "the cat sat": a substitution and a deletion, 2 of 6 words.
    worse = audio_metrics.score_transcripts(gold, [[{"index": 0, "correction": "the hat"}]])
    assert worse["wer"] == pytest.approx(2 / 6)
    assert audio_metrics.edit_distance("kitten", "sitting") == 3


def test_diarization_error_rate():
    reference = [{"start": 0.0, "end": 2.0, "speaker": "A"},
                 {"start": 2.0, "end": 4.0, "speaker": "B"}]
    same = [{"start": 0.0, "end": 2.0, "speaker": "x"}, {"start": 2.0, "end": 4.0, "speaker": "y"}]
    assert audio_metrics.diarization_error(reference, same)[0] == 0.0
    # One speaker for both halves: 2 s of confusion over 4 s of speech.
    assert audio_metrics.diarization_error(
        reference, [{"start": 0.0, "end": 4.0, "speaker": "x"}])[0] == pytest.approx(0.5)
    # Missing the second half and inventing a speaker after the end.
    der, parts = audio_metrics.diarization_error(
        reference, [{"start": 0.0, "end": 2.0, "speaker": "x"},
                    {"start": 5.0, "end": 6.0, "speaker": "z"}])
    assert parts["missed_s"] == pytest.approx(2.0) and parts["false_alarm_s"] == pytest.approx(1.0)
    assert der == pytest.approx(0.75)
    # Audio-annotation and tiered payloads read the same.
    scores = audio_metrics.score_diarization(
        [reference], [{"segments": [{"start_time": 0, "end_time": 4, "label": "x"}]}])
    assert scores["der"] == pytest.approx(0.5) and scores["confusion"] == pytest.approx(0.5)


def test_spectrogram_rendering_puts_a_tone_where_its_box_says(tmp_path):
    numpy = pytest.importorskip("numpy")
    soundfile = pytest.importorskip("soundfile")
    from PIL import Image
    rate = 16000
    t = numpy.arange(rate * 6) / rate
    signal = 0.005 * numpy.random.default_rng(0).standard_normal(len(t))
    tone = (t >= 2) & (t < 3)
    signal[tone] += 0.5 * numpy.sin(2 * numpy.pi * 3000 * t[tone])
    soundfile.write(tmp_path / "a.wav", signal.astype("float32"), rate)
    meta = spectrograms.render(str(tmp_path / "a.wav"), str(tmp_path / "a.png"),
                               {"fft_size": 512, "max_freq": 6000})
    assert meta["width"] == 600 and meta["max_hz"] == 6000 and meta["min_hz"] == 0
    (box,) = spectrograms.boxes_to_objects(
        [{"start_s": 2, "end_s": 3, "low_hz": 2800, "high_hz": 3200, "label": "tone"}], meta)
    image = numpy.asarray(Image.open(tmp_path / "a.png").convert("L"), dtype=float)
    h, w = image.shape
    c = box["coordinates"]
    inside = image[int(c["y"] * h):int((c["y"] + c["height"]) * h) + 1,
                   int(c["x"] * w):int((c["x"] + c["width"]) * w)]
    before = image[int(c["y"] * h):int((c["y"] + c["height"]) * h) + 1, 0:int(c["x"] * w) - 10]
    assert inside.mean() > before.mean() + 50
    back = spectrograms.objects_to_boxes([dict(box, confidence=0.8)], meta, "m1")
    assert back == [{"start_s": 2.0, "end_s": 3.0, "low_hz": 2800.0, "high_hz": 3200.0,
                     "label": "tone", "source": "ai", "ai_model": "m1", "confidence": 0.8}]


def test_a_tiered_prediction_object_reads_as_its_turns():
    """A tiered prediction is the answer object itself, not a stored value
    map; read as a wrapper, its one key was stripped and every tiered
    diarization run scored DER 1."""
    payload = {"annotations": {"speaker": [{"start_time": 0, "end_time": 2000, "label": "x"}]}}
    assert audio.speaker_turns(payload) == [
        {"start": 0.0, "end": 2.0, "speaker": "x", "tier": "speaker"}]
    reference = [{"start": 0.0, "end": 2.0, "speaker": "A"}]
    assert audio_metrics.score_diarization([reference], [payload])["der"] == 0.0


def test_the_speaker_tier_is_never_a_guess():
    def answer(**tiers):
        return {"_data": json.dumps({"annotations": {
            name: [{"start_time": 0, "end_time": 1000, "label": label}] if label else []
            for name, label in tiers.items()}})}
    # Two tiers that both say speaker: no target, and why.
    problems = []
    assert audio.speaker_turns(answer(speaker_a="A", speaker_b="B"), problems=problems) is None
    assert "speaker_a" in problems[0]
    # "Non-speaker" is not a speaker tier; "Speaker" is.
    turns = audio.speaker_turns(answer(**{"Non-speaker": "noise", "Speaker": "Ana"}))
    assert [t["tier"] for t in turns] == ["Speaker"]
    # An empty speaker tier does not fall back to the words.
    assert audio.speaker_turns(answer(words="hello", speaker="")) is None
    # Several labelled tiers and none named: no target.
    problems = []
    assert audio.speaker_turns(answer(words="hello", gloss="hi"), problems=problems) is None
    assert "name the speaker tier" in problems[0]
    # One labelled tier and nothing named: that one.
    assert audio.speaker_turns(answer(who="Ana"))[0]["speaker"] == "Ana"


def test_spectrogram_boxes_are_clipped_to_the_recording():
    meta = {"duration_s": 10.0, "min_hz": 0.0, "max_hz": 8000.0, "width": 1000, "height": 256}
    boxes = spectrograms.boxes_to_objects([
        {"start_s": 9.5, "end_s": 12.0, "low_hz": 1000, "high_hz": 2000, "label": "a"},
        {"start_s": -1.0, "end_s": 1.0, "label": "b"},
        {"start_s": 11.0, "end_s": 12.0, "label": "outside"},
        {"start_s": -3.0, "end_s": -2.0, "label": "before"}], meta)
    assert [b["label"] for b in boxes] == ["a", "b"]
    for box in boxes:
        c = box["coordinates"]
        assert 0 <= c["x"] and c["x"] + c["width"] <= 1 + 1e-9
    assert boxes[0]["coordinates"]["x"] == pytest.approx(0.95)
    assert boxes[0]["coordinates"]["width"] == pytest.approx(0.05)
