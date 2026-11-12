"""HTTP-level concurrency tests for the living-document content API (Phase 6).

The pure-Python service is covered by
`tests/unit/test_codebook_content_service_concurrency.py`; this suite proves
the same guarantees survive the full request path (blueprint routing, session
auth, JSON (de)serialization, the 409 body contract) against a real served
Flask app with concurrent clients:

  * lost-update prevention — two real HTTP clients at the same base version,
    one 200 + one 409-with-rebase, then the loser rebases and lands;
  * different-scope parallelism — concurrent PUTs to two codes both 200;
  * threaded same-scope hammer — exactly one 200 per version step, the rest
    409, final live content equals the winner, no torn state.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory, create_test_data_file, create_test_config,
    cleanup_test_directory)

_CB = [{"name": "themes", "description": "T",
        "annotation_type": "multiselect", "codebook": True,
        "labels": ["alpha", "beta"]}]


def _session(server, email):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": email, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": email, "pass": "pw"})
    return s


class TestContentApiConcurrency:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cb_content_concurrency")
        data_file = create_test_data_file(
            test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _CB, data_files=[data_file], require_password=False,
            additional_config={"codebook_mode": "open"})
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def _url(self, path):
        return f"{self.server.base_url}/api/codebook{path}"

    def _mk(self, s, name):
        r = s.post(self._url(""), json={"name": name})
        assert r.status_code == 200, r.text
        return r.json()["code"]["id"]

    def _put(self, s, cid, body, base, **extra):
        payload = {"code_id": cid, "base_version": base,
                   "blocks": [{"block_type": "definition", "body_md": body}]}
        payload.update(extra)
        return s.put(self._url("/blocks"), json=payload)

    # ---- lost-update over HTTP -----------------------------------------

    def test_two_http_clients_one_409_then_rebase(self):
        admin = _session(self.server, "cc_admin")
        cid = self._mk(admin, "http race code")
        # two independent clients/sessions, both at base 0
        ca = _session(self.server, "cc_a")
        cb = _session(self.server, "cc_b")
        barrier = threading.Barrier(2)
        results = {}

        def writer(tag, sess, body):
            barrier.wait()
            results[tag] = self._put(sess, cid, body, 0)

        ta = threading.Thread(target=writer, args=("A", ca, "alpha"))
        tb = threading.Thread(target=writer, args=("B", cb, "beta"))
        ta.start(); tb.start(); ta.join(); tb.join()

        codes = sorted(r.status_code for r in results.values())
        assert codes == [200, 409], {k: v.status_code for k, v in
                                     results.items()}
        loser = next(r for r in results.values() if r.status_code == 409)
        body = loser.json()
        assert body["error"] == "stale_content"
        assert body["current_version"] == 1
        winning_body = body["current_blocks"][0]["body_md"]

        # loser rebases onto current_version and now succeeds
        loser_sess = ca if results["A"].status_code == 409 else cb
        rebased = self._put(loser_sess, cid, "rebased value", 1)
        assert rebased.status_code == 200, rebased.text
        assert rebased.json()["scope_version"] == 2

        live = admin.get(self._url("/blocks"),
                         params={"code_id": cid}).json()
        assert live["blocks"][0]["body_md"] == "rebased value"
        assert winning_body in ("alpha", "beta")

    # ---- different-scope parallelism over HTTP -------------------------

    def test_two_codes_put_concurrently(self):
        admin = _session(self.server, "cc_admin2")
        c1 = self._mk(admin, "http code one")
        c2 = self._mk(admin, "http code two")
        s1 = _session(self.server, "cc_p1")
        s2 = _session(self.server, "cc_p2")
        start = threading.Barrier(2)
        out = {}

        def writer(key, sess, cid, body):
            start.wait()
            out[key] = self._put(sess, cid, body, 0)

        t1 = threading.Thread(target=writer, args=("1", s1, c1, "one"))
        t2 = threading.Thread(target=writer, args=("2", s2, c2, "two"))
        t1.start(); t2.start(); t1.join(); t2.join()
        assert out["1"].status_code == 200, out["1"].text
        assert out["2"].status_code == 200, out["2"].text
        assert out["1"].json()["scope_version"] == 1
        assert out["2"].json()["scope_version"] == 1

    # ---- threaded same-scope hammer over HTTP --------------------------

    def test_http_hammer_single_round_one_winner(self):
        admin = _session(self.server, "cc_admin3")
        cid = self._mk(admin, "http hammer code")
        N = 8
        sessions = [_session(self.server, f"cc_h{i}") for i in range(N)]
        barrier = threading.Barrier(N)

        def writer(i):
            barrier.wait()
            return self._put(sessions[i], cid, f"body-{i}", 0).status_code

        with ThreadPoolExecutor(max_workers=N) as ex:
            codes = list(ex.map(writer, range(N)))

        assert codes.count(200) == 1, codes
        assert codes.count(409) == N - 1
        live = admin.get(self._url("/blocks"),
                         params={"code_id": cid}).json()
        assert live["scope_version"] == 1
        assert len(live["blocks"]) == 1

    def test_http_hammer_with_retry_converges(self):
        admin = _session(self.server, "cc_admin4")
        cid = self._mk(admin, "http converge code")
        N = 6
        sessions = [_session(self.server, f"cc_c{i}") for i in range(N)]
        landed = []
        lock = threading.Lock()

        def writer(i):
            sess = sessions[i]
            for _ in range(50):  # bounded retry loop
                cur = sess.get(self._url("/blocks"),
                               params={"code_id": cid}).json()["scope_version"]
                r = self._put(sess, cid, f"writer-{i}", cur)
                if r.status_code == 200:
                    with lock:
                        landed.append(i)
                    return
                assert r.status_code == 409, r.text
            pytest.fail(f"writer {i} never converged")

        with ThreadPoolExecutor(max_workers=N) as ex:
            list(ex.map(writer, range(N)))

        assert sorted(landed) == list(range(N))
        live = admin.get(self._url("/blocks"),
                         params={"code_id": cid}).json()
        assert live["scope_version"] == N
        assert len(live["blocks"]) == 1
        hist = admin.get(self._url("/history"),
                         params={"scope_kind": "code", "scope_id": cid}).json()
        assert hist["count"] == N
