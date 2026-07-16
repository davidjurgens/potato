"""
Unit tests for the transcript ingestion normalizer.

Covers every accepted input shape (native turn JSON, WhisperX/diarized JSON,
plain Whisper JSON, WebVTT, SRT), stable turn-id assignment, undiarized ->
speaker None, and timestamp parsing.
"""

import pytest

from potato.server_utils.transcript_ingest import normalize_transcript, TranscriptError


class TestNativeTurnJSON:
    def test_dict_with_audio_and_turns(self):
        raw = {"audio": "ep.mp3", "turns": [
            {"speaker": "host", "start": 1.0, "end": 2.5, "text": "Hi"},
            {"speaker": "guest", "start": 2.5, "end": 4, "text": "Hello"},
        ]}
        out = normalize_transcript(raw)
        assert out["audio"] == "ep.mp3"
        assert [t["turn_id"] for t in out["turns"]] == ["t0", "t1"]
        assert out["turns"][0] == {"turn_id": "t0", "speaker": "host", "start": 1.0, "end": 2.5, "text": "Hi"}
        assert out["turns"][1]["end"] == 4.0

    def test_bare_list_of_turns(self):
        out = normalize_transcript([{"speaker": "a", "start": 0, "end": 1, "text": "x"}])
        assert out["audio"] is None
        assert out["turns"][0]["speaker"] == "a"

    def test_explicit_turn_id_preserved(self):
        out = normalize_transcript({"turns": [{"turn_id": "utt-9", "text": "hi"}]})
        assert out["turns"][0]["turn_id"] == "utt-9"

    def test_custom_keys(self):
        raw = {"clip": "a.wav", "segs": [{"spk": "S1", "begin": 0, "stop": 2, "words": "hey"}]}
        out = normalize_transcript(
            raw, audio_key="clip", turns_key="segs",
            speaker_key="spk", text_key="words", start_key="begin", end_key="stop",
        )
        assert out["audio"] == "a.wav"
        assert out["turns"][0]["speaker"] == "S1"
        assert out["turns"][0]["text"] == "hey"
        assert out["turns"][0]["end"] == 2.0


class TestWhisper:
    def test_whisperx_diarized_segments(self):
        raw = {"segments": [
            {"start": 0, "end": 1.2, "text": "Welcome", "speaker": "SPEAKER_00"},
            {"start": 1.2, "end": 3.0, "text": "Thanks", "speaker": "SPEAKER_01"},
        ]}
        out = normalize_transcript(raw)
        assert out["turns"][0]["speaker"] == "SPEAKER_00"
        assert out["turns"][1]["speaker"] == "SPEAKER_01"
        assert [t["turn_id"] for t in out["turns"]] == ["t0", "t1"]

    def test_plain_whisper_is_undiarized(self):
        raw = {"segments": [{"id": 0, "start": 0, "end": 1.2, "text": "Welcome"}]}
        out = normalize_transcript(raw)
        assert out["turns"][0]["speaker"] is None
        # numeric segment id must NOT become the turn_id (index is stable)
        assert out["turns"][0]["turn_id"] == "t0"


class TestVTT:
    def test_vtt_with_voice_tags(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n<v Host>Welcome to the show</v>\n\n"
            "00:00:03.000 --> 00:00:06.000\n<v Guest>Glad to be here</v>\n"
        )
        out = normalize_transcript(vtt)
        assert out["turns"][0]["speaker"] == "Host"
        assert out["turns"][0]["text"] == "Welcome to the show"
        assert out["turns"][0]["start"] == 1.0
        assert out["turns"][1]["speaker"] == "Guest"
        assert out["turns"][1]["end"] == 6.0

    def test_vtt_name_prefix(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nAlice: hi there\n"
        out = normalize_transcript(vtt)
        assert out["turns"][0]["speaker"] == "Alice"
        assert out["turns"][0]["text"] == "hi there"

    def test_vtt_no_speaker(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\njust some narration\n"
        out = normalize_transcript(vtt)
        assert out["turns"][0]["speaker"] is None
        assert out["turns"][0]["text"] == "just some narration"


class TestSRT:
    def test_srt_with_speaker_prefix(self):
        srt = (
            "1\n00:00:01,000 --> 00:00:02,500\nHost: So let us begin.\n\n"
            "2\n00:00:02,500 --> 00:00:05,000\nRight, the key thing is timing.\n"
        )
        out = normalize_transcript(srt)
        assert out["turns"][0]["speaker"] == "Host"
        assert out["turns"][0]["text"] == "So let us begin."
        assert out["turns"][0]["start"] == 1.0
        assert out["turns"][0]["end"] == 2.5
        assert out["turns"][1]["speaker"] is None
        assert out["turns"][1]["end"] == 5.0

    def test_srt_multiline_cue(self):
        srt = "1\n00:00:00,000 --> 00:00:04,000\nline one\nline two\n"
        out = normalize_transcript(srt)
        assert out["turns"][0]["text"] == "line one\nline two"


class TestSPoRC:
    """Structured Podcast Research Corpus (blitt/SPoRC) speaker-turn rows."""

    def _rows(self):
        base = {"episode_id": "ep_abc", "podcast_id": "p1",
                "mp3_url": "https://cdn.example.com/ep_abc.mp3"}
        return [
            {**base, "speaker": ["SPEAKER_00"], "turn_text": "Welcome to the show.",
             "start_time": 0.0, "end_time": 4.2, "duration": 4.2, "turn_count": 0,
             "inferred_speaker_role": "host", "inferred_speaker_name": "Alex Rivera"},
            {**base, "speaker": ["SPEAKER_01"], "turn_text": "Thanks for having me.",
             "start_time": 4.2, "end_time": 7.9, "duration": 3.7, "turn_count": 1,
             "inferred_speaker_role": "guest", "inferred_speaker_name": "Dr. Chen"},
            {**base, "speaker": ["SPEAKER_02"], "turn_text": "A brief ad plays here.",
             "start_time": 7.9, "end_time": 12.0, "duration": 4.1, "turn_count": 2,
             "inferred_speaker_role": "neither", "inferred_speaker_name": ""},
        ]

    def test_bare_list_default_keys(self):
        # turn_text / start_time / end_time picked up via fallback; speaker list
        # -> first element; audio derived from mp3_url.
        out = normalize_transcript(self._rows())
        assert out["audio"] == "https://cdn.example.com/ep_abc.mp3"
        assert out["turns"][0] == {
            "turn_id": "t0", "speaker": "SPEAKER_00",
            "start": 0.0, "end": 4.2, "text": "Welcome to the show.",
        }
        assert out["turns"][1]["speaker"] == "SPEAKER_01"

    def test_audio_from_mp3_url_on_dict_without_audio(self):
        out = normalize_transcript({"turns": self._rows()})
        assert out["audio"] == "https://cdn.example.com/ep_abc.mp3"

    def test_speaker_key_inferred_name(self):
        out = normalize_transcript(self._rows(), speaker_key="inferred_speaker_name")
        speakers = [t["speaker"] for t in out["turns"]]
        # empty name + role "neither" -> undiarized (None) so annotator assigns
        assert speakers == ["Alex Rivera", "Dr. Chen", None]

    def test_speaker_key_inferred_role(self):
        out = normalize_transcript(self._rows(), speaker_key="inferred_speaker_role")
        speakers = [t["speaker"] for t in out["turns"]]
        assert speakers == ["host", "guest", None]  # "neither" -> None

    def test_list_speaker_default_key_falls_back_to_name(self):
        # If the raw diarization list is empty, fall back to inferred name.
        row = {"speaker": [], "turn_text": "hi", "start_time": 1, "end_time": 2,
               "inferred_speaker_name": "Sam"}
        out = normalize_transcript([row])
        assert out["turns"][0]["speaker"] == "Sam"

    def test_camelcase_jsonl_rows(self):
        # The SPoRC JSONL distribution uses camelCase fields.
        rows = [
            {"turnText": "Welcome to the show.", "speaker": ["SPEAKER_00"],
             "startTime": 0.0, "endTime": 4.2, "duration": 4.2, "turnCount": 0,
             "mp3url": "https://cdn.example.com/ep.mp3",
             "inferredSpeakerRole": "host", "inferredSpeakerName": "Harold Prestonbach"},
            {"turnText": "Thanks!", "speaker": ["SPEAKER_01"],
             "startTime": 4.2, "endTime": 6.0, "duration": 1.8, "turnCount": 1,
             "mp3url": "https://cdn.example.com/ep.mp3",
             "inferredSpeakerRole": "guest", "inferredSpeakerName": "Kristen Dowd"},
            {"turnText": "love", "speaker": ["SPEAKER_02"],
             "startTime": 6.0, "endTime": 6.5, "duration": 0.5, "turnCount": 2,
             "mp3url": "https://cdn.example.com/ep.mp3",
             "inferredSpeakerRole": "NO_INFERRED_ROLE", "inferredSpeakerName": "NO_INFERRED_SPEAKER"},
        ]
        out = normalize_transcript(rows, speaker_key="inferredSpeakerName")
        assert out["audio"] == "https://cdn.example.com/ep.mp3"  # from mp3url
        assert out["turns"][0]["text"] == "Welcome to the show."
        assert out["turns"][0]["start"] == 0.0 and out["turns"][0]["end"] == 4.2
        speakers = [t["speaker"] for t in out["turns"]]
        # real names, and NO_INFERRED_SPEAKER -> undiarized
        assert speakers == ["Harold Prestonbach", "Kristen Dowd", None]


class TestTimestamps:
    def test_hms_and_numeric(self):
        raw = {"turns": [
            {"start": "00:01:02.500", "end": "1:03:04.000", "text": "a"},
            {"start": 5, "end": 7.5, "text": "b"},
        ]}
        out = normalize_transcript(raw)
        assert out["turns"][0]["start"] == 62.5
        assert out["turns"][0]["end"] == 3784.0
        assert out["turns"][1]["start"] == 5.0

    def test_missing_end_falls_back_to_start(self):
        out = normalize_transcript({"turns": [{"start": 3.0, "text": "a"}]})
        assert out["turns"][0]["end"] == 3.0


class TestEdgeCases:
    def test_none_and_empty(self):
        assert normalize_transcript(None) == {"audio": None, "turns": []}
        assert normalize_transcript("") == {"audio": None, "turns": []}
        assert normalize_transcript({}) == {"audio": None, "turns": []}

    def test_plain_string_single_turn(self):
        out = normalize_transcript("one blob of untimed text")
        assert len(out["turns"]) == 1
        assert out["turns"][0]["speaker"] is None
        assert out["turns"][0]["text"] == "one blob of untimed text"

    def test_transcript_subkey_string(self):
        raw = {"audio": "a.mp3", "transcript": "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHost: hi\n"}
        out = normalize_transcript(raw)
        assert out["audio"] == "a.mp3"
        assert out["turns"][0]["speaker"] == "Host"

    def test_unsupported_type_raises(self):
        with pytest.raises(TranscriptError):
            normalize_transcript(42)

    def test_stable_ids_across_reingest(self):
        raw = {"turns": [{"text": "a"}, {"text": "b"}, {"text": "c"}]}
        ids1 = [t["turn_id"] for t in normalize_transcript(raw)["turns"]]
        ids2 = [t["turn_id"] for t in normalize_transcript(raw)["turns"]]
        assert ids1 == ids2 == ["t0", "t1", "t2"]
