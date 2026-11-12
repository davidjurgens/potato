"""Padding keeps audio decodable and makes every response's bytes differ."""

import io
import struct
import wave

from potato.listening import blind
from tests.helpers.test_utils import create_test_directory


def _wav(path, frames=b"\x01\x00\x02\x00" * 50):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(frames)
    return frames


def test_wav_padding_keeps_frames(tmp_path=None):
    d = create_test_directory("listening_blind")
    p = f"{d}/a.wav"
    frames = _wav(p)
    a, b = blind.padded_audio(p), blind.padded_audio(p)
    assert a != b
    with wave.open(io.BytesIO(a)) as w:
        assert w.readframes(w.getnframes()) == frames
    assert struct.unpack("<I", a[4:8])[0] == len(a) - 8


def test_flac_padding_block_is_well_formed():
    streaminfo = bytes([0x80]) + (34).to_bytes(3, "big") + b"\0" * 34   # last-block flag set
    data = b"fLaC" + streaminfo + b"\xff\xf8frames"
    out = blind._pad_flac(data)
    assert out[4] == 0x00                     # STREAMINFO no longer last
    pad_header = out[8 + 34]
    assert pad_header == 0x81                 # PADDING, last
    n = int.from_bytes(out[8 + 35:8 + 38], "big")
    assert out[8 + 38 + n:] == b"\xff\xf8frames"


def test_mp3_gets_an_id3_padding_tag():
    data = b"\xff\xfb\x90\x00" + b"\0" * 20
    out = blind._pad_mp3(data)
    assert out.startswith(b"ID3\x04") and out.endswith(data)
    size = out[6:10]
    n = (size[0] << 21) | (size[1] << 14) | (size[2] << 7) | size[3]
    assert len(out) == 10 + n + len(data)


def test_private_fields_follow_the_scheme():
    cfg = {"annotation_schemes": [{"annotation_type": "listening_test", "name": "q",
                                   "stimuli_field": "clips"}]}
    assert blind.private_item_fields(cfg) == ["clips", "reference", "condition"]
