"""
type: headphone_check over HTTP. The page runs on the runtime layer (strict
CSP, the finish route), a failed check screens the participant out by its
derived exit_when, a passed one continues, and a later page can test
`<page>_passed` with show_when.
"""

import json
import os
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)

HEADERS = {"X-Potato-Navigation": "1"}


@pytest.fixture(scope="module")
def hc_server(request):
    d = create_test_directory("headphone_check_server")
    data = create_test_data_file(d, [{"id": "1", "text": "hello"}])
    survey = os.path.join(d, "after.json")
    with open(survey, "w") as f:
        json.dump([{"name": "comment", "annotation_type": "text", "description": "Anything?"}], f)
    config = create_test_config(
        d,
        annotation_schemes=[{"name": "rating", "annotation_type": "radio",
                             "labels": ["good", "bad"], "description": "Rate."}],
        data_files=[data],
        phases={
            "order": ["headphones", "after", "annotation"],
            "headphones": {"type": "headphone_check", "trials": 4, "pass_threshold": 3},
            "after": {"type": "prestudy", "file": survey,
                      "show_when": [{"schema": "headphones_passed", "operator": "equals",
                                     "value": "yes"}]},
        })
    server = FlaskTestServer(config=config)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def _login(base, name):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
    return s


def _cfg(s, base):
    r = s.get(f"{base}/", timeout=5)
    m = re.search(r'id="potato-runtime-config">(.*?)</script>', r.text, re.S)
    return r, (json.loads(m.group(1)) if m else None)


def _plan(name):
    """The server's answers for this participant's run (FlaskTestServer is
    in-process, so the state is readable here)."""
    from potato.user_state_management import get_user_state_manager
    rec = get_user_state_manager().get_user_state(name).flow_record
    return rec["runtimes"]["headphones"]["hc_plan"]["trials"]


def _fetch_all(s, base, cfg):
    for i in range(cfg["runtime"]["trials"]):
        r = s.get(f"{base}{cfg['runtime']['stimulus']}{i}.wav", timeout=5)
        assert r.status_code == 200 and r.headers["Content-Type"] == "audio/wav", r.status_code


def _post(s, base, cfg, trials):
    return s.post(f"{base}{cfg['endpoints']['finish']}", headers=HEADERS, timeout=5,
                  json={"page": cfg["page"], "run_id": cfg["run_id"], "trials": trials})


def _finish(s, base, cfg, correct, name):
    """Fetch every trial's sounds, as the page does, then answer the first
    `correct` trials right and the rest wrong."""
    _fetch_all(s, base, cfg)
    plan = _plan(name)
    trials = [{"index": i, "test": row["test"], "trial": row["trial"],
               "response": row["target"] if i < correct else row["target"] % 3 + 1}
              for i, row in enumerate(plan)]
    return _post(s, base, cfg, trials)


def test_page_is_a_runtime_page(hc_server):
    s = _login(hc_server.base_url, "hc_page")
    r, cfg = _cfg(s, hc_server.base_url)
    assert cfg["kind"] == "headphone_check"
    assert cfg["runtime"] == {"test": "huggins", "trials": 4,
                              "stimulus": "/runtime/headphones/stimulus/",
                              "spacing_s": 1.5, "interval_s": 1.0}
    # The page is never told the answers.
    assert "target" not in json.dumps(cfg)
    assert "runtime-boot-headphone.js" in r.text and "runtime-headphone.css" in r.text
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


def test_failing_screens_out(hc_server):
    s = _login(hc_server.base_url, "hc_fail")
    _, cfg = _cfg(s, hc_server.base_url)
    assert _finish(s, hc_server.base_url, cfg, correct=2, name="hc_fail").status_code == 200
    html = s.get(f"{hc_server.base_url}/", timeout=5).text
    assert 'id="screened-out"' in html and "headphones" in html.lower()


def test_passing_continues_to_the_gated_page(hc_server):
    s = _login(hc_server.base_url, "hc_pass")
    _, cfg = _cfg(s, hc_server.base_url)
    assert _finish(s, hc_server.base_url, cfg, correct=3, name="hc_pass").status_code == 200
    html = s.get(f"{hc_server.base_url}/", timeout=5).text
    assert 'data-schema-name="comment"' in html
    from potato.user_state_management import get_user_state_manager
    rec = get_user_state_manager().get_user_state("hc_pass").flow_record
    assert rec["runtime_answers"] == {"headphones_passed": "yes", "headphones_correct": 3}


def test_item_text_is_withheld_before_the_check_and_after_screen_out(hc_server):
    """Audit 96 R12: /api/spans/<id> returned the item's text on the
    headphone page and after a screen-out."""
    base = hc_server.base_url
    s = _login(base, "hc_spans")
    _, cfg = _cfg(s, base)
    r = s.get(f"{base}/api/spans/1", timeout=5)
    assert r.status_code == 403 and "hello" not in r.text
    _finish(s, base, cfg, correct=1, name="hc_spans")
    r = s.get(f"{base}/api/spans/1", timeout=5)
    assert r.status_code == 403 and "hello" not in r.text


def _answers(name):
    from potato.user_state_management import get_user_state_manager
    return get_user_state_manager().get_user_state(name).flow_record["runtime_answers"]


def test_a_posted_target_does_not_pass_the_check(hc_server):
    """Audit 96 R13: trials naming their own target, with the response equal
    to it, gave headphones_passed=yes."""
    base = hc_server.base_url
    s = _login(base, "hc_forge")
    _, cfg = _cfg(s, base)
    forged = [{"test": "huggins", "trial": i + 1, "target": 1, "response": 1,
               "correct": True, "scored": True} for i in range(4)]
    assert _post(s, base, cfg, forged).status_code == 200
    assert _answers("hc_forge") == {"headphones_passed": "no", "headphones_correct": 0}
    assert 'id="screened-out"' in s.get(f"{base}/", timeout=5).text


def test_an_answer_to_a_sound_never_fetched_does_not_count(hc_server):
    base = hc_server.base_url
    s = _login(base, "hc_unheard")
    _, cfg = _cfg(s, base)
    # Fetch only the first sound, then answer all four with the server's targets.
    assert s.get(f"{base}{cfg['runtime']['stimulus']}0.wav", timeout=5).status_code == 200
    plan = _plan("hc_unheard")
    trials = [{"index": i, "response": row["target"]} for i, row in enumerate(plan)]
    assert _post(s, base, cfg, trials).status_code == 200
    assert _answers("hc_unheard")["headphones_correct"] == 1


def test_a_repeated_answer_counts_once(hc_server):
    base = hc_server.base_url
    s = _login(base, "hc_repeat")
    _, cfg = _cfg(s, base)
    _fetch_all(s, base, cfg)
    target = _plan("hc_repeat")[0]["target"]
    trials = [{"index": 0, "response": r} for r in (1, 2, 3)] * 2
    assert _post(s, base, cfg, trials).status_code == 200
    # Only the first answer to trial 0 is scored.
    assert _answers("hc_repeat")["headphones_correct"] == int(target == 1)


def test_a_stimulus_outside_the_run_is_not_served(hc_server):
    base = hc_server.base_url
    s = _login(base, "hc_range")
    _, cfg = _cfg(s, base)
    assert s.get(f"{base}{cfg['runtime']['stimulus']}4.wav", timeout=5).status_code == 404
    assert requests.get(f"{base}{cfg['runtime']['stimulus']}0.wav", timeout=5).status_code == 404


def _channels(data):
    import io
    import wave
    import numpy as np
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, 16000)
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2)
    return pcm[:, 0].astype(float), pcm[:, 1].astype(float)


def _interval(x, i):
    return x[int(i * 1.5 * 16000):int((i * 1.5 + 1.0) * 16000)]


def test_the_huggins_sound_inverts_the_band_in_the_target_only(hc_server):
    import numpy as np
    base = hc_server.base_url
    s = _login(base, "hc_huggins")
    _, cfg = _cfg(s, base)
    left, right = _channels(s.get(f"{base}{cfg['runtime']['stimulus']}0.wav", timeout=5).content)
    assert len(left) == 4 * 16000
    target = _plan("hc_huggins")[0]["target"]
    for i in range(3):
        L, R = _interval(left, i), _interval(right, i)
        freqs = np.fft.rfftfreq(len(L), 1 / 16000)
        band = (freqs > 600 * 0.95) & (freqs < 600 * 1.05)
        # In-band, the channels are anti-correlated in the target and equal elsewhere.
        corr = np.real(np.sum(np.fft.rfft(L)[band] * np.conj(np.fft.rfft(R)[band])))
        if i + 1 == target:
            assert corr < 0
        else:
            assert np.array_equal(L, R)


def test_the_antiphase_sounds_follow_woods_et_al():
    """Unit check of the generator: the quiet tone is 6 dB down, the
    antiphase tone has right = -left, the standard is diotic."""
    import numpy as np
    from potato.runtimes.adapters.headphone_check import _tone
    std, quiet, anti = _tone("standard"), _tone("quiet"), _tone("antiphase")
    assert np.array_equal(std[0], std[1])
    assert np.allclose(anti[1], -anti[0])
    ratio = np.sqrt(np.mean(quiet[0] ** 2) / np.mean(std[0] ** 2))
    assert 20 * np.log10(ratio) == pytest.approx(-6.02, abs=0.05)
