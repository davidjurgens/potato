"""One recording per utterance has no shared timeline, and is not offered one.

`audio_from_segments` returns the first segment carrying an audio url and
stops. Its docstring is explicit about the case it was written for -- some
sources repeat one media URL on every row (SPoRC's `mp3_url`) -- and nothing
checked that the rows agreed.

They disagree when there is one file per turn, which is how telephony
pipelines, turn-based TTS evaluations and most conversational agent logs store
audio. Measured on a four-turn rebooking call with a recording per turn:

    shared player src   mono44.wav   (turn 1's file)
    real duration       5.00s
    turn seek targets   0.0  3.4  6.3  9.1
    seeking past EOF    turns 3 and 4

Two turns played silence past the end of a file that was not theirs, the other
turns' files were never loaded, all four turns rendered, `--strict` passed and
the log was silent. An annotator correcting an ASR transcript would have done
turn 2 against the wrong audio and turns 3 and 4 against nothing.

The turns still render, because reading them is useful. What goes is the
transport bar and the per-turn buttons -- the part that was lying -- plus a
notice naming `speech_transcript`, which is the display for this shape.
"""

import logging
import re

import pytest

from potato.server_utils.displays.registry import display_registry
from potato.server_utils.transcripts import audio_sources_from_segments


def turns(*urls):
    return {"turns": [
        {"speaker": "caller" if i % 2 == 0 else "agent",
         "text": f"turn {i}", "audio_url": url,
         "start": i * 3.0, "end": i * 3.0 + 2.5}
        for i, url in enumerate(urls)]}


def render(data):
    return display_registry.render(
        "audio_dialogue", {"type": "audio_dialogue", "key": "call"}, data)


SHARED = turns("/m/call.wav", "/m/call.wav", "/m/call.wav", "/m/call.wav")
PER_TURN = turns("/m/t1.wav", "/m/t2.wav", "/m/t3.wav", "/m/t4.wav")


class TestTheSourcesAreCounted:

    def test_one_repeated_url_is_one_source(self):
        assert audio_sources_from_segments(SHARED["turns"]) == ["/m/call.wav"]

    def test_a_file_per_turn_is_many(self):
        assert audio_sources_from_segments(PER_TURN["turns"]) == [
            "/m/t1.wav", "/m/t2.wav", "/m/t3.wav", "/m/t4.wav"]

    def test_order_is_first_seen(self):
        segments = [{"audio_url": "/m/b.wav"}, {"audio_url": "/m/a.wav"},
                    {"audio_url": "/m/b.wav"}]
        assert audio_sources_from_segments(segments) == ["/m/b.wav", "/m/a.wav"]

    @pytest.mark.parametrize("key", ["mp3_url", "mp3url", "audio_url", "audio",
                                     "url", "media_url"])
    def test_every_spelling_is_read(self, key):
        assert audio_sources_from_segments([{key: "/m/a.wav"}]) == ["/m/a.wav"]

    def test_segments_with_no_audio_yield_nothing(self):
        assert audio_sources_from_segments([{"text": "hi"}, "not a dict"]) == []

    def test_the_single_source_helper_still_returns_the_first(self):
        from potato.server_utils.transcripts import audio_from_segments

        assert audio_from_segments(PER_TURN["turns"]) == "/m/t1.wav"


class TestAPerTurnCorpusGetsNoPlayer:

    def test_the_transport_bar_is_gone(self):
        assert "<audio" not in render(PER_TURN), (
            "the player loaded turn 1's file and every other turn seeked into "
            "a recording that was not theirs")

    def test_the_per_turn_buttons_are_gone(self):
        assert not re.search(r'class="ad-play"', render(PER_TURN)), (
            "a button that seeks a meaningless offset is worse than no button")

    def test_a_notice_says_why(self):
        html = render(PER_TURN)
        assert "ad-per-turn-notice" in html
        assert "speech_transcript" in html, (
            "the notice has to name the display that handles this shape")

    def test_the_notice_is_a_status_region(self):
        assert 'role="status"' in render(PER_TURN)

    def test_every_turn_still_renders(self):
        """Reading the transcript is useful even without playback."""
        html = render(PER_TURN)
        for i in range(4):
            assert f"turn {i}" in html

    def test_the_speakers_still_render(self):
        html = render(PER_TURN)
        assert "caller" in html and "agent" in html

    def test_it_is_reported_in_the_log(self, caplog):
        with caplog.at_level(logging.WARNING):
            render(PER_TURN)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "4 different audio files" in message
        assert "speech_transcript" in message


class TestASharedRecordingIsUnaffected:
    """The control arm. Suppressing playback for everyone would pass every
    test above and break the podcast case the display exists for."""

    def test_the_player_is_still_there(self):
        assert "<audio" in render(SHARED)

    def test_the_per_turn_buttons_are_still_there(self):
        assert len(re.findall(r'class="ad-play"', render(SHARED))) == 4

    def test_no_notice_is_shown(self):
        assert "ad-per-turn-notice" not in render(SHARED)

    def test_nothing_is_logged(self, caplog):
        with caplog.at_level(logging.WARNING):
            render(SHARED)
        assert "different audio files" not in " ".join(
            r.getMessage() for r in caplog.records)

    def test_a_transcript_with_no_audio_at_all_is_unaffected(self):
        data = {"turns": [{"speaker": "a", "text": "hi", "start": 0, "end": 1}]}
        html = render(data)
        assert "ad-per-turn-notice" not in html
        assert "hi" in html
