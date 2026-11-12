"""
Unit tests for sidecar transcript loading.

The interesting behavior is the path-vs-content decision: a field value can be
either a path to a transcript file or the transcript itself, and getting that
wrong in either direction is bad — reading a file that was meant as content, or
displaying a path as if it were a one-line transcript.

Also covers the security boundary, since sidecar paths come from data files and
must not be able to reach outside the task directory.
"""

import json
import os

import pytest

from potato.server_utils.transcripts import (
    is_transcript_path,
    normalize_transcript,
    read_transcript_file,
    resolve_transcript_source,
)

SRT = """1
00:00:00,000 --> 00:00:02,400
Alice: Good morning.

2
00:00:02,400 --> 00:00:05,000
Bob: Morning!
"""

VTT = """WEBVTT

00:00:00.000 --> 00:00:02.400
<v Alice>Good morning.
"""


@pytest.fixture
def task_dir(tmp_path):
    """A task directory with a media subfolder of sidecar transcripts."""
    media = tmp_path / "media"
    media.mkdir()
    (media / "int_001.srt").write_text(SRT, encoding="utf-8")
    (media / "int_002.vtt").write_text(VTT, encoding="utf-8")
    (media / "int_003.json").write_text(
        json.dumps({"segments": [{"start": 0, "end": 1.5, "text": "From JSON"}]}),
        encoding="utf-8",
    )
    # A file outside the task dir that a malicious data row might try to read.
    (tmp_path.parent / "secrets.srt").write_text("top secret", encoding="utf-8")
    return str(tmp_path)


class TestIsTranscriptPath:
    @pytest.mark.parametrize("value", [
        "media/int_001.srt",
        "int_001.vtt",
        "./captions/talk.json3",
        "data/sources/session.TextGrid",
        "out.eaf",
    ])
    def test_recognizes_paths(self, value):
        assert is_transcript_path(value) is True

    @pytest.mark.parametrize("value", [
        SRT,                       # actual content, multi-line
        "Just a sentence someone said.",
        "",
        "   ",
        "https://example.org/captions.srt",   # a URL is not a local sidecar
        "media/audio.mp3",                    # not a transcript extension
        123,
        None,
        ["media/x.srt"],
    ])
    def test_rejects_non_paths(self, value):
        assert is_transcript_path(value) is False

    def test_rejects_overlong_string(self):
        # Content that happens to be one line but is far too long to be a path.
        assert is_transcript_path("word " * 200 + ".srt") is False

    def test_single_line_content_ending_in_extension_is_edge_case(self):
        # Documented behavior: this *is* treated as a path. It is why the
        # "false" override exists.
        assert is_transcript_path("hello.txt") is True


class TestReadTranscriptFile:
    def test_reads_relative_path(self, task_dir):
        content = read_transcript_file("media/int_001.srt", task_dir)
        assert "Good morning." in content

    def test_missing_file_returns_none(self, task_dir):
        assert read_transcript_file("media/nope.srt", task_dir) is None

    def test_traversal_is_refused(self, task_dir):
        # The file exists and is readable; only the security check stops it.
        assert read_transcript_file("../secrets.srt", task_dir) is None

    def test_absolute_path_outside_task_dir_refused(self, task_dir):
        outside = os.path.join(os.path.dirname(task_dir), "secrets.srt")
        assert read_transcript_file(outside, task_dir) is None

    def test_strips_bom(self, tmp_path):
        (tmp_path / "bom.srt").write_text("﻿" + SRT, encoding="utf-8")
        content = read_transcript_file("bom.srt", str(tmp_path))
        assert content.startswith("1")


class TestResolveTranscriptSource:
    def test_reads_when_path(self, task_dir):
        out = resolve_transcript_source("media/int_001.srt", task_dir)
        assert "Good morning." in out

    def test_passes_content_through(self, task_dir):
        assert resolve_transcript_source(SRT, task_dir) == SRT

    def test_no_base_dir_disables_loading(self):
        assert resolve_transcript_source("media/int_001.srt", None) == "media/int_001.srt"

    def test_is_path_false_disables_loading(self, task_dir):
        out = resolve_transcript_source("media/int_001.srt", task_dir, is_path="false")
        assert out == "media/int_001.srt"

    def test_is_path_true_forces_loading(self, task_dir):
        # Force a read for a name the heuristic would not accept on its own.
        (os.path.join(task_dir, "media"))
        out = resolve_transcript_source("media/int_001.srt", task_dir, is_path="true")
        assert "Good morning." in out

    def test_unreadable_path_degrades_to_original(self, task_dir):
        # A typo must not raise — the instance renders with no turns instead.
        assert resolve_transcript_source("media/typo.srt", task_dir) == "media/typo.srt"

    def test_non_string_untouched(self, task_dir):
        payload = {"turns": [{"text": "hi"}]}
        assert resolve_transcript_source(payload, task_dir) is payload


class TestNormalizeWithSidecars:
    def test_top_level_path(self, task_dir):
        out = normalize_transcript("media/int_001.srt", base_dir=task_dir)
        assert [t["speaker"] for t in out["turns"]] == ["Alice", "Bob"]

    def test_nested_transcript_path_with_audio(self, task_dir):
        # The common layout: media URL plus a transcript file beside it.
        raw = {"audio": "media/int_001.mp3", "transcript": "media/int_001.srt"}
        out = normalize_transcript(raw, base_dir=task_dir)
        assert out["audio"] == "media/int_001.mp3"
        assert len(out["turns"]) == 2
        assert out["turns"][0]["text"] == "Good morning."

    def test_vtt_sidecar(self, task_dir):
        out = normalize_transcript(
            {"transcript": "media/int_002.vtt"}, base_dir=task_dir
        )
        assert out["turns"][0]["speaker"] == "Alice"

    def test_json_sidecar(self, task_dir):
        out = normalize_transcript(
            {"transcript": "media/int_003.json"}, base_dir=task_dir
        )
        assert out["turns"][0]["text"] == "From JSON"

    def test_without_base_dir_path_renders_as_text(self, task_dir):
        # No base_dir means no file access at all; the path is just a string.
        out = normalize_transcript("media/int_001.srt")
        assert len(out["turns"]) == 1
        assert out["turns"][0]["text"] == "media/int_001.srt"

    def test_traversal_via_data_file_is_refused(self, task_dir):
        out = normalize_transcript("../secrets.srt", base_dir=task_dir)
        # Falls back to treating the unreadable path as plain text — the secret
        # file's contents never appear.
        assert "top secret" not in out["turns"][0]["text"]

    def test_inline_content_still_wins(self, task_dir):
        out = normalize_transcript(SRT, base_dir=task_dir)
        assert len(out["turns"]) == 2
