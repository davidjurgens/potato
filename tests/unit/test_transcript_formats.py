"""
Unit tests for the transcript formats added beyond Whisper/VTT/SRT.

Covers the caption formats you get from YouTube (json3, srv/TTML, ASS), the
cloud ASR vendor responses (AWS Transcribe, Deepgram, AssemblyAI, Rev.ai),
Whisper's other output files (whisper.cpp JSON, TSV), and the alignment formats
(CTM, Praat TextGrid, ELAN EAF).

The fixtures here are trimmed but structurally faithful to what each tool
actually emits — in particular the time units, which differ per vendor and are
the most common source of silently wrong output.

The pre-existing shapes are covered by ``test_transcript_ingest.py``, which must
keep passing unchanged; these tests are additive.
"""

import pytest

from potato.server_utils.transcripts import (
    detect_format,
    normalize_transcript,
)


def turns(raw, **kwargs):
    return normalize_transcript(raw, **kwargs)["turns"]


# ---------------------------------------------------------------------------
# YouTube / caption formats
# ---------------------------------------------------------------------------

class TestJSON3:
    """YouTube's json3, what ``yt-dlp --sub-format json3`` downloads."""

    RAW = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 1500, "segs": [{"utf8": "Hello there"}]},
            {"tStartMs": 1500, "dDurationMs": 2000, "segs": [
                {"utf8": "general"}, {"utf8": " kenobi", "tOffsetMs": 400},
            ]},
            # Window/format records carry no segs and must be skipped.
            {"tStartMs": 0, "wWinId": 1},
        ]
    }

    def test_events_become_turns(self):
        out = turns(self.RAW)
        assert len(out) == 2
        assert out[0]["text"] == "Hello there"
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == 1.5

    def test_milliseconds_converted(self):
        out = turns(self.RAW)
        assert out[1]["start"] == 1.5
        assert out[1]["end"] == 3.5

    def test_word_offsets_preserved(self):
        out = turns(self.RAW)
        words = out[1]["words"]
        assert [w["word"] for w in words] == ["general", "kenobi"]
        assert words[1]["start"] == pytest.approx(1.9)

    def test_single_seg_event_has_no_words_key(self):
        # One segment is not word timing; emitting "words" would be misleading.
        assert "words" not in turns(self.RAW)[0]

    def test_detect(self):
        assert detect_format(self.RAW) == "YouTube json3"


class TestTTML:
    TTML = """<?xml version="1.0" encoding="utf-8"?>
<tt xmlns="http://www.w3.org/ns/ttml">
  <body><div>
    <p begin="00:00:01.000" end="00:00:03.500">Alice: Good morning.</p>
    <p begin="00:00:03.500" end="00:00:06.000">Bob: Morning!<br/>How are you?</p>
  </div></body>
</tt>"""

    def test_parses_namespaced_paragraphs(self):
        out = turns(self.TTML)
        assert len(out) == 2
        assert out[0]["start"] == 1.0
        assert out[0]["end"] == 3.5

    def test_speaker_prefix_extracted(self):
        out = turns(self.TTML)
        assert out[0]["speaker"] == "Alice"
        assert out[0]["text"] == "Good morning."

    def test_br_becomes_space(self):
        assert turns(self.TTML)[1]["text"] == "Morning! How are you?"

    def test_offset_time_expressions(self):
        ttml = ('<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
                '<p begin="1.5s" end="2500ms">quick</p></div></body></tt>')
        out = turns(ttml)
        assert out[0]["start"] == 1.5
        assert out[0]["end"] == 2.5

    def test_detect(self):
        assert detect_format(self.TTML) == "TTML / srv XML"


class TestSRV1:
    """YouTube's older srv1 endpoint: <transcript><text start dur>."""

    SRV1 = ('<?xml version="1.0" encoding="utf-8"?><transcript>'
            '<text start="0" dur="2.4">first line</text>'
            '<text start="2.4" dur="1.6">second line</text></transcript>')

    def test_start_plus_dur(self):
        out = turns(self.SRV1)
        assert len(out) == 2
        assert out[1]["start"] == 2.4
        assert out[1]["end"] == pytest.approx(4.0)


class TestASS:
    ASS = """[Script Info]
Title: Sample
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname
Style: Default,Arial

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,Alice,0,0,0,,{\\an8}Hello, how are you?
Dialogue: 0,0:00:03.50,0:00:05.00,Default,Bob,0,0,0,,Fine\\Nthanks
"""

    def test_dialogue_events(self):
        out = turns(self.ASS)
        assert len(out) == 2
        assert out[0]["start"] == 1.0
        assert out[0]["end"] == 3.5

    def test_name_field_is_speaker(self):
        out = turns(self.ASS)
        assert [t["speaker"] for t in out] == ["Alice", "Bob"]

    def test_override_tags_stripped(self):
        # {\an8} is positioning, not content.
        assert turns(self.ASS)[0]["text"] == "Hello, how are you?"

    def test_commas_in_text_survive_field_split(self):
        assert "," in turns(self.ASS)[0]["text"]

    def test_newline_escape(self):
        assert turns(self.ASS)[1]["text"] == "Fine thanks"

    def test_detect(self):
        assert detect_format(self.ASS) == "SubStation Alpha"


# ---------------------------------------------------------------------------
# Whisper's other outputs
# ---------------------------------------------------------------------------

class TestWhisperCpp:
    RAW = {
        "systeminfo": "...",
        "transcription": [
            {"timestamps": {"from": "00:00:00,000", "to": "00:00:02,400"},
             "offsets": {"from": 0, "to": 2400}, "text": " Hello world."},
            {"timestamps": {"from": "00:00:02,400", "to": "00:00:04,000"},
             "offsets": {"from": 2400, "to": 4000}, "text": " Second bit."},
        ],
    }

    def test_offsets_are_milliseconds(self):
        out = turns(self.RAW)
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == 2.4
        assert out[1]["start"] == 2.4

    def test_text_stripped(self):
        assert turns(self.RAW)[0]["text"] == "Hello world."

    def test_falls_back_to_timestamps(self):
        raw = {"transcription": [
            {"timestamps": {"from": "00:00:01,500", "to": "00:00:02,000"},
             "text": "no offsets"},
        ]}
        out = turns(raw)
        assert out[0]["start"] == 1.5

    def test_detect(self):
        assert detect_format(self.RAW) == "whisper.cpp JSON"


class TestWhisperTSV:
    TSV = "start\tend\ttext\n0\t2400\tHello world.\n2400\t4000\tSecond bit.\n"

    def test_milliseconds_to_seconds(self):
        out = turns(self.TSV)
        assert len(out) == 2
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == 2.4

    def test_header_skipped(self):
        assert turns(self.TSV)[0]["text"] == "Hello world."

    def test_detect(self):
        assert detect_format(self.TSV) == "Whisper TSV"


# ---------------------------------------------------------------------------
# Cloud ASR vendors
# ---------------------------------------------------------------------------

class TestAWSTranscribe:
    MODERN = {
        "jobName": "job",
        "results": {
            "transcripts": [{"transcript": "Hello there. Hi back."}],
            "audio_segments": [
                {"id": 0, "transcript": "Hello there.", "start_time": "0.0",
                 "end_time": "1.5", "speaker_label": "spk_0"},
                {"id": 1, "transcript": "Hi back.", "start_time": "1.5",
                 "end_time": "2.8", "speaker_label": "spk_1"},
            ],
            "items": [],
        },
    }

    LEGACY = {
        "results": {
            "transcripts": [{"transcript": "Hello there"}],
            "speaker_labels": {"segments": [
                {"start_time": "0.0", "end_time": "1.0", "speaker_label": "spk_0"},
                {"start_time": "1.0", "end_time": "2.0", "speaker_label": "spk_1"},
            ]},
            "items": [
                {"type": "pronunciation", "start_time": "0.0", "end_time": "0.4",
                 "alternatives": [{"content": "Hello", "confidence": "0.99"}]},
                {"type": "punctuation",
                 "alternatives": [{"content": ",", "confidence": "0.0"}]},
                {"type": "pronunciation", "start_time": "1.2", "end_time": "1.6",
                 "alternatives": [{"content": "there", "confidence": "0.98"}]},
            ],
        },
    }

    def test_modern_audio_segments(self):
        out = turns(self.MODERN)
        assert len(out) == 2
        assert out[0]["speaker"] == "spk_0"
        assert out[0]["start"] == 0.0
        assert out[1]["text"] == "Hi back."

    def test_legacy_items_grouped_by_speaker(self):
        out = turns(self.LEGACY)
        assert [t["speaker"] for t in out] == ["spk_0", "spk_1"]

    def test_punctuation_attaches_to_previous_word(self):
        out = turns(self.LEGACY)
        assert out[0]["text"] == "Hello,"

    def test_word_confidence_preserved(self):
        out = turns(self.LEGACY)
        assert out[0]["words"][0]["confidence"] == pytest.approx(0.99)

    def test_detect(self):
        assert detect_format(self.MODERN) == "AWS Transcribe JSON"


class TestDeepgram:
    WITH_UTTERANCES = {
        "results": {
            "channels": [{"alternatives": [{"transcript": "Hello there hi back"}]}],
            "utterances": [
                {"start": 0.0, "end": 1.5, "confidence": 0.97, "speaker": 0,
                 "transcript": "Hello there",
                 "words": [{"word": "hello", "punctuated_word": "Hello",
                            "start": 0.0, "end": 0.5, "confidence": 0.99}]},
                {"start": 1.5, "end": 2.8, "speaker": 1, "transcript": "hi back"},
            ],
        }
    }

    WORDS_ONLY = {
        "results": {"channels": [{"alternatives": [{
            "transcript": "hello there hi",
            "words": [
                {"word": "hello", "start": 0.0, "end": 0.4, "speaker": 0},
                {"word": "there", "start": 0.4, "end": 0.9, "speaker": 0},
                {"word": "hi", "start": 3.0, "end": 3.2, "speaker": 1},
            ],
        }]}]}
    }

    def test_utterances_preferred(self):
        out = turns(self.WITH_UTTERANCES)
        assert len(out) == 2
        assert out[0]["text"] == "Hello there"

    def test_integer_speaker_normalized(self):
        assert turns(self.WITH_UTTERANCES)[0]["speaker"] == "speaker_0"

    def test_utterance_confidence_kept(self):
        assert turns(self.WITH_UTTERANCES)[0]["confidence"] == pytest.approx(0.97)

    def test_punctuated_word_wins(self):
        assert turns(self.WITH_UTTERANCES)[0]["words"][0]["word"] == "Hello"

    def test_words_grouped_on_speaker_change(self):
        out = turns(self.WORDS_ONLY)
        assert len(out) == 2
        assert out[0]["text"] == "hello there"
        assert out[1]["speaker"] == "speaker_1"

    def test_detect(self):
        assert detect_format(self.WITH_UTTERANCES) == "Deepgram JSON"


class TestAssemblyAI:
    RAW = {
        "id": "abc",
        "text": "Hello there hi back",
        "words": [{"text": "Hello", "start": 0, "end": 400, "confidence": 0.99,
                   "speaker": "A"}],
        "utterances": [
            {"start": 0, "end": 1500, "confidence": 0.95, "speaker": "A",
             "text": "Hello there",
             "words": [{"text": "Hello", "start": 0, "end": 400, "confidence": 0.99}]},
            {"start": 1500, "end": 2800, "speaker": "B", "text": "hi back"},
        ],
    }

    def test_milliseconds_rescaled(self):
        out = turns(self.RAW)
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == 1.5
        assert out[1]["start"] == 1.5

    def test_speakers(self):
        assert [t["speaker"] for t in turns(self.RAW)] == ["A", "B"]

    def test_word_times_also_rescaled(self):
        assert turns(self.RAW)[0]["words"][0]["end"] == pytest.approx(0.4)

    def test_words_only_fallback(self):
        raw = {"text": "hello there", "words": [
            {"text": "hello", "start": 0, "end": 400, "speaker": "A"},
            {"text": "there", "start": 400, "end": 900, "speaker": "A"},
        ]}
        out = turns(raw)
        assert len(out) == 1
        assert out[0]["text"] == "hello there"

    def test_detect(self):
        assert detect_format(self.RAW) == "AssemblyAI JSON"


class TestRevAI:
    RAW = {
        "monologues": [
            {"speaker": 0, "elements": [
                {"type": "text", "value": "Hello", "ts": 0.0, "end_ts": 0.4,
                 "confidence": 0.98},
                {"type": "punct", "value": " "},
                {"type": "text", "value": "there", "ts": 0.4, "end_ts": 0.9},
                {"type": "punct", "value": "."},
            ]},
            {"speaker": 1, "elements": [
                {"type": "text", "value": "Hi", "ts": 1.5, "end_ts": 1.8},
            ]},
        ]
    }

    def test_monologue_per_speaker(self):
        out = turns(self.RAW)
        assert len(out) == 2
        assert out[0]["speaker"] == "speaker_0"

    def test_punctuation_joins_text(self):
        assert turns(self.RAW)[0]["text"] == "Hello there."

    def test_times_from_first_and_last_word(self):
        out = turns(self.RAW)
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == pytest.approx(0.9)

    def test_detect(self):
        assert detect_format(self.RAW) == "Rev.ai JSON"


# ---------------------------------------------------------------------------
# Alignment / linguistics formats
# ---------------------------------------------------------------------------

class TestCTM:
    MULTI = (
        "interview 1 0.00 0.34 hello 0.98\n"
        "interview 1 0.35 0.40 there 0.95\n"
        "interview 2 2.00 0.30 hi 0.91\n"
    )
    SINGLE = (
        "rec A 0.00 0.34 hello\n"
        "rec A 0.35 0.40 there\n"
        "rec A 5.00 0.30 later\n"
    )

    def test_channel_becomes_speaker(self):
        out = turns(self.MULTI)
        assert [t["speaker"] for t in out] == ["1", "2"]

    def test_words_grouped_into_turns(self):
        out = turns(self.MULTI)
        assert out[0]["text"] == "hello there"

    def test_duration_becomes_end_time(self):
        out = turns(self.MULTI)
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == pytest.approx(0.75)

    def test_single_channel_reads_as_undiarized(self):
        # One channel carries no speaker information; "A" everywhere is noise.
        out = turns(self.SINGLE)
        assert all(t["speaker"] is None for t in out)

    def test_pause_splits_turns(self):
        out = turns(self.SINGLE)
        assert len(out) == 2
        assert out[1]["text"] == "later"

    def test_confidence_preserved(self):
        assert turns(self.MULTI)[0]["words"][0]["confidence"] == pytest.approx(0.98)

    def test_comments_ignored(self):
        assert turns(";; a comment\n" + self.MULTI)[0]["text"] == "hello there"

    def test_detect(self):
        assert detect_format(self.MULTI) == "NIST CTM"


class TestTextGrid:
    LONG = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 6
tiers? <exists>
size = 2
item []:
    item [1]:
        class = "IntervalTier"
        name = "alice"
        xmin = 0
        xmax = 6
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 1.5
            text = "good morning"
        intervals [2]:
            xmin = 1.5
            xmax = 3
            text = ""
    item [2]:
        class = "IntervalTier"
        name = "bob"
        xmin = 0
        xmax = 6
        intervals: size = 1
        intervals [1]:
            xmin = 3
            xmax = 4.25
            text = "morning"
'''

    SHORT = '''File type = "ooTextFile"
Object class = "TextGrid"

0
6
<exists>
1
"IntervalTier"
"alice"
0
6
2
0
1.5
"good morning"
1.5
3
""
'''

    def test_long_format_tiers_are_speakers(self):
        out = turns(self.LONG)
        assert [t["speaker"] for t in out] == ["alice", "bob"]

    def test_long_format_times(self):
        out = turns(self.LONG)
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == 1.5
        assert out[1]["start"] == 3.0

    def test_empty_intervals_skipped(self):
        # The silences are most of a TextGrid; they are not turns.
        assert len(turns(self.LONG)) == 2

    def test_turns_sorted_chronologically(self):
        out = turns(self.LONG)
        assert out[0]["start"] <= out[1]["start"]

    def test_short_format(self):
        out = turns(self.SHORT)
        assert len(out) == 1
        assert out[0]["text"] == "good morning"
        assert out[0]["speaker"] == "alice"
        assert out[0]["end"] == 1.5

    def test_short_format_multiple_tiers(self):
        # The token walk has to find the next tier header after consuming a
        # tier's intervals, which is where positional parsing usually breaks.
        short_two_tiers = self.SHORT.replace("\n1\n", "\n2\n", 1) + (
            '"IntervalTier"\n"bob"\n0\n6\n1\n3\n4.25\n"morning"\n'
        )
        out = turns(short_two_tiers)
        assert [t["speaker"] for t in out] == ["alice", "bob"]
        assert out[1]["start"] == 3.0

    def test_detect(self):
        assert detect_format(self.LONG) == "Praat TextGrid"


class TestEAF:
    EAF = '''<?xml version="1.0" encoding="UTF-8"?>
<ANNOTATION_DOCUMENT AUTHOR="" DATE="2026-01-01" FORMAT="3.0" VERSION="3.0">
  <HEADER MEDIA_FILE="" TIME_UNITS="milliseconds">
    <MEDIA_DESCRIPTOR MEDIA_URL="file:///data/session.wav"
                      RELATIVE_MEDIA_URL="./session.wav" MIME_TYPE="audio/x-wav"/>
  </HEADER>
  <TIME_ORDER>
    <TIME_SLOT TIME_SLOT_ID="ts1" TIME_VALUE="0"/>
    <TIME_SLOT TIME_SLOT_ID="ts2" TIME_VALUE="1500"/>
    <TIME_SLOT TIME_SLOT_ID="ts3" TIME_VALUE="3000"/>
    <TIME_SLOT TIME_SLOT_ID="ts4" TIME_VALUE="4250"/>
  </TIME_ORDER>
  <TIER TIER_ID="utterance" PARTICIPANT="alice" LINGUISTIC_TYPE_REF="default">
    <ANNOTATION>
      <ALIGNABLE_ANNOTATION ANNOTATION_ID="a1" TIME_SLOT_REF1="ts1" TIME_SLOT_REF2="ts2">
        <ANNOTATION_VALUE>good morning</ANNOTATION_VALUE>
      </ALIGNABLE_ANNOTATION>
    </ANNOTATION>
    <ANNOTATION>
      <ALIGNABLE_ANNOTATION ANNOTATION_ID="a2" TIME_SLOT_REF1="ts3" TIME_SLOT_REF2="ts4">
        <ANNOTATION_VALUE>how are you</ANNOTATION_VALUE>
      </ALIGNABLE_ANNOTATION>
    </ANNOTATION>
  </TIER>
  <TIER TIER_ID="gloss" PARTICIPANT="alice" PARENT_REF="utterance">
    <ANNOTATION>
      <REF_ANNOTATION ANNOTATION_ID="a3" ANNOTATION_REF="a1">
        <ANNOTATION_VALUE>greeting</ANNOTATION_VALUE>
      </REF_ANNOTATION>
    </ANNOTATION>
  </TIER>
</ANNOTATION_DOCUMENT>'''

    def test_time_slots_resolved_from_milliseconds(self):
        out = turns(self.EAF)
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == 1.5

    def test_participant_is_speaker(self):
        assert turns(self.EAF)[0]["speaker"] == "alice"

    def test_ref_annotation_borrows_parent_timing(self):
        out = turns(self.EAF)
        gloss = [t for t in out if t["text"] == "greeting"]
        assert len(gloss) == 1
        assert gloss[0]["start"] == 0.0
        assert gloss[0]["end"] == 1.5

    def test_media_descriptor_becomes_audio(self):
        assert normalize_transcript(self.EAF)["audio"] == "./session.wav"

    def test_detect(self):
        assert detect_format(self.EAF) == "ELAN EAF"


# ---------------------------------------------------------------------------
# Cross-cutting behavior
# ---------------------------------------------------------------------------

class TestNoRegressionOnEnrichment:
    """``words``/``confidence`` must be absent, not empty, when unavailable."""

    def test_plain_whisper_turn_has_no_optional_keys(self):
        out = turns({"segments": [{"start": 0, "end": 1, "text": "hi"}]})
        assert set(out[0]) == {"turn_id", "speaker", "start", "end", "text"}

    def test_whisper_word_timestamps_passed_through(self):
        raw = {"segments": [{
            "start": 0, "end": 1, "text": "hi there",
            "words": [{"word": "hi", "start": 0.0, "end": 0.3, "probability": 0.9},
                      {"word": "there", "start": 0.3, "end": 0.9}],
        }]}
        out = turns(raw)
        assert [w["word"] for w in out[0]["words"]] == ["hi", "there"]
        assert out[0]["words"][0]["confidence"] == pytest.approx(0.9)


class TestStableIdsAcrossNewFormats:
    """turn_id is the persistence key; it must not drift between reloads."""

    @pytest.mark.parametrize("raw", [
        TestJSON3.RAW,
        TestASS.ASS,
        TestWhisperCpp.RAW,
        TestAWSTranscribe.MODERN,
        TestDeepgram.WITH_UTTERANCES,
        TestAssemblyAI.RAW,
        TestRevAI.RAW,
        TestCTM.MULTI,
        TestTextGrid.LONG,
        TestEAF.EAF,
    ])
    def test_ids_are_deterministic_and_indexed(self, raw):
        first = [t["turn_id"] for t in turns(raw)]
        second = [t["turn_id"] for t in turns(raw)]
        assert first == second
        assert first == [f"t{i}" for i in range(len(first))]


class TestExplicitKeysStillWin:
    """A configured container key must beat vendor sniffing."""

    def test_turns_key_beats_vendor_shape(self):
        raw = {
            "turns": [{"speaker": "host", "start": 0, "end": 1, "text": "explicit"}],
            "results": {"channels": [{"alternatives": [{"transcript": "sniffed"}]}]},
        }
        out = turns(raw)
        assert len(out) == 1
        assert out[0]["text"] == "explicit"
