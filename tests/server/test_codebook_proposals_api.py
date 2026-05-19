"""Phase 2 (C) HTTP surface: admin merge/split, the model->confirm
proposal lifecycle, and admin gating. Link-rewrite correctness is
covered by the unit tests; here we exercise the API + auth boundary
end-to-end on the served app (blueprint, not the discarded module app).
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


class TestProposalsAndAdminOps:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cb_proposals")
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

    def _mk(self, s, name):
        r = s.post(f"{self.server.base_url}/api/codebook",
                   json={"name": name})
        assert r.status_code == 200, r.text
        return r.json()["code"]["id"]

    def _labels(self, s):
        return s.get(f"{self.server.base_url}/api/codebook").json()["labels"]

    # ---- gating ---------------------------------------------------------

    def test_merge_requires_admin(self):
        s = _login(self.server, "norm1")
        r = s.post(f"{self.server.base_url}/api/codebook/admin/merge",
                   json={"src_id": "a", "dst_id": "b"})
        assert r.status_code == 403

    def test_admin_proposals_requires_admin(self):
        s = _login(self.server, "norm2")
        assert s.get(
            f"{self.server.base_url}/api/codebook/admin/proposals"
        ).status_code == 403

    def test_merge_field_validation(self):
        s = _login(self.server, "adm0")
        r = s.post(f"{self.server.base_url}/api/codebook/admin/merge",
                   json={"src_id": "a"}, headers=self._admin())
        assert r.status_code == 400

    # ---- direct admin merge --------------------------------------------

    def test_admin_merge_archives_source(self):
        s = _login(self.server, "adm1")
        a = self._mk(s, "dup one")
        b = self._mk(s, "keep one")
        assert "dup one" in self._labels(s)
        r = s.post(f"{self.server.base_url}/api/codebook/admin/merge",
                   json={"src_id": a, "dst_id": b},
                   headers=self._admin())
        assert r.status_code == 200, r.text
        assert r.json()["dst_id"] == b
        labels = self._labels(s)
        assert "dup one" not in labels and "keep one" in labels

    # ---- proposal lifecycle (model -> human confirm) -------------------

    def test_model_proposal_confirm_executes(self):
        s = _login(self.server, "adm2")
        a = self._mk(s, "prop src")
        b = self._mk(s, "prop dst")
        # model stages a proposal (no admin gate — only queues)
        r = s.post(f"{self.server.base_url}/api/codebook/proposals",
                   json={"op": "merge",
                         "payload": {"src_id": a, "dst_id": b},
                         "actor_kind": "model"})
        assert r.status_code == 201, r.text
        pid = r.json()["proposal"]["id"]
        # appears in the admin pending list
        lst = s.get(
            f"{self.server.base_url}/api/codebook/admin/proposals",
            headers=self._admin()).json()
        assert any(p["id"] == pid for p in lst["proposals"])
        # confirm -> executes the merge, src archived
        c = s.post(
            f"{self.server.base_url}/api/codebook/admin/"
            f"proposals/{pid}/confirm", headers=self._admin())
        assert c.status_code == 200, c.text
        assert "prop src" not in self._labels(s)
        # no longer pending; re-confirm is a 409
        again = s.post(
            f"{self.server.base_url}/api/codebook/admin/"
            f"proposals/{pid}/confirm", headers=self._admin())
        assert again.status_code == 409

    def test_model_proposal_reject_is_noop(self):
        s = _login(self.server, "adm3")
        a = self._mk(s, "rej src")
        b = self._mk(s, "rej dst")
        pid = s.post(
            f"{self.server.base_url}/api/codebook/proposals",
            json={"op": "merge",
                  "payload": {"src_id": a, "dst_id": b},
                  "actor_kind": "model"}).json()["proposal"]["id"]
        r = s.post(
            f"{self.server.base_url}/api/codebook/admin/"
            f"proposals/{pid}/reject", headers=self._admin())
        assert r.status_code == 200
        # nothing changed — src still a live label
        assert "rej src" in self._labels(s)

    def test_changes_log_visible_to_admin(self):
        s = _login(self.server, "adm4")
        a = self._mk(s, "chg a")
        b = self._mk(s, "chg b")
        s.post(f"{self.server.base_url}/api/codebook/admin/merge",
               json={"src_id": a, "dst_id": b}, headers=self._admin())
        ch = s.get(f"{self.server.base_url}/api/codebook/admin/changes",
                   headers=self._admin())
        assert ch.status_code == 200
        ops = [c["op"] for c in ch.json()["changes"]]
        assert "merge" in ops
