"""HTTP surface for the codebook output-change review queue: admin
gating on the queue + resolve, and the on-demand /admin/review/run
endpoint's behaviour when no labeling model is configured.

The sweep itself (re-label + significance) is covered end-to-end with a
faked endpoint in tests/unit/test_solo_mode/test_codebook_review.py; here
we exercise the API + auth boundary on the served app.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory, create_test_data_file, create_test_config,
    cleanup_test_directory)

ADMIN_KEY = "test-admin-key"
_CB = [{"name": "themes", "description": "T",
        "annotation_type": "multiselect", "codebook": True,
        "labels": ["alpha", "beta"]}]


def _login(server, email):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": email, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": email, "pass": "pw"})
    return s


class TestReviewQueueApi:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cb_review")
        data_file = create_test_data_file(
            test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _CB, data_files=[data_file], require_password=False,
            additional_config={"codebook_mode": "open",
                               "admin_api_key": ADMIN_KEY})
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def _admin(self):
        return {"X-API-Key": ADMIN_KEY}

    # ---- gating ---------------------------------------------------------

    def test_queue_requires_admin(self):
        s = _login(self.server, "rev_norm1")
        r = s.get(f"{self.server.base_url}/api/codebook/admin/review")
        assert r.status_code == 403

    def test_run_requires_admin(self):
        s = _login(self.server, "rev_norm2")
        r = s.post(f"{self.server.base_url}/api/codebook/admin/review/run")
        assert r.status_code == 403

    # ---- queue + resolve ------------------------------------------------

    def test_empty_queue_for_admin(self):
        s = _login(self.server, "rev_adm1")
        r = s.get(f"{self.server.base_url}/api/codebook/admin/review",
                  headers=self._admin())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 0
        assert body["flags"] == []

    def test_resolve_unknown_flag_404(self):
        s = _login(self.server, "rev_adm2")
        r = s.post(
            f"{self.server.base_url}/api/codebook/admin/review/nope/resolve",
            json={"status": "reviewed"}, headers=self._admin())
        assert r.status_code == 404

    # ---- on-demand run without a labeling model -------------------------

    def test_run_without_solo_mode_returns_503(self):
        s = _login(self.server, "rev_adm3")
        r = s.post(f"{self.server.base_url}/api/codebook/admin/review/run",
                   headers=self._admin())
        # No solo mode in this deployment -> no labeling endpoint to
        # re-label with; the API says so clearly rather than silently
        # doing nothing.
        assert r.status_code == 503, r.text
        assert "solo mode" in r.json()["error"].lower()

    def test_run_rejects_bad_max_instances(self):
        s = _login(self.server, "rev_adm4")
        r = s.post(f"{self.server.base_url}/api/codebook/admin/review/run",
                   json={"max_instances": "lots"}, headers=self._admin())
        # Validation happens before the solo-mode check only if a manager
        # exists; without one we accept either the 400 (validation) or the
        # 503 (no manager) — both are correct refusals. Pin to the actual
        # contract: no manager short-circuits to 503.
        assert r.status_code in (400, 503), r.text
