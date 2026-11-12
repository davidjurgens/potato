"""
Unit tests for ``potato transcripts``.

The command's job is turning a folder of transcript files into a Potato data
file, so the behavior worth pinning down is discovery (which files get picked
up), id derivation (which has a real trap in Whisper's ``name.mp3.json``
convention), media pairing, and the failure reporting that ``--dry-run`` exists
to provide.
"""

import json
import os

import pytest

from potato.transcript_cli import (
    collect_inputs,
    convert_file,
    find_media,
    item_id_for,
    main,
)

SRT = """1
00:00:00,000 --> 00:00:02,400
Alice: Good morning.

2
00:00:02,400 --> 00:00:05,000
Bob: Morning!
"""

VTT = """WEBVTT

00:00:00.000 --> 00:00:03.000
Just one cue.
"""

WHISPER = {
    "text": "Hello world.",
    "segments": [
        {"id": 0, "start": 0.0, "end": 2.4, "text": " Hello world."},
        {"id": 1, "start": 2.4, "end": 4.0, "text": " Second bit."},
    ],
}


@pytest.fixture
def workspace(tmp_path):
    """A folder of transcripts plus a parallel folder of media."""
    src = tmp_path / "whisper_out"
    src.mkdir()
    (src / "talk_01.srt").write_text(SRT, encoding="utf-8")
    (src / "talk_02.vtt").write_text(VTT, encoding="utf-8")
    (src / "talk_03.mp3.json").write_text(json.dumps(WHISPER), encoding="utf-8")
    # Noise that must not be swept up when scanning a directory.
    (src / "README.txt").write_text("notes about this run", encoding="utf-8")
    (src / "run.log").write_text("...", encoding="utf-8")

    nested = src / "session_b"
    nested.mkdir()
    (nested / "talk_04.srt").write_text(SRT, encoding="utf-8")

    media = tmp_path / "audio"
    media.mkdir()
    for name in ("talk_01.mp3", "talk_02.wav", "talk_03.mp3"):
        (media / name).write_bytes(b"\x00")

    return tmp_path


class TestCollectInputs:
    def test_scans_directory(self, workspace):
        found = collect_inputs([str(workspace / "whisper_out")])
        names = [os.path.basename(p) for p in found]
        assert names == ["talk_01.srt", "talk_02.vtt", "talk_03.mp3.json"]

    def test_skips_txt_and_unknown_extensions_when_scanning(self, workspace):
        found = collect_inputs([str(workspace / "whisper_out")])
        names = [os.path.basename(p) for p in found]
        assert "README.txt" not in names
        assert "run.log" not in names

    def test_recursive(self, workspace):
        found = collect_inputs([str(workspace / "whisper_out")], recursive=True)
        assert any(p.endswith("talk_04.srt") for p in found)

    def test_non_recursive_excludes_nested(self, workspace):
        found = collect_inputs([str(workspace / "whisper_out")])
        assert not any(p.endswith("talk_04.srt") for p in found)

    def test_glob_pattern(self, workspace):
        found = collect_inputs([str(workspace / "whisper_out" / "*.srt")])
        assert len(found) == 1

    def test_explicit_file_of_any_supported_extension(self, workspace):
        # .txt is skipped when scanning but honored when named directly.
        target = workspace / "whisper_out" / "README.txt"
        assert collect_inputs([str(target)]) == [os.path.normpath(str(target))]

    def test_deduplicates_and_sorts(self, workspace):
        folder = str(workspace / "whisper_out")
        found = collect_inputs([folder, folder + "/*.srt"])
        assert len(found) == len(set(found))
        assert found == sorted(found)


class TestItemId:
    def test_plain_stem(self):
        assert item_id_for("/x/talk_01.srt") == "talk_01"

    def test_strips_whisper_double_extension(self):
        # Whisper writes interview.mp3.json for interview.mp3.
        assert item_id_for("/x/interview_07.mp3.json") == "interview_07"

    def test_leaves_non_media_inner_extension(self):
        assert item_id_for("/x/notes.v2.srt") == "notes.v2"

    def test_prefix(self):
        assert item_id_for("/x/talk_01.srt", prefix="s1_") == "s1_talk_01"


class TestFindMedia:
    def test_pairs_by_basename(self, workspace):
        src = str(workspace / "whisper_out" / "talk_01.srt")
        found = find_media(src, str(workspace / "audio"), None)
        assert found.endswith("talk_01.mp3")

    def test_pairs_non_mp3_extension(self, workspace):
        src = str(workspace / "whisper_out" / "talk_02.vtt")
        found = find_media(src, str(workspace / "audio"), None)
        assert found.endswith("talk_02.wav")

    def test_no_match_returns_none(self, workspace):
        src = str(workspace / "whisper_out" / "talk_99.srt")
        assert find_media(src, str(workspace / "audio"), None) is None

    def test_url_prefix_uses_real_extension_when_dir_given(self, workspace):
        src = str(workspace / "whisper_out" / "talk_02.vtt")
        found = find_media(src, str(workspace / "audio"), "https://cdn.example.org/a/")
        assert found == "https://cdn.example.org/a/talk_02.wav"

    def test_url_prefix_alone_assumes_mp3(self, workspace):
        src = str(workspace / "whisper_out" / "talk_01.srt")
        found = find_media(src, None, "https://cdn.example.org/a")
        assert found == "https://cdn.example.org/a/talk_01.mp3"


class TestConvertFile:
    def test_builds_item(self, workspace):
        src = str(workspace / "whisper_out" / "talk_01.srt")
        item, report = convert_file(src, media_dir=str(workspace / "audio"))
        assert item["id"] == "talk_01"
        assert len(item["conversation"]["turns"]) == 2
        assert item["conversation"]["audio"].endswith("talk_01.mp3")

    def test_report_contents(self, workspace):
        src = str(workspace / "whisper_out" / "talk_01.srt")
        _item, report = convert_file(src)
        assert report["format"] == "SRT"
        assert report["turns"] == 2
        assert report["speakers"] == ["Alice", "Bob"]
        assert report["duration"] == pytest.approx(5.0)

    def test_custom_field(self, workspace):
        src = str(workspace / "whisper_out" / "talk_01.srt")
        item, _report = convert_file(src, field="dialogue")
        assert "dialogue" in item
        assert "conversation" not in item

    def test_undiarized_reports_no_speakers(self, workspace):
        src = str(workspace / "whisper_out" / "talk_02.vtt")
        _item, report = convert_file(src)
        assert report["speakers"] == []

    def test_item_without_media_omits_audio_key(self, workspace):
        src = str(workspace / "whisper_out" / "talk_02.vtt")
        item, _report = convert_file(src)
        assert "audio" not in item["conversation"]

    def test_unparseable_file_is_skipped_with_reason(self, tmp_path):
        empty = tmp_path / "empty.srt"
        empty.write_text("", encoding="utf-8")
        item, report = convert_file(str(empty))
        assert item is None
        assert report["error"] == "no turns parsed"


class TestMain:
    def test_writes_json(self, workspace, capsys):
        out = workspace / "data" / "items.json"
        code = main([
            str(workspace / "whisper_out"),
            "--media-dir", str(workspace / "audio"),
            "-o", str(out),
        ])
        assert code == 0
        items = json.loads(out.read_text())
        assert [i["id"] for i in items] == ["talk_01", "talk_02", "talk_03"]

    def test_writes_jsonl(self, workspace):
        out = workspace / "items.jsonl"
        main([
            str(workspace / "whisper_out"), "-o", str(out), "--format", "jsonl",
        ])
        lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
        assert len(lines) == 3
        assert json.loads(lines[0])["id"] == "talk_01"

    def test_creates_output_directory(self, workspace):
        out = workspace / "deep" / "nested" / "items.json"
        main([str(workspace / "whisper_out"), "-o", str(out)])
        assert out.is_file()

    def test_id_prefix(self, workspace):
        out = workspace / "items.json"
        main([str(workspace / "whisper_out"), "-o", str(out), "--id-prefix", "s1_"])
        items = json.loads(out.read_text())
        assert items[0]["id"] == "s1_talk_01"

    def test_dry_run_writes_nothing(self, workspace, capsys):
        out = workspace / "items.json"
        code = main([str(workspace / "whisper_out"), "-o", str(out), "--dry-run"])
        assert code == 0
        assert not out.exists()
        captured = capsys.readouterr().out
        assert "Dry run" in captured

    def test_dry_run_reports_detected_formats(self, workspace, capsys):
        main([str(workspace / "whisper_out"), "--dry-run"])
        captured = capsys.readouterr().out
        assert "SRT" in captured
        assert "WebVTT" in captured
        assert "Whisper JSON" in captured

    def test_warns_when_media_missing(self, workspace, capsys):
        main([str(workspace / "whisper_out"), "--dry-run"])
        captured = capsys.readouterr().out
        assert "no media" in captured

    def test_output_required_without_dry_run(self, workspace):
        with pytest.raises(SystemExit):
            main([str(workspace / "whisper_out")])

    def test_no_matches_returns_error(self, tmp_path, capsys):
        assert main([str(tmp_path / "nothing" / "*.srt"), "--dry-run"]) == 1

    def test_emit_config(self, workspace, capsys):
        out = workspace / "items.json"
        main([str(workspace / "whisper_out"), "-o", str(out), "--emit-config"])
        captured = capsys.readouterr().out
        assert "type: audio_dialogue" in captured
        assert "id_key: id" in captured
