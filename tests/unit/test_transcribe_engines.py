"""WhisperX when it runs here, faster-whisper when it does not.

Both engines are replaced with fakes in ``sys.modules``, so these run with
neither installed and never load a model.
"""

import logging
import sys
import types

import pytest

from potato.server_utils.transcripts import transcribe as tx


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(tx, "_WHISPERX_STATUS", None)
    monkeypatch.setattr(tx, "_MODEL_CACHE", {})
    monkeypatch.setattr(tx, "_WHISPERX_REFUSED", {})
    monkeypatch.setattr(tx, "_ANNOUNCED", set())
    monkeypatch.setattr(tx, "_ALIGNERS", {})


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "talk.wav"
    path.write_bytes(b"RIFF")
    return str(path)


def fake_faster_whisper(monkeypatch, calls):
    module = types.ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, model, device, compute_type):
            calls.append(("faster-whisper load", model, device))

        def transcribe(self, path, **kwargs):
            calls.append(("faster-whisper", path))
            segment = types.SimpleNamespace(start=0.0, end=1.0, text=" hello ", words=None)
            return iter([segment]), types.SimpleNamespace(language="en", duration=1.0)

    module.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


def fake_whisperx(monkeypatch, calls, load_error=None, transcribe_error=None,
                  align_error=None, import_error=None):
    module = types.ModuleType("whisperx")
    asr = types.ModuleType("whisperx.asr")
    if import_error is not None:
        if isinstance(import_error, ImportError):
            # Not installed: None in sys.modules makes the import fail.
            monkeypatch.setitem(sys.modules, "whisperx", None)
            return
        # Installed but broken, as burger's is: importing it raises.
        import builtins
        real_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "whisperx" or name.startswith("whisperx."):
                raise import_error
            return real_import(name, *args, **kwargs)
        monkeypatch.delitem(sys.modules, "whisperx", raising=False)
        monkeypatch.setattr(builtins, "__import__", guarded)
        return

    class Pipeline:
        def transcribe(self, audio, batch_size=None, language=None):
            if transcribe_error:
                raise transcribe_error
            calls.append(("whisperx", batch_size, language))
            return {"language": language or "en", "segments": [
                {"start": 0.0, "end": 1.5, "text": " hi there "},
                {"start": 2.0, "end": 2.0, "text": "  "}]}

    def load_model(model, device, compute_type=None, language=None, asr_options=None):
        calls.append(("whisperx load attempt", model))
        if load_error:
            raise load_error
        calls.append(("whisperx load", model, device, compute_type, asr_options))
        return Pipeline()

    def load_align_model(language, device):
        calls.append(("align load", language))
        if align_error:
            raise align_error
        return "aligner", {"language": language}

    def align(segments, model, metadata, audio, device):
        return {"segments": [dict(s, words=[
            {"word": "hi", "start": 0.0, "end": 0.5, "score": 0.9},
            {"word": "3", "score": 0.1}]) for s in segments]}

    module.load_model = load_model
    module.load_audio = lambda path: [0.0] * 32000
    module.load_align_model = load_align_model
    module.align = align
    monkeypatch.setitem(sys.modules, "whisperx", module)
    monkeypatch.setitem(sys.modules, "whisperx.asr", asr)


def test_auto_uses_whisperx_when_it_runs(monkeypatch, media):
    calls = []
    fake_whisperx(monkeypatch, calls)
    fake_faster_whisper(monkeypatch, calls)
    out = tx.transcribe_file(media, model="ct2-dir", beam_size=3)
    assert out["engine"] == "whisperx" and out["language"] == "en"
    assert out["segments"] == [{"id": 0, "start": 0.0, "end": 1.5, "text": "hi there"}]
    assert out["duration"] == 2.0
    assert ("whisperx load", "ct2-dir", "cpu", "int8", {"beam_size": 3}) in calls
    assert not [c for c in calls if c[0].startswith("faster-whisper")]


def test_word_times_come_from_alignment_and_unplaced_words_are_left_out(monkeypatch, media):
    calls = []
    fake_whisperx(monkeypatch, calls)
    out = tx.transcribe_file(media, word_timestamps=True)
    assert out["segments"][0]["words"] == [
        {"start": 0.0, "end": 0.5, "word": "hi", "probability": 0.9}]


def test_a_failed_alignment_keeps_the_segments(monkeypatch, media, caplog):
    calls = []
    fake_whisperx(monkeypatch, calls, align_error=OSError("no alignment model offline"))
    with caplog.at_level(logging.WARNING):
        out = tx.transcribe_file(media, word_timestamps=True)
    assert out["engine"] == "whisperx" and "words" not in out["segments"][0]
    assert "could not load a word-alignment model" in caplog.text


@pytest.mark.parametrize("import_error", [ImportError("no module"),
                                          AttributeError("torchaudio has no AudioMetaData")])
def test_auto_falls_back_when_whisperx_does_not_import(monkeypatch, media, caplog,
                                                       import_error):
    calls = []
    fake_faster_whisper(monkeypatch, calls)
    fake_whisperx(monkeypatch, calls, import_error=import_error)
    with caplog.at_level(logging.WARNING):
        out = tx.transcribe_file(media)
    assert out["engine"] == "faster-whisper"
    assert "transcribing with faster-whisper" in caplog.text
    if isinstance(import_error, AttributeError):
        assert "AudioMetaData" in caplog.text


def test_auto_falls_back_on_a_device_whisperx_has_not(monkeypatch, media):
    calls = []
    fake_whisperx(monkeypatch, calls)
    fake_faster_whisper(monkeypatch, calls)
    out = tx.transcribe_file(media, device="mps")
    assert out["engine"] == "faster-whisper"


def test_a_model_whisperx_cannot_load_falls_back_once_for_every_file(monkeypatch, media, caplog):
    calls = []
    fake_whisperx(monkeypatch, calls, load_error=AssertionError("Unsupported n_mels: 16"))
    fake_faster_whisper(monkeypatch, calls)
    with caplog.at_level(logging.WARNING):
        first = tx.transcribe_file(media, model="tiny-16-mels")
        second = tx.transcribe_file(media, model="tiny-16-mels")
    assert first["engine"] == second["engine"] == "faster-whisper"
    assert caplog.text.count("Unsupported n_mels") == 1
    # Tried once; the second file does not pay for the same failure.
    assert [c for c in calls if c[0] == "whisperx load attempt"] == [
        ("whisperx load attempt", "tiny-16-mels")]


def test_one_file_whisperx_fails_on_falls_back_alone(monkeypatch, media):
    calls = []
    fake_whisperx(monkeypatch, calls, transcribe_error=IndexError("no speech found"))
    fake_faster_whisper(monkeypatch, calls)
    assert tx.transcribe_file(media)["engine"] == "faster-whisper"
    # Not a load-level failure: the next file tries WhisperX again.
    assert not tx._WHISPERX_REFUSED


def test_a_named_engine_does_not_fall_back(monkeypatch, media):
    calls = []
    fake_whisperx(monkeypatch, calls, load_error=RuntimeError("bad model"))
    fake_faster_whisper(monkeypatch, calls)
    with pytest.raises(tx.TranscriptionError, match="bad model"):
        tx.transcribe_file(media, engine="whisperx")
    calls.clear()
    assert tx.transcribe_file(media, engine="faster-whisper")["engine"] == "faster-whisper"
    assert not [c for c in calls if c[0].startswith("whisperx")]


def test_whisperx_missing_by_name_says_how_to_install(monkeypatch, media):
    fake_whisperx(monkeypatch, [], import_error=ImportError("no module"))
    with pytest.raises(tx.TranscriptionError, match="pip install whisperx"):
        tx.transcribe_file(media, engine="whisperx")
    with pytest.raises(tx.TranscriptionError, match="engine must be one of"):
        tx.transcribe_file(media, engine="whisper.cpp")


@pytest.mark.parametrize("cached, works, want, reused", [
    ("faster-whisper", True, "auto", False),    # fell back once; WhisperX works now
    ("faster-whisper", False, "auto", True),
    ("whisperx", True, "auto", True),
    ("whisperx", True, "faster-whisper", False),
    (None, False, "auto", True),                # written before engines were recorded
    ("failed-here", True, "auto", True),        # WhisperX already failed on this file
    ("failed-here", True, "whisperx", False),   # E2: named WhisperX wants its own
])
def test_a_cached_transcript_is_reused_only_from_the_engine_that_would_run(
        monkeypatch, tmp_path, cached, works, want, reused):
    """Audit 104 W-P2b: the cache was keyed on the engine asked for."""
    import json
    from potato import transcript_cli as cli
    media = tmp_path / "talk.wav"
    media.write_bytes(b"RIFF")
    options = {"model": "base", "language": None, "vad_filter": True,
               "word_timestamps": False, "engine": want}
    entry = {"segments": [], "asr": cli._signature(options, cli._ASR_SIGNATURE_KEYS)}
    if cached == "failed-here":
        entry.update(engine="faster-whisper", whisperx_failed="IndexError: no speech")
    elif cached:
        entry["engine"] = cached
    (tmp_path / "talk.whisper.json").write_text(json.dumps(entry))
    monkeypatch.setattr(tx, "_WHISPERX_STATUS", (works, "" if works else "not installed"))
    ran = []
    monkeypatch.setattr(cli, "transcribe_file", lambda path, **kw: ran.append(kw) or {
        "segments": [], "engine": "whisperx"})
    _, from_cache = cli.transcribe_media(str(media), options=options)
    assert from_cache is reused and bool(ran) is not reused


def test_the_cli_says_which_engine_ran(monkeypatch, tmp_path):
    from potato import transcript_cli as cli
    media = tmp_path / "talk.wav"
    media.write_bytes(b"RIFF")
    monkeypatch.setattr(cli, "transcribe_file", lambda path, **kw: {
        "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}], "language": "en",
        "duration": 1.0, "engine": "faster-whisper"})
    item, report = cli.convert_file(str(media), transcribe={"model": "base", "engine": "auto",
                                                            "reuse_cache": False})
    assert item is not None and report["format"] == "ASR (faster-whisper)"


@pytest.mark.parametrize("align_error", [None, OSError("offline")])
def test_the_alignment_model_loads_once_for_a_directory(monkeypatch, tmp_path, align_error):
    """Audit 104 W-P2a: three files made three loads, or three failed tries,
    each of which can wait on a network timeout offline."""
    calls = []
    fake_whisperx(monkeypatch, calls, align_error=align_error)
    for name in ("a", "b", "c"):
        path = tmp_path / ("%s.wav" % name)
        path.write_bytes(b"RIFF")
        tx.transcribe_file(str(path), word_timestamps=True)
    assert [c for c in calls if c[0] == "align load"] == [("align load", "en")]


def test_segment_times_stay_inside_the_recording_and_ids_run_on(monkeypatch, media, caplog):
    """tiny.en ended a 2.7 s file's segment at 7.0 s; untimed segments left
    gaps in the ids and went unreported."""
    calls = []
    fake_whisperx(monkeypatch, calls)
    import whisperx

    class Pipeline:
        def transcribe(self, audio, batch_size=None, language=None):
            return {"language": "en", "segments": [
                {"start": None, "end": 1.0, "text": "lost"},
                {"start": 1.5, "end": 7.0, "text": "past the end"}]}
    monkeypatch.setattr(whisperx, "load_model", lambda *a, **k: Pipeline())
    with caplog.at_level(logging.WARNING):
        out = tx.transcribe_file(media)
    assert out["segments"] == [{"id": 0, "start": 1.5, "end": 2.0, "text": "past the end"}]
    assert "1 segment(s)" in caplog.text


def test_an_english_only_model_transcribes_english(monkeypatch, media, caplog):
    calls = []
    fake_whisperx(monkeypatch, calls)
    with caplog.at_level(logging.WARNING):
        out = tx.transcribe_file(media, model="tiny.en", language="fr")
    assert out["language"] == "en" and "English-only" in caplog.text


def test_a_model_whisperx_refuses_is_remembered_in_every_files_transcript(monkeypatch, tmp_path):
    """Audit 104 E1: the refusal lived only in the process, so every new run
    loaded the model again and re-transcribed a file to find out."""
    from potato import transcript_cli as cli
    calls = []
    fake_whisperx(monkeypatch, calls, load_error=AssertionError("Unsupported n_mels: 16"))
    fake_faster_whisper(monkeypatch, calls)
    outs = []
    for name in ("a", "b"):
        path = tmp_path / ("%s.wav" % name)
        path.write_bytes(b"RIFF")
        outs.append(tx.transcribe_file(str(path), model="tiny-16"))
    assert all("n_mels" in out["whisperx_failed"] for out in outs)
    # A new process has forgotten the refusal; the transcripts still stand.
    monkeypatch.setattr(tx, "_WHISPERX_REFUSED", {})
    assert all(cli._cached_engine_fits(out, {"engine": "auto", "model": "tiny-16"})
               for out in outs)


def test_a_named_whisperx_that_will_not_load_does_not_say_install_it(monkeypatch, media):
    """E4: WhisperX is installed; telling the user to install it is wrong."""
    fake_whisperx(monkeypatch, [], load_error=RuntimeError("bad model"))
    with pytest.raises(tx.TranscriptionError) as excinfo:
        tx.transcribe_file(media, engine="whisperx")
    assert "bad model" in str(excinfo.value) and "pip install" not in str(excinfo.value)
