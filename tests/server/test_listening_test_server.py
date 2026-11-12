"""
listening_test over HTTP: the plan route names no condition, every slot's
audio is served (anchors made from the reference), sessions are required,
and a saved MUSHRA answer survives a reload of the item.
"""

import json
import os
import shutil
from pathlib import Path

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "audio" / "listening-test-mushra"


@pytest.fixture(scope="module")
def lt_server(request):
    d = create_test_directory("listening_test_server")
    for sub in ("media", "data"):
        shutil.copytree(EXAMPLE / sub, os.path.join(d, sub))
    import yaml
    cfg = yaml.safe_load((EXAMPLE / "config.yaml").read_text())
    # Pinned: the in-process harness resolves a relative one against the cwd.
    cfg["output_annotation_dir"] = os.path.join(d, "annotation_output")
    with open(os.path.join(d, "config.yaml"), "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    server = FlaskTestServer(config=os.path.join(d, "config.yaml"))
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def _login(base, name):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
    return s


def test_page_loads_player(lt_server):
    s = _login(lt_server.base_url, "lt_page")
    html = s.get(f"{lt_server.base_url}/annotate", timeout=5).text
    assert 'data-annotation-type="listening_test"' in html
    assert "listening-test.js" in html and "listening-test.css" in html


def test_plan_is_blind_and_audio_is_served(lt_server):
    base = lt_server.base_url
    s = _login(base, "lt_plan")
    s.get(f"{base}/annotate", timeout=5)
    r = s.get(f"{base}/api/listening/plan", params={"schema": "quality", "instance_id": "excerpt_1"},
              timeout=5)
    assert r.status_code == 200
    view = r.json()
    text = json.dumps(view)
    for secret in ("lowrate", "coarse", "hidden_reference", "anchor", "chord_"):
        assert secret not in text, secret
    assert len(view["slots"]) == 5
    for url in [view["reference"]] + [x["url"] for x in view["slots"]]:
        audio = s.get(f"{base}{url}", timeout=10)
        assert audio.status_code == 200 and audio.content[:4] == b"RIFF", url
        assert "Content-Disposition" not in audio.headers


def test_session_required(lt_server):
    r = requests.get(f"{lt_server.base_url}/api/listening/plan",
                     params={"schema": "quality", "instance_id": "excerpt_1"}, timeout=5)
    assert r.status_code == 401


def test_answer_round_trips(lt_server):
    base = lt_server.base_url
    s = _login(base, "lt_save")
    s.get(f"{base}/annotate", timeout=5)
    answer = {"ratings": {"s1": 100, "s2": 40, "s3": 20, "s4": 70, "s5": 55},
              "played": ["ref", "s1", "s2", "s3", "s4", "s5"]}
    r = s.post(f"{base}/updateinstance", json={
        "instance_id": "excerpt_1", "annotations": {"quality:::quality": json.dumps(answer)},
        "span_annotations": []}, timeout=5)
    assert r.status_code == 200, r.text
    from bs4 import BeautifulSoup
    html = s.get(f"{base}/annotate", timeout=5).text
    field = BeautifulSoup(html, "html.parser").find("input", class_="listening-test-input")
    assert json.loads(field["value"])["ratings"]["s2"] == 40


def _pcm(wav_bytes):
    import io
    import wave
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.readframes(w.getnframes())


def test_no_channel_names_a_slot(lt_server):
    """Audit 96 L1/L2: the item JSON, /media/, hashes and cache headers must
    not tell a participant which slot holds which file."""
    import hashlib
    base = lt_server.base_url
    s = _login(base, "lt_blind")
    html = s.get(f"{base}/annotate", timeout=5).text
    for secret in ("chord_", "lowrate", "coarse", "/media/"):
        assert secret not in html, secret
    for name in ("chord_ref.wav", "chord_lowrate.wav", "chord_coarse.wav"):
        assert s.get(f"{base}/media/{name}", timeout=5).status_code == 404, name
    view = s.get(f"{base}/api/listening/plan",
                 params={"schema": "quality", "instance_id": "excerpt_1"}, timeout=5).json()
    media = EXAMPLE / "media"
    file_hashes = {hashlib.md5(p.read_bytes()).hexdigest() for p in media.glob("*.wav")}
    slot_hashes, pcm = set(), {}
    for url in [view["reference"]] + [x["url"] for x in view["slots"]]:
        r = s.get(f"{base}{url}", timeout=10)
        assert "ETag" not in r.headers and "Last-Modified" not in r.headers
        digest = hashlib.md5(r.content).hexdigest()
        assert digest not in file_hashes and digest not in slot_hashes
        slot_hashes.add(digest)
        pcm[url] = _pcm(r.content)
    # The audio itself is untouched: the hidden reference decodes to the reference.
    ref = (media / "chord_ref.wav").read_bytes()
    assert sum(1 for v in pcm.values() if v == _pcm(ref)) == 2
