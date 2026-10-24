"""Raven, Audacity and BirdNET tables: parsing, writing, and the round trip."""

import pytest

from potato.server_utils import acoustic_tables as t

RAVEN = (
    "Selection\tView\tChannel\tBegin Time (s)\tEnd Time (s)\tLow Freq (Hz)\tHigh Freq (Hz)\tSpecies\tNotes\n"
    "1\tWaveform 1\t1\t0.5\t1.1\t0\t0\twhistle\t\n"
    "1\tSpectrogram 1\t1\t0.5\t1.1\t2900\t3100\twhistle\tclear\n"
    "2\tSpectrogram 1\t2\t1.8\t2.4\t5100\t1900\tupsweep\t\n"
)


def test_raven_merges_views_and_reads_the_spectrogram_row():
    boxes = t.parse_raven(RAVEN)
    assert [(b["start_s"], b["end_s"], b["low_hz"], b["high_hz"], b["label"]) for b in boxes] == [
        (0.5, 1.1, 2900.0, 3100.0, "whistle"), (1.8, 2.4, 1900.0, 5100.0, "upsweep")]
    assert boxes[1]["channel"] == 2 and "channel" not in boxes[0]


def test_raven_label_column_can_be_chosen_and_must_exist():
    assert [b["label"] for b in t.parse_raven(RAVEN, label_column="Notes")] == ["clear", ""]
    with pytest.raises(ValueError, match="no column named"):
        t.parse_raven(RAVEN, label_column="Call")


def test_raven_multi_file_table_uses_file_offset():
    text = ("Selection\tView\tChannel\tBegin File\tFile Offset (s)\tBegin Time (s)\tEnd Time (s)\t"
            "Low Freq (Hz)\tHigh Freq (Hz)\tAnnotation\n"
            "1\tSpectrogram 1\t1\trec2.wav\t3.0\t63.0\t64.5\t100\t900\tgrunt\n")
    box = t.parse_raven(text)[0]
    assert (box["file"], box["start_s"], box["end_s"]) == ("rec2.wav", 3.0, 4.5)


def test_raven_round_trip():
    boxes = [{"start_s": 0.25, "end_s": 0.75, "low_hz": 1200.5, "high_hz": 4000.0, "label": "a b"},
             {"start_s": 2.0, "end_s": 2.5, "low_hz": 300.0, "high_hz": 800.0, "label": "c"}]
    back = t.parse_raven(t.write_raven(boxes))
    assert [{k: b[k] for k in t.BOX_KEYS} for b in back] == boxes
    assert t.looks_like_raven(t.write_raven(boxes))


def test_raven_writes_time_only_boxes_over_the_band():
    text = t.write_raven([{"start_s": 1, "end_s": 2, "low_hz": None, "high_hz": None, "label": "x"}],
                         default_high_hz=11025)
    assert t.parse_raven(text)[0]["high_hz"] == 11025.0


AUDACITY = "1.000000\t2.500000\tbird call\n\\\t200.000000\t4000.000000\n3.0\t3.0\tpoint\n"


def test_audacity_spectral_and_time_only_labels():
    boxes = t.parse_audacity(AUDACITY)
    assert boxes[0] == {"start_s": 1.0, "end_s": 2.5, "low_hz": 200.0, "high_hz": 4000.0, "label": "bird call"}
    assert boxes[1]["low_hz"] is None and boxes[1]["start_s"] == boxes[1]["end_s"] == 3.0
    assert t.looks_like_audacity(AUDACITY)
    assert not t.looks_like_audacity(RAVEN)


def test_audacity_round_trip():
    boxes = t.parse_audacity(AUDACITY)
    assert t.parse_audacity(t.write_audacity(boxes)) == boxes


def test_birdnet_csv_and_raven_forms():
    csv_text = ("Start (s),End (s),Scientific name,Common name,Confidence,File\n"
                "0.0,3.0,Turdus migratorius,American Robin,0.82,/data/a.wav\n"
                "3.0,6.0,Cardinalis cardinalis,Northern Cardinal,0.05,/data/a.wav\n")
    assert t.looks_like_birdnet_csv(csv_text) and not t.looks_like_raven(csv_text)
    rows = t.parse_birdnet_csv(csv_text)
    assert rows[0]["label"] == "Turdus migratorius" and rows[0]["confidence"] == 0.82
    assert rows[0]["file"] == "a.wav" and rows[0]["low_hz"] is None
    assert t.parse_birdnet_csv(csv_text, "Common name")[0]["label"] == "American Robin"
    raven = ("Selection\tView\tChannel\tBegin Time (s)\tEnd Time (s)\tLow Freq (Hz)\tHigh Freq (Hz)\t"
             "Common Name\tSpecies Code\tConfidence\n"
             "1\tSpectrogram 1\t1\t0\t3\t150\t15000\tAmerican Robin\tamerob\t0.9\n")
    assert t.looks_like_birdnet_raven(raven)
    assert t.parse_raven(raven, prefer=t.BIRDNET_LABEL_COLUMNS)[0]["label"] == "American Robin"


@pytest.mark.parametrize("name,stem", [
    ("site3_0612.Table.1.selections.txt", "site3_0612"),
    ("rec.BirdNET.selection.table.txt", "rec"),
    ("rec.BirdNET.results.csv", "rec"),
    ("rec.labels.txt", "rec"),
    ("plain.txt", "plain"),
])
def test_recording_stem(name, stem):
    assert t.recording_stem(name) == stem


def test_decode_boxes_reads_the_stored_shapes():
    stored = '[{"start_s": 2, "end_s": 1, "low_hz": 900, "high_hz": 100, "label": "x", "edited": true}]'
    for value in (stored, {"_data": stored}):
        box = t.decode_boxes(value)[0]
        assert (box["start_s"], box["end_s"], box["low_hz"], box["high_hz"]) == (1.0, 2.0, 100.0, 900.0)
        assert box["edited"] is True
    assert t.decode_boxes("") is None and t.decode_boxes("[]") == []
