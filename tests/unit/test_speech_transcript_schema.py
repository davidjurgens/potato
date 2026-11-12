"""Unit tests for the speech_transcript schema (M13)."""

from potato.server_utils.schemas.speech_transcript import generate_speech_transcript_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "speech_transcript", "name": "tx",
            "description": "Tag speech errors", "segments_key": "segments"}
    base.update(kw)
    return base


class TestSpeechTranscript:
    def test_generates_container_and_input(self):
        html, kb = generate_speech_transcript_layout(_scheme())
        assert "speech-transcript-container" in html and "speech-transcript-input" in html
        assert kb == []

    def test_default_error_types(self):
        html, _ = generate_speech_transcript_layout(_scheme())
        for e in ("asr_error", "tts_artifact", "mispronunciation", "disfluency"):
            assert e in html

    def test_custom_error_types(self):
        html, _ = generate_speech_transcript_layout(_scheme(error_types=["clipping", "noise"]))
        assert '"error_types": ["clipping", "noise"]' in html

    def test_correction_toggle(self):
        html, _ = generate_speech_transcript_layout(_scheme(allow_correction=False))
        assert '"allow_correction": false' in html

    def test_restore_by_index(self):
        html, _ = generate_speech_transcript_layout(_scheme())
        assert "byIndex" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "speech_transcript" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "speech_transcript", "name": "x", "description": "d"})
        assert "speech-transcript-container" in html
