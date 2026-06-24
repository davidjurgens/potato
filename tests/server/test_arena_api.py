"""
Server integration test for the multi-model arena. A stub endpoint builder is
injected into the in-process manager so the test is hermetic (no real LLMs).
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class _StubEndpoint:
    def __init__(self, label):
        self.label = label
    def query(self, prompt, output_format=None):
        return f"[{self.label}] {prompt[:40]}"


@pytest.fixture(scope="class", autouse=True)
def flask_server(request):
    schemes = [{"annotation_type": "radio", "name": "ok",
                "description": "ok?", "labels": ["yes", "no"]}]
    extra = {"arena": {"enabled": True, "models": [
        {"label": "Alpha", "endpoint_type": "stub", "model": "a"},
        {"label": "Beta", "endpoint_type": "stub", "model": "b"},
    ]}}
    with TestConfigManager(
        "arena_api", schemes,
        additional_config=extra, admin_api_key="test-admin-api-key",
    ) as test_config:
        server = FlaskTestServer(port=9066, config_file=test_config.config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        # Inject the stub endpoint builder into the in-process arena singleton.
        from potato.arena.manager import get_arena_manager
        mgr = get_arena_manager()
        assert mgr is not None
        mgr.endpoint_builder = lambda m: _StubEndpoint(m.label)
        request.cls.server = server
        yield server
        server.stop()


class TestArenaAPI:
    def _admin(self):
        s = requests.Session()
        s.headers.update({"X-API-Key": self.server.admin_api_key})
        return s, self.server.base_url

    def test_run_returns_all_models(self):
        s, base = self._admin()
        r = s.post(f"{base}/admin/arena/api/run", json={"prompt": "what is 2+2?"})
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert [x["label"] for x in results] == ["Alpha", "Beta"]
        assert results[0]["response"].startswith("[Alpha]")

    def test_run_empty_prompt_400(self):
        s, base = self._admin()
        r = s.post(f"{base}/admin/arena/api/run", json={"prompt": "  "})
        assert r.status_code == 400

    def test_preference_updates_leaderboard(self):
        s, base = self._admin()
        s.post(f"{base}/admin/arena/api/run", json={"prompt": "q"})
        r = s.post(f"{base}/admin/arena/api/preference",
                   json={"prompt": "q", "winner": "Alpha"})
        assert r.status_code == 200, r.text
        lb = {row["label"]: row for row in r.json()["leaderboard"]}
        assert lb["Alpha"]["wins"] >= 1
        assert lb["Alpha"]["comparisons"] >= 1

    def test_preference_requires_winner(self):
        s, base = self._admin()
        r = s.post(f"{base}/admin/arena/api/preference", json={"prompt": "q"})
        assert r.status_code == 400

    def test_page_and_admin_guard(self):
        s, base = self._admin()
        assert s.get(f"{base}/admin/arena").status_code == 200
        assert requests.post(f"{base}/admin/arena/api/run",
                             json={"prompt": "x"}).status_code in (401, 403)

    def test_leaderboard_has_elo_and_bt(self):
        s, base = self._admin()
        s.post(f"{base}/admin/arena/api/run", json={"prompt": "rank me"})
        s.post(f"{base}/admin/arena/api/preference",
               json={"prompt": "rank me", "winner": "Alpha"})
        lb = {row["label"]: row for row in
              s.get(f"{base}/admin/arena/api/leaderboard").json()["leaderboard"]}
        # Both opponent-strength-aware metrics are present after a comparison.
        assert lb["Alpha"]["elo"] is not None and lb["Beta"]["elo"] is not None
        assert lb["Alpha"]["elo"] > lb["Beta"]["elo"]
        assert lb["Alpha"]["bt_score"] >= lb["Beta"]["bt_score"]

    def test_export_dpo_returns_pairs(self):
        s, base = self._admin()
        s.post(f"{base}/admin/arena/api/run", json={"prompt": "dpo please"})
        s.post(f"{base}/admin/arena/api/preference",
               json={"prompt": "dpo please", "winner": "Alpha"})
        r = s.get(f"{base}/admin/arena/api/export_dpo")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["count"] >= 1
        pair = data["pairs"][0]
        assert pair["chosen"].startswith("[Alpha]")
        assert pair["rejected"].startswith("[Beta]")

    def test_export_dpo_admin_guarded(self):
        assert requests.get(f"{self.server.base_url}/admin/arena/api/export_dpo"
                            ).status_code in (401, 403)
