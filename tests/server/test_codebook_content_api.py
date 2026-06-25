"""HTTP surface for the living-document content layer (Phase 2).

Exercised end-to-end on the served app (the registered blueprint, not the
discarded module app): GET /document, GET/PUT /blocks with optimistic 409,
POST /parse, history + restore, semantic-vs-cosmetic revision behavior, and
locked-mode proposal routing + admin confirm.
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


class TestContentApiOpen:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cb_content_open")
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

    def _url(self, path):
        return f"{self.server.base_url}/api/codebook{path}"

    def _mk(self, s, name):
        r = s.post(self._url(""), json={"name": name})
        assert r.status_code == 200, r.text
        return r.json()["code"]["id"]

    # ---- document + vocabulary -----------------------------------------

    def test_document_shape(self):
        s = _login(self.server, "doc1")
        r = s.get(self._url("/document"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert "codes" in d and "doc_sections" in d
        assert "block_types" in d and any(
            bt["key"] == "use_when" for bt in d["block_types"])
        assert d["can_edit_content"] is True
        assert d["sem_revision"] == 0

    # ---- save + read ----------------------------------------------------

    def test_put_then_get_blocks(self):
        s = _login(self.server, "save1")
        cid = self._mk(s, "saveable code")
        r = s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 0,
            "blocks": [
                {"block_type": "definition", "body_md": "the meaning"},
                {"block_type": "example", "body_md": "> a quote"},
            ]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scope_version"] == 1
        assert [b["block_type"] for b in body["blocks"]] == [
            "definition", "example"]
        got = s.get(self._url("/blocks"), params={"code_id": cid}).json()
        assert got["scope_version"] == 1
        assert got["blocks"][0]["body_md"] == "the meaning"

    def test_optimistic_conflict_returns_409(self):
        s = _login(self.server, "race1")
        cid = self._mk(s, "raced code")
        ok = s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 0,
            "blocks": [{"block_type": "definition", "body_md": "v1"}]})
        assert ok.status_code == 200, ok.text
        # second writer still thinks base is 0 -> conflict
        stale = s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 0,
            "blocks": [{"block_type": "definition", "body_md": "v2"}]})
        assert stale.status_code == 409, stale.text
        body = stale.json()
        assert body["error"] == "stale_content"
        assert body["current_version"] == 1
        assert body["current_blocks"][0]["body_md"] == "v1"
        assert "current_md" in body
        # the stale write did not land
        live = s.get(self._url("/blocks"), params={"code_id": cid}).json()
        assert live["blocks"][0]["body_md"] == "v1"

    # ---- parse ----------------------------------------------------------

    def test_parse_classifies_and_flags(self):
        s = _login(self.server, "parse1")
        md = "### Use when\napply here\n\n### Mystery Heading\nhmm\n"
        r = s.post(self._url("/parse"), json={"markdown": md})
        assert r.status_code == 200, r.text
        blocks = r.json()["blocks"]
        assert blocks[0]["block_type"] == "use_when"
        assert blocks[0]["classified"] is True
        assert blocks[1]["block_type"] == "custom"
        assert blocks[1]["custom_label"] == "Mystery Heading"
        assert blocks[1]["classified"] is False

    # ---- semantic vs cosmetic ------------------------------------------

    def test_semantic_edit_bumps_sem_revision_cosmetic_does_not(self):
        s = _login(self.server, "sem1")
        cid = self._mk(s, "sem code")
        before = s.get(self._url("/document")).json()["sem_revision"]
        # semantic: a use_when rule
        r1 = s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 0,
            "blocks": [{"block_type": "use_when", "body_md": "rule A"}]})
        assert r1.json()["semantic"] is True
        after_sem = s.get(self._url("/document")).json()["sem_revision"]
        assert after_sem == before + 1
        # cosmetic: append a note, keep the rule identical
        r2 = s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 1,
            "blocks": [
                {"block_type": "use_when", "body_md": "rule A"},
                {"block_type": "notes", "body_md": "fyi"},
            ]})
        assert r2.json()["semantic"] is False
        assert r2.json()["content_revision"] > r1.json()["content_revision"]
        assert s.get(
            self._url("/document")).json()["sem_revision"] == after_sem

    def test_minor_flag_forces_cosmetic(self):
        s = _login(self.server, "minor1")
        cid = self._mk(s, "minor code")
        s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 0,
            "blocks": [{"block_type": "definition", "body_md": "d1"}]})
        sem_before = s.get(self._url("/document")).json()["sem_revision"]
        r = s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 1, "minor": True,
            "blocks": [{"block_type": "definition", "body_md": "d2"}]})
        assert r.json()["semantic"] is False
        assert s.get(
            self._url("/document")).json()["sem_revision"] == sem_before

    # ---- history + restore ---------------------------------------------

    def test_history_and_restore(self):
        s = _login(self.server, "hist1")
        cid = self._mk(s, "history code")
        s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 0,
            "blocks": [{"block_type": "definition", "body_md": "first"}]})
        s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 1,
            "blocks": [{"block_type": "definition", "body_md": "second"}]})
        hist = s.get(self._url("/history"),
                     params={"scope_kind": "code", "scope_id": cid}).json()
        assert hist["count"] == 2
        # newest first
        assert hist["history"][0]["created_at"] >= \
            hist["history"][1]["created_at"]
        oldest = hist["history"][-1]
        snap = s.get(self._url(f"/history/{oldest['id']}")).json()
        assert snap["blocks"][0]["body_md"] == "first"
        # restore the oldest -> live content becomes "first" again
        rr = s.post(self._url("/restore"),
                    json={"snapshot_id": oldest["id"]})
        assert rr.status_code == 200, rr.text
        live = s.get(self._url("/blocks"), params={"code_id": cid}).json()
        assert live["blocks"][0]["body_md"] == "first"

    # ---- full-page route (blueprint-registration guard) ----------------

    def test_codebook_page_served(self):
        s = _login(self.server, "page1")
        r = s.get(f"{self.server.base_url}/codebook")
        assert r.status_code == 200, r.text
        assert "text/html" in r.headers.get("Content-Type", "")
        assert "codebook_document.js" in r.text
        assert 'id="cbd-doc"' in r.text

    # ---- distillation ---------------------------------------------------

    def test_distilled_reflects_content(self):
        s = _login(self.server, "dist1")
        cid = self._mk(s, "distillable")
        s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 0,
            "blocks": [
                {"block_type": "definition", "body_md": "a clear meaning"},
                {"block_type": "use_when", "body_md": "trigger phrase"},
            ]})
        r = s.get(self._url("/distilled"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["procedure"] == "concat"
        assert "a clear meaning" in body["distilled"]
        assert "trigger phrase" in body["distilled"]
        assert "### distillable" in body["distilled"]

    # ---- doc-level sections --------------------------------------------

    def test_doc_section_scope(self):
        s = _login(self.server, "docsec1")
        r = s.put(self._url("/blocks"), json={
            "section": "preamble", "base_version": 0,
            "blocks": [{"block_type": "custom", "custom_label": "Preamble",
                        "body_md": "Read this first."}]})
        assert r.status_code == 200, r.text
        doc = s.get(self._url("/document")).json()
        pre = [x for x in doc["doc_sections"]
               if x["section"] == "preamble"][0]
        assert pre["blocks"][0]["body_md"] == "Read this first."

    def test_unknown_section_rejected(self):
        s = _login(self.server, "docsec2")
        r = s.put(self._url("/blocks"), json={
            "section": "not_a_section", "base_version": 0,
            "blocks": [{"block_type": "notes", "body_md": "x"}]})
        assert r.status_code == 400, r.text


class TestContentApiLockedMode:
    """extensible mode: a non-privileged content edit is QUEUED as a
    proposal (not a 403), and an admin confirm applies it."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cb_content_locked")
        data_file = create_test_data_file(
            test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            test_dir, _CB, data_files=[data_file], require_password=False,
            additional_config={"codebook_mode": "extensible",
                               "admin_api_key": ADMIN_KEY})
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def _url(self, path):
        return f"{self.server.base_url}/api/codebook{path}"

    def test_content_edit_is_queued_then_confirmed(self):
        s = _login(self.server, "lk1")
        # extensible lets a user add a code
        cid = s.post(self._url(""), json={"name": "locked code"}).json()[
            "code"]["id"]
        # ...but a content edit is queued, not applied
        r = s.put(self._url("/blocks"), json={
            "code_id": cid, "base_version": 0,
            "blocks": [{"block_type": "definition", "body_md": "proposed"}]})
        assert r.status_code == 201, r.text
        assert r.json().get("queued") is True
        pid = r.json()["proposal"]["id"]
        # not yet applied
        live = s.get(self._url("/blocks"), params={"code_id": cid}).json()
        assert live["blocks"] == []
        # admin confirms -> applied
        c = s.post(self._url(f"/admin/proposals/{pid}/confirm"),
                   headers={"X-API-Key": ADMIN_KEY})
        assert c.status_code == 200, c.text
        live2 = s.get(self._url("/blocks"), params={"code_id": cid}).json()
        assert live2["blocks"][0]["body_md"] == "proposed"
