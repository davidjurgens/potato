"""Local transcription and diarization.

Neither backend is installed in every environment, so nothing here imports
faster-whisper or sherpa-onnx. The pieces that matter are ours: which files get
picked up, where transcripts are cached, how diarization labels are matched to
transcript segments, and what happens when the optional dependency is absent.
"""

import json
import os

import pytest

from potato.server_utils.transcripts import diarize as diarize_mod
from potato.server_utils.transcripts import transcribe as transcribe_mod
from potato.server_utils.transcripts import normalize_transcript


class TestMediaDetection:
    @pytest.mark.parametrize("name", [
        "a.mp3", "a.WAV", "a.m4a", "a.flac", "a.opus",
        # Video counts: the decoder pulls the audio track out, so there is no
        # reason to make people demux first.
        "a.mp4", "a.webm", "a.mkv", "a.mov",
    ])
    def test_media_is_recognized(self, name):
        assert transcribe_mod.looks_like_media(name)

    @pytest.mark.parametrize("name", ["a.srt", "a.vtt", "a.json", "a.txt", "a"])
    def test_transcripts_are_not_media(self, name):
        assert not transcribe_mod.looks_like_media(name)


class TestCachePaths:
    def test_default_is_beside_the_media(self, tmp_path):
        media = tmp_path / "interview_01.mp3"
        media.write_bytes(b"")
        assert transcribe_mod.cache_path_for(str(media)) == str(
            tmp_path / "interview_01.whisper.json")

    def test_cache_dir_overrides(self, tmp_path):
        media = tmp_path / "audio" / "interview_01.mp3"
        out = transcribe_mod.cache_path_for(str(media), str(tmp_path / "cache"))
        assert out == str(tmp_path / "cache" / "interview_01.whisper.json")

    def test_extension_does_not_leak_into_the_name(self, tmp_path):
        # talk.wav and talk.mp3 would collide, but that is a name clash the
        # user made, not one we introduce by keeping the extension.
        assert transcribe_mod.cache_path_for("/x/talk.wav").endswith(
            "talk.whisper.json")


class TestCacheFilesAreNotScannedAsTranscripts:
    """The duplicate-item trap.

    The cache is written beside the media as ``<name>.whisper.json``, and
    ``.json`` is a transcript extension. Without a filter the second run over a
    folder of audio collects both the mp3 and its own cache, producing two
    items for one recording.
    """

    def test_is_cache_file(self):
        from potato.transcript_cli import is_cache_file

        assert is_cache_file("/x/talk.whisper.json")
        assert is_cache_file("/x/TALK.WHISPER.JSON")
        assert not is_cache_file("/x/talk.json")
        assert not is_cache_file("/x/whisper.json.srt")

    def test_directory_scan_skips_the_cache(self, tmp_path):
        from potato.transcript_cli import collect_inputs

        (tmp_path / "talk.mp3").write_bytes(b"")
        (tmp_path / "talk.whisper.json").write_text("{}")

        found = collect_inputs([str(tmp_path)], include_media=True)
        assert found == [str(tmp_path / "talk.mp3")]

    def test_media_is_ignored_without_include_media(self, tmp_path):
        from potato.transcript_cli import collect_inputs

        (tmp_path / "talk.mp3").write_bytes(b"")
        (tmp_path / "notes.srt").write_text("1\n")

        assert collect_inputs([str(tmp_path)]) == [str(tmp_path / "notes.srt")]


class TestSpeakerAssignment:
    def test_longest_overlap_wins_not_the_start(self):
        """A segment that *starts* inside one turn but mostly sits in the next
        belongs to the next. Whisper's boundaries and the diarizer's are
        produced independently and do not line up."""
        segments = [{"start": 9.0, "end": 14.0, "text": "..."}]
        turns = [
            {"start": 0.0, "end": 10.0, "speaker": "SPEAKER_00"},
            {"start": 10.0, "end": 20.0, "speaker": "SPEAKER_01"},
        ]
        out = diarize_mod.assign_speakers(segments, turns)
        assert out[0]["speaker"] == "SPEAKER_01"

    def test_no_overlap_stays_undiarized(self):
        segments = [{"start": 30.0, "end": 32.0, "text": "..."}]
        turns = [{"start": 0.0, "end": 10.0, "speaker": "SPEAKER_00"}]
        assert diarize_mod.assign_speakers(segments, turns)[0]["speaker"] is None

    def test_empty_diarization_leaves_everything_undiarized(self):
        segments = [{"start": 0.0, "end": 2.0, "text": "hi"}]
        assert diarize_mod.assign_speakers(segments, [])[0]["speaker"] is None

    def test_input_is_not_mutated(self):
        segments = [{"start": 0.0, "end": 2.0, "text": "hi"}]
        diarize_mod.assign_speakers(
            segments, [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}])
        assert "speaker" not in segments[0]

    def test_other_segment_keys_survive(self):
        segments = [{"start": 0.0, "end": 2.0, "text": "hi", "words": [1, 2]}]
        out = diarize_mod.assign_speakers(
            segments, [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}])
        assert out[0]["words"] == [1, 2]
        assert out[0]["text"] == "hi"

    def test_missing_bounds_do_not_crash(self):
        out = diarize_mod.assign_speakers(
            [{"text": "no timings"}],
            [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}])
        assert out[0]["speaker"] is None

    def test_labels_match_the_whisperx_convention(self):
        assert diarize_mod.speaker_label(0) == "SPEAKER_00"
        assert diarize_mod.speaker_label(7) == "SPEAKER_07"
        assert diarize_mod.speaker_label(12) == "SPEAKER_12"


class TestMissingBackend:
    def test_transcription_error_names_the_extra(self, monkeypatch):
        monkeypatch.setattr(transcribe_mod, "is_available", lambda: False)
        with pytest.raises(transcribe_mod.TranscriptionError) as excinfo:
            transcribe_mod.require_backend()
        assert "potato-annotation[transcribe]" in str(excinfo.value)

    def test_diarization_error_names_the_extra(self, monkeypatch):
        monkeypatch.setattr(diarize_mod, "is_available", lambda: False)
        with pytest.raises(diarize_mod.DiarizationError) as excinfo:
            diarize_mod.require_backend()
        assert "potato-annotation[transcribe]" in str(excinfo.value)

    def test_missing_media_file_is_named(self):
        with pytest.raises(transcribe_mod.TranscriptionError) as excinfo:
            transcribe_mod.transcribe_file("/nope/missing.mp3")
        assert "missing.mp3" in str(excinfo.value)

    def test_missing_media_file_is_named_for_diarization(self):
        with pytest.raises(diarize_mod.DiarizationError) as excinfo:
            diarize_mod.diarize_file("/nope/missing.mp3")
        assert "missing.mp3" in str(excinfo.value)


class TestModelResolution:
    def test_explicit_paths_are_never_downloaded(self, tmp_path, monkeypatch):
        """The air-gap contract: staged models must not trigger a fetch."""
        def explode(*args, **kwargs):
            raise AssertionError("downloaded despite explicit model paths")

        monkeypatch.setattr(diarize_mod, "_download", explode)

        seg = tmp_path / "seg.onnx"
        emb = tmp_path / "emb.onnx"
        seg.write_bytes(b"x")
        emb.write_bytes(b"x")

        assert diarize_mod.ensure_models(
            segmentation_model=str(seg), embedding_model=str(emb)
        ) == (str(seg), str(emb))

    def test_missing_explicit_model_is_reported_not_downloaded(self, monkeypatch):
        monkeypatch.setattr(diarize_mod, "_download", lambda *a, **k: None)
        with pytest.raises(diarize_mod.DiarizationError) as excinfo:
            diarize_mod.ensure_models(segmentation_model="/nope/seg.onnx")
        assert "/nope/seg.onnx" in str(excinfo.value)

    def test_cache_dir_honours_the_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("POTATO_MODEL_CACHE", str(tmp_path))
        assert diarize_mod.model_cache_dir() == str(tmp_path / "diarization")

    def test_cache_dir_defaults_under_home(self, monkeypatch):
        monkeypatch.delenv("POTATO_MODEL_CACHE", raising=False)
        assert diarize_mod.model_cache_dir().endswith(
            os.path.join(".cache", "potato", "models", "diarization"))


class TestTranscribeMediaCaching:
    """``transcribe_media`` is where the expensive work is skipped."""

    def _stub(self, monkeypatch, calls):
        import potato.transcript_cli as cli

        def fake_transcribe(path, **kwargs):
            calls.append("transcribe")
            return {"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}],
                    "language": "en", "duration": 1.0}

        def fake_diarize(path, **kwargs):
            calls.append("diarize")
            return [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]

        monkeypatch.setattr(cli, "transcribe_file", fake_transcribe)
        monkeypatch.setattr(cli, "diarize_file", fake_diarize)
        return cli

    def test_second_run_reuses_the_transcript(self, tmp_path, monkeypatch):
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={})
        payload, from_cache = cli.transcribe_media(str(media), options={})

        assert calls == ["transcribe"]
        assert from_cache is True
        assert payload["segments"][0]["text"] == "hello"

    def test_no_cache_forces_a_rerun(self, tmp_path, monkeypatch):
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={})
        cli.transcribe_media(str(media), options={}, reuse_cache=False)

        assert calls == ["transcribe", "transcribe"]

    def test_diarization_is_added_without_re_transcribing(self, tmp_path, monkeypatch):
        """Asking for speakers after the fact must not re-decode the audio."""
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={})
        payload, _ = cli.transcribe_media(
            str(media), options={}, diarize={"num_speakers": 2})

        assert calls == ["transcribe", "diarize"]
        assert payload["diarization"] == {"num_speakers": 2}
        assert payload["segments"][0]["speaker"] == "SPEAKER_00"
        assert payload["speakers"] == ["SPEAKER_00"]

    def test_diarization_is_not_repeated(self, tmp_path, monkeypatch):
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={}, diarize={})
        cli.transcribe_media(str(media), options={}, diarize={})

        assert calls == ["transcribe", "diarize"]

    def test_a_corrupt_cache_costs_one_rerun_not_a_crash(self, tmp_path, monkeypatch):
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")
        (tmp_path / "a.whisper.json").write_text("{ truncated")

        payload, from_cache = cli.transcribe_media(str(media), options={})

        assert calls == ["transcribe"]
        assert from_cache is False
        assert payload["segments"][0]["text"] == "hello"

    def test_a_different_model_is_not_served_from_the_cache(
            self, tmp_path, monkeypatch):
        """The silent one. Asking for large-v3 must not hand back tiny's text."""
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={"model": "tiny.en"})
        cli.transcribe_media(str(media), options={"model": "large-v3"})

        assert calls == ["transcribe", "transcribe"]

    def test_the_same_model_still_hits_the_cache(self, tmp_path, monkeypatch):
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={"model": "tiny.en"})
        _payload, from_cache = cli.transcribe_media(
            str(media), options={"model": "tiny.en"})

        assert calls == ["transcribe"]
        assert from_cache is True

    def test_turning_vad_off_re_transcribes(self, tmp_path, monkeypatch):
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={"vad_filter": True})
        cli.transcribe_media(str(media), options={"vad_filter": False})

        assert calls == ["transcribe", "transcribe"]

    def test_a_device_change_does_not_re_transcribe(self, tmp_path, monkeypatch):
        """Same model, different executor. Re-decoding an hour of audio because
        someone moved to a GPU would be a poor trade."""
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(
            str(media), options={"model": "base", "device": "cpu",
                                 "compute_type": "int8"})
        cli.transcribe_media(
            str(media), options={"model": "base", "device": "cuda",
                                 "compute_type": "float16"})

        assert calls == ["transcribe"]

    def test_changing_the_speaker_count_re_diarizes_only(
            self, tmp_path, monkeypatch):
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={}, diarize={"num_speakers": 2})
        cli.transcribe_media(str(media), options={}, diarize={"num_speakers": 3})

        assert calls == ["transcribe", "diarize", "diarize"]

    def test_the_cache_is_valid_json_on_disk(self, tmp_path, monkeypatch):
        calls = []
        cli = self._stub(monkeypatch, calls)
        media = tmp_path / "a.mp3"
        media.write_bytes(b"")

        cli.transcribe_media(str(media), options={})
        written = json.loads((tmp_path / "a.whisper.json").read_text())
        assert written["segments"][0]["text"] == "hello"


class TestNormalizerAcceptsWhatWeProduce:
    """The reason the ASR output is shaped as plain-Whisper JSON."""

    def test_undiarized_segments_become_undiarized_turns(self):
        result = normalize_transcript({
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello"},
                         {"start": 1.0, "end": 2.0, "text": "there"}],
            "language": "en",
        })
        assert [t["speaker"] for t in result["turns"]] == [None, None]
        assert [t["text"] for t in result["turns"]] == ["hello", "there"]

    def test_diarized_segments_carry_their_speakers_through(self):
        result = normalize_transcript({
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hello", "speaker": "SPEAKER_00"},
                {"start": 1.0, "end": 2.0, "text": "hi", "speaker": "SPEAKER_01"},
            ],
        })
        assert [t["speaker"] for t in result["turns"]] == [
            "SPEAKER_00", "SPEAKER_01"]


class TestCLIGating:
    def test_diarize_without_transcribe_is_rejected(self, tmp_path, capsys):
        from potato.transcript_cli import main

        with pytest.raises(SystemExit):
            main([str(tmp_path), "--diarize", "--dry-run"])
        assert "--diarize applies to --transcribe" in capsys.readouterr().err

    def test_transcribe_without_the_backend_names_the_extra(
            self, tmp_path, monkeypatch, capsys):
        import potato.server_utils.transcripts as pkg
        from potato.transcript_cli import main

        monkeypatch.setattr(pkg, "transcription_available", lambda: False)
        (tmp_path / "a.mp3").write_bytes(b"")

        assert main([str(tmp_path), "--transcribe", "--dry-run"]) == 1
        assert "potato-annotation[transcribe]" in capsys.readouterr().err

    def test_diarize_without_the_backend_names_the_extra(
            self, tmp_path, monkeypatch, capsys):
        import potato.server_utils.transcripts as pkg
        from potato.transcript_cli import main

        monkeypatch.setattr(pkg, "transcription_available", lambda: True)
        monkeypatch.setattr(pkg, "diarization_available", lambda: False)
        (tmp_path / "a.mp3").write_bytes(b"")

        assert main([str(tmp_path), "--transcribe", "--diarize",
                     "--dry-run"]) == 1
        assert "potato-annotation[transcribe]" in capsys.readouterr().err

    def test_a_media_file_without_transcribe_says_why_it_was_skipped(self, tmp_path):
        from potato.transcript_cli import convert_file

        media = tmp_path / "a.mp3"
        media.write_bytes(b"")
        item, report = convert_file(str(media))

        assert item is None
        assert "--transcribe" in report["error"]


class TestPackagingContract:
    def test_the_transcribe_extra_exists_and_names_faster_whisper(self):
        """`stt.py`, the CLI and the docs all point people at this extra."""
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        tree = ast.parse((root / "setup.py").read_text())

        deps = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", None) == "_TRANSCRIBE_DEPS"
                            for t in node.targets)):
                deps = ast.literal_eval(node.value)
        assert deps is not None, "_TRANSCRIBE_DEPS is gone from setup.py"
        joined = " ".join(deps)
        assert "faster-whisper" in joined
        assert "sherpa-onnx" in joined
