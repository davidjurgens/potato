"""RTTM in, as speaker turns to correct, and back out through the segments
exporter unchanged."""

import json
import wave
from pathlib import Path

import pytest

from potato.importers.projects.rttm import RTTMImporter, parse_rttm, parse_speaker_map
from potato.importers.projects.writer import write_project
from tests.helpers.test_utils import create_test_directory

RTTM = """SPKR-INFO rec1 1 <NA> <NA> <NA> unknown SPEAKER_00 <NA> <NA>
SPEAKER rec1 1 0.000 2.500 <NA> <NA> SPEAKER_00 <NA> <NA>
SPEAKER rec1 1 2.500 1.250 <NA> <NA> SPEAKER_01 <NA> <NA>
SPEAKER rec1 1 4.000 0.000 <NA> <NA> SPEAKER_01 <NA> <NA>
SPEAKER rec2 1 0.300 1.700 <NA> <NA> SPEAKER_00 <NA> <NA>
SPEAKER rec2 1 1.000 2.000 <NA> <NA> SPEAKER_02 <NA> <NA>
"""


@pytest.fixture
def out():
    return Path(create_test_directory("rttm_import"))


def _wav(path, seconds=5.0, rate=8000):
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(b"\x00\x00" * int(seconds * rate))


def _source(out):
    src = out / "src"
    src.mkdir()
    (src / "meeting.rttm").write_text(RTTM)
    _wav(src / "rec1.wav")
    _wav(src / "rec2.wav")
    return src


def test_lines_and_skips():
    turns, skipped = parse_rttm(RTTM)
    assert len(turns) == 4
    assert turns[0] == {"file": "rec1", "channel": "1", "start": 0.0, "end": 2.5,
                        "speaker": "SPEAKER_00"}
    assert skipped == {"SPKR-INFO lines": 1, "zero-length turns": 1}
    assert parse_speaker_map("SPEAKER_00=Interviewer, SPEAKER_01 = Guest,bad") == {
        "SPEAKER_00": "Interviewer", "SPEAKER_01": "Guest"}


def test_one_item_per_recording_with_its_turns(out):
    src = _source(out)
    importer = RTTMImporter()
    assert importer.detect_path(src)
    result = importer.parse_path(src, {"speaker_map": "SPEAKER_00=Interviewer"})
    assert [i.instance_id for i in result.items] == ["rec1", "rec2"]
    (scheme,) = result.schemes
    assert scheme["annotation_type"] == "audio_annotation"
    assert [l["name"] for l in scheme["labels"]] == ["Interviewer", "SPEAKER_01", "SPEAKER_02"]
    rec2 = result.items[1]
    assert rec2.fields["audio_url"] == "/media/rec2.wav"
    segments = rec2.predictions["speakers"]["segments"]
    # Overlapping speech stays two turns.
    assert [(s["start_time"], s["end_time"], s["label"]) for s in segments] == [
        (0.3, 2.0, "Interviewer"), (1.0, 3.0, "SPEAKER_02")]
    assert result.skipped["zero-length turns"] == 1


def test_tiered_scheme_in_milliseconds(out):
    result = RTTMImporter().parse_path(_source(out), {"rttm_scheme": "tiered"})
    (scheme,) = result.schemes
    assert scheme["tiers"][0]["name"] == "speaker"
    first = result.items[0].predictions["tiers"]["annotations"]["speaker"][0]
    assert (first["start_time"], first["end_time"], first["label"]) == (0.0, 2500.0, "SPEAKER_00")
    with pytest.raises(ValueError):
        RTTMImporter().parse_path(out / "src", {"rttm_scheme": "words"})


def test_missing_audio_is_reported_and_the_id_kept(out):
    src = out / "src"
    src.mkdir()
    (src / "only.rttm").write_text(RTTM)
    result = RTTMImporter().parse_path(src)
    assert all(i.fields["audio_url"] == "" for i in result.items)
    assert any("no audio file named rec1" in w for w in result.warnings)


def test_round_trip_through_the_segments_exporter(out):
    """Import, accept the turns as they are, export: the same RTTM lines."""
    from potato.export.cli import build_export_context
    from potato.export.segments_exporter import SegmentsExporter
    src = _source(out)
    project = out / "project"
    write_project(RTTMImporter().parse_path(src), str(project), source=str(src))
    (data_file,) = (project / "data").glob("*.jsonl")
    data = [json.loads(line) for line in data_file.open() if line.strip()]
    state = {"user_id": "ann", "instance_id_ordering": [d["id"] for d in data],
             "current_instance_index": 0, "instance_id_to_span_to_value": {},
             "instance_id_to_label_to_value": {}}
    for item in data:
        answer = item["predictions"]["speakers"]
        state["instance_id_to_label_to_value"][item["id"]] = [
            [{"schema": "speakers", "name": "_data"}, json.dumps(answer)]]
    user_dir = project / "annotation_output" / "ann"
    user_dir.mkdir(parents=True)
    (user_dir / "user_state.json").write_text(json.dumps(state))
    context = build_export_context(str(project / "config.yaml"))
    result = SegmentsExporter().export(context, str(out / "export"), {})
    assert result.success, result.errors
    written = (out / "export" / "rttm" / "ann.rttm").read_text().splitlines()
    original = [line for line in RTTM.splitlines()
                if line.startswith("SPEAKER") and " 0.000 <NA>" not in line]
    assert sorted(written) == sorted(original)


def test_cli_detects_rttm_and_passes_its_flags(out):
    from potato.importers.cli import main
    src = out / "cli-src"
    src.mkdir()
    (src / "meeting.rttm").write_text(RTTM)
    media = out / "recordings"
    media.mkdir()
    _wav(media / "rec1.wav")
    assert main(["-i", str(src), "-o", str(out / "cli"), "--rttm-scheme", "tiered",
                 "--speaker-map", "SPEAKER_00=Interviewer", "--media-dir", str(media)]) == 0
    config = (out / "cli" / "config.yaml").read_text()
    assert "annotation_type: tiered_annotation" in config and "Interviewer" in config
    assert (out / "cli" / "media" / "rec1.wav").exists()
    assert main(["-f", "rttm", "-i", str(src), "-o", str(out / "cli2")]) == 0
    assert "annotation_type: audio_annotation" in (out / "cli2" / "config.yaml").read_text()


def test_times_names_and_maps_that_cannot_be_turns_are_reported(out):
    """Audit 103: nan and inf durations were written into the data as NaN
    and Infinity, a negative onset was kept, <NA> became a speaker, and a
    speaker map that merged or misnamed speakers said nothing."""
    turns, skipped = parse_rttm("\n".join([
        "SPEAKER r 1 0.5 nan <NA> <NA> A <NA> <NA>",
        "SPEAKER r 1 0.5 inf <NA> <NA> A <NA> <NA>",
        "SPEAKER r 1 -3.0 1.0 <NA> <NA> A <NA> <NA>",
        "SPEAKER r 1 1.0 1.0 <NA> <NA> <NA> <NA> <NA>",
        "SPEAKER r 1 2.0 1.0 <NA> <NA> A <NA> <NA>"]))
    assert [t["start"] for t in turns] == [2.0]
    assert skipped == {"turns with a non-finite onset or duration": 2,
                       "turns with a negative onset": 1, "turns with no speaker name": 1}

    src = out / "maps"
    src.mkdir()
    (src / "a.rttm").write_text("SPEAKER rec 1 0 1 <NA> <NA> A <NA> <NA>\n"
                                "SPEAKER rec 1 0 1 <NA> <NA> A <NA> <NA>\n"
                                "SPEAKER rec 1 1 1 <NA> <NA> Dr Smith <NA> <NA>\n")
    (src / "b").mkdir()
    (src / "b" / "b.rttm").write_text("SPEAKER rec 1 3 1 <NA> <NA> B <NA> <NA>\n")
    _wav(src / "b" / "rec.wav")   # beside the second file only
    result = RTTMImporter().parse_path(src, {"speaker_map": "A=X,B=X,Q=Y,oops"})
    warnings = " | ".join(result.warnings)
    assert "'oops'" in warnings and "Q" in warnings and "A, B all become 'X'" in warnings
    assert "more than RTTM's ten fields" in warnings
    (item,) = result.items
    assert item.fields["audio_url"] == "/media/rec.wav"
    assert item.fields["source_file"] == "a.rttm, b.rttm"
    assert result.skipped["repeated turns"] == 1
    assert len(item.predictions["speakers"]["segments"]) == 3
    assert json.dumps(item.predictions).count("NaN") == 0
