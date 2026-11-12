"""Codebook links follow saved annotations, so merge/split reach real codings.

Before this, nothing outside the unit tests wrote `annotation_codes`: a save
stamped the revision and stopped. A merge reported `merged: 0`, a split moved
nothing, and a split by one annotator archived a code everyone else still
used. These drive the served app end to end: two coders save, an admin
merges or splits, and the saved labels, links and review worklists are read
back.
"""

import glob
import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "links-admin-key"
PROJECT = "Codebook Links"
_CB = [{"name": "themes", "description": "T",
        "annotation_type": "multiselect", "codebook": True,
        "labels": ["seed"]}]


def _login(server, email):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": email, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": email, "pass": "pw"})
    return s


class TestCodebookLinksOnSave:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("cb_links_on_save")
        data_file = create_test_data_file(test_dir, [
            {"id": f"i{n}", "text": f"text {n}"} for n in range(1, 7)])
        config_file = create_test_config(
            test_dir, _CB, data_files=[data_file], require_password=False,
            annotation_task_name=PROJECT,
            additional_config={"codebook_mode": "open",
                               "admin_api_key": ADMIN_KEY})
        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("server did not start")
        request.cls.server = server
        request.cls.test_dir = os.path.abspath(test_dir)
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    # ---- helpers --------------------------------------------------------

    @property
    def base(self):
        return self.server.base_url

    def _admin(self):
        return {"X-API-Key": ADMIN_KEY}

    def _mk(self, s, name):
        r = s.post(f"{self.base}/api/codebook", json={"name": name})
        assert r.status_code == 200, r.text
        return r.json()["code"]["id"]

    def _save(self, s, iid, *names):
        r = s.post(f"{self.base}/updateinstance", json={
            "instance_id": iid,
            "annotations": {f"themes:::{n}": n for n in names}})
        assert r.status_code == 200, r.text

    def _saved(self, s, iid):
        r = s.get(f"{self.base}/get_annotations", params={"instance_id": iid})
        assert r.status_code == 200, r.text
        return sorted(r.json()["label_annotations"].get("themes", []))

    def _on_disk(self, user, iid):
        """Label names in the user's persisted user_state.json."""
        paths = glob.glob(os.path.join(
            self.test_dir, "output", "**", user, "user_state.json"),
            recursive=True)
        assert paths, f"no user_state.json for {user}"
        with open(paths[0]) as f:
            state = json.load(f)
        pairs = state["instance_id_to_label_to_value"].get(iid, [])
        return sorted(label["name"] for label, _value in pairs
                      if label["schema"] == "themes")

    def _links(self, code_id):
        from potato.codebook import store
        return sorted(store.affected_annotation_ids(
            self.test_dir, PROJECT, code_id))

    def _stale_ids(self, s):
        r = s.get(f"{self.base}/api/codebook/stale")
        assert r.status_code == 200, r.text
        return {it["instance_id"]: it for it in r.json()["stale"]}

    def _labels(self, s):
        return s.get(f"{self.base}/api/codebook").json()["labels"]

    # ---- tests ----------------------------------------------------------

    def test_two_coders_get_one_link_each(self):
        alice, bob = _login(self.server, "la"), _login(self.server, "lb")
        x = self._mk(alice, "link-x")
        self._save(alice, "i1", "link-x")
        self._save(bob, "i1", "link-x")
        # One instance, two coders: two links, not one row overwritten.
        assert self._links(x) == ["i1\x1fla", "i1\x1flb"]

    def test_deselecting_a_code_drops_the_link(self):
        s = _login(self.server, "ld")
        a, b = self._mk(s, "drop-a"), self._mk(s, "drop-b")
        self._save(s, "i2", "drop-a", "drop-b")
        assert self._links(a) == ["i2\x1fld"]
        r = s.post(f"{self.base}/updateinstance", json={
            "instance_id": "i2", "annotations": {"themes:::drop-b": "drop-b"},
            "cleared_schemas": ["themes"]})
        assert r.status_code == 200, r.text
        assert self._links(a) == []
        assert self._links(b) == ["i2\x1fld"]

    def test_merge_moves_both_coders_labels_and_links(self):
        alice, bob = _login(self.server, "ma"), _login(self.server, "mb")
        x, y = self._mk(alice, "merge-x"), self._mk(alice, "merge-y")
        self._save(alice, "i3", "merge-x")
        self._save(bob, "i3", "merge-x")

        r = alice.post(f"{self.base}/api/codebook/admin/merge",
                       json={"src_id": x, "dst_id": y}, headers=self._admin())
        assert r.status_code == 200, r.text
        assert r.json()["merged"] == 2

        assert self._links(y) == ["i3\x1fma", "i3\x1fmb"]
        assert self._links(x) == []
        # The saved label follows the code, in memory and on disk; left as
        # "merge-x" it names a code that no longer exists.
        for sess, user in ((alice, "ma"), (bob, "mb")):
            assert self._saved(sess, "i3") == ["merge-y"]
            assert self._on_disk(user, "i3") == ["merge-y"]
            assert "i3" in self._stale_ids(sess)

        # The next save keeps the link on the merged code.
        self._save(alice, "i3", "merge-y")
        assert self._links(y) == ["i3\x1fma", "i3\x1fmb"]

    def test_merge_reaches_codings_saved_before_links_existed(self):
        alice, bob = _login(self.server, "pa"), _login(self.server, "pb")
        x, y = self._mk(alice, "pre-x"), self._mk(alice, "pre-y")
        self._save(alice, "i5", "pre-x")
        self._save(bob, "i5", "pre-x")
        # A project annotated before saves wrote links has the labels in
        # user state and no rows at all.
        from potato.persistence import get_db
        conn = get_db(self.test_dir)
        conn.execute("DELETE FROM annotation_codes WHERE code_id = ?", (x,))
        conn.commit()
        assert self._links(x) == []

        r = alice.post(f"{self.base}/api/codebook/admin/merge",
                       json={"src_id": x, "dst_id": y}, headers=self._admin())
        assert r.status_code == 200, r.text
        assert r.json()["merged"] == 2
        assert self._saved(bob, "i5") == ["pre-y"]

    def test_split_by_one_coder_leaves_the_other_on_the_source(self):
        alice, bob = _login(self.server, "sa"), _login(self.server, "sb")
        x = self._mk(alice, "split-x")
        self._save(alice, "i4", "split-x")
        self._save(bob, "i4", "split-x")

        r = alice.post(f"{self.base}/api/codebook/admin/split",
                       json={"src_id": x, "annotator": "sa",
                             "new_name": "split-x-sa"},
                       headers=self._admin())
        assert r.status_code == 200, r.text
        assert r.json()["moved"] == 1
        target = r.json()["target_id"]

        # bob still codes with split-x, so it must stay in the palette.
        assert "split-x" in self._labels(bob)
        assert self._links(x) == ["i4\x1fsb"]
        assert self._links(target) == ["i4\x1fsa"]
        assert self._saved(alice, "i4") == ["split-x-sa"]
        assert self._saved(bob, "i4") == ["split-x"]

    def test_split_archives_the_source_once_nobody_uses_it(self):
        s = _login(self.server, "so")
        x = self._mk(s, "solo-x")
        self._save(s, "i5", "solo-x")
        r = s.post(f"{self.base}/api/codebook/admin/split",
                   json={"src_id": x, "annotator": "so",
                         "new_name": "solo-x-moved"},
                   headers=self._admin())
        assert r.status_code == 200, r.text
        labels = self._labels(s)
        assert "solo-x" not in labels and "solo-x-moved" in labels

    def test_definition_edit_lists_the_coder_for_review(self):
        s = _login(self.server, "ce")
        x = self._mk(s, "sem-x")
        self._mk(s, "sem-y")
        # Coded with sem-y, not sem-x: only the semantic worklist can find it.
        self._save(s, "i6", "sem-y")
        assert "i6" not in self._stale_ids(s)

        scope = s.get(f"{self.base}/api/codebook/blocks",
                      params={"code_id": x}).json()
        r = s.put(f"{self.base}/api/codebook/blocks", json={
            "code_id": x, "base_version": scope["scope_version"],
            "blocks": [{"block_type": "definition",
                        "body_md": "A changed meaning."}]})
        assert r.status_code == 200, r.text
        assert r.json()["semantic"] is True

        stale = self._stale_ids(s)
        assert "i6" in stale and stale["i6"]["content_stale"] is True
        admin = s.get(f"{self.base}/api/codebook/admin/stale",
                      headers=self._admin()).json()["stale"]
        assert any(it["instance_id"] == "i6" and it["username"] == "ce"
                   and it.get("content_stale") for it in admin)

    def test_rename_flags_provenance_and_rewrites_the_saved_label(self):
        s = _login(self.server, "rn")
        x = self._mk(s, "ren-x")
        self._save(s, "i1", "ren-x")
        prov = s.get(f"{self.base}/api/codebook/provenance",
                     params={"instance_id": "i1"}).json()
        assert prov["stale"] is False

        r = s.patch(f"{self.base}/api/codebook/{x}", json={"name": "ren-x2"})
        assert r.status_code == 200, r.text
        prov = s.get(f"{self.base}/api/codebook/provenance",
                     params={"instance_id": "i1"}).json()
        # No code was added, so the banner shows "renamed / recolored".
        assert prov["stale"] is True and prov["codes_added_since"] == []
        assert self._saved(s, "i1") == ["ren-x2"]
        assert self._links(x) == ["i1\x1frn"]

    def test_patch_and_delete_record_who_did_it(self):
        s = _login(self.server, "auditor")
        x = self._mk(s, "audit-x")
        assert s.patch(f"{self.base}/api/codebook/{x}",
                       json={"name": "audit-x2", "color": "#123456"}
                       ).status_code == 200
        assert s.delete(f"{self.base}/api/codebook/{x}").status_code == 200
        changes = s.get(f"{self.base}/api/codebook/admin/changes",
                        headers=self._admin()).json()["changes"]
        mine = {c["op"]: c for c in changes if c.get("code_id") == x}
        assert set(mine) >= {"rename", "recolor", "delete"}
        for op in ("rename", "recolor", "delete"):
            assert mine[op]["actor"] == "auditor", mine[op]
            assert mine[op]["actor_kind"] == "human"

    def test_a_code_added_on_the_page_is_saved_by_its_name_and_linked(self):
        """Audit 105 A1: a code added after the server started was named after
        its element id, `<schema>__cb__<slug>`. Saved under that name it had
        no link, and merge, split and rename could not reach it. A coding
        saved that way before the fix is renamed at the next save."""
        s = _login(self.server, "runtime-coder")
        zid = self._mk(s, "ze ta")
        # As the page saves it now: by the code's own name.
        self._save(s, "i5", "ze ta")
        assert self._links(zid) == ["i5\x1fruntime-coder"]
        # As it saved it before: by the element id.
        self._save(s, "i6", "themes__cb__ze_ta")
        assert self._saved(s, "i6") == ["ze ta"]
        assert self._on_disk("runtime-coder", "i6") == ["ze ta"]
        assert sorted(self._links(zid)) == ["i5\x1fruntime-coder", "i6\x1fruntime-coder"]

    def test_the_banner_does_not_announce_the_code_a_merge_moved_you_onto(self):
        """Audit 105 P3: after a merge onto a newer code, /provenance listed
        that code as 'added since you labeled this', though it is the code
        the coder now holds."""
        s = _login(self.server, "pv")
        x = self._mk(s, "pv-x")
        self._save(s, "i4", "pv-x")
        y = self._mk(s, "pv-y")                   # created after the save
        r = s.post(f"{self.base}/api/codebook/admin/merge",
                   json={"src_id": x, "dst_id": y}, headers=self._admin())
        assert r.status_code == 200, r.text
        p = s.get(f"{self.base}/api/codebook/provenance",
                  params={"instance_id": "i4"}).json()
        assert p["stale"] is True
        assert "pv-y" not in p["codes_added_since"]

    def test_a_code_named_like_an_element_id_is_not_renamed(self):
        """Audit 105 N1: a code literally named `themes__cb__nx` was renamed to
        `nx` at the next save, so a coder holding both lost one."""
        alice, bob = _login(self.server, "n1a"), _login(self.server, "n1b")
        lit, plain = self._mk(alice, "themes__cb__nx"), self._mk(alice, "nx")
        self._save(alice, "i1", "themes__cb__nx", "nx")
        self._save(bob, "i1", "themes__cb__nx")
        assert self._saved(alice, "i1") == ["nx", "themes__cb__nx"]
        assert self._on_disk("n1b", "i1") == ["themes__cb__nx"]
        assert self._links(lit) == ["i1\x1fn1a", "i1\x1fn1b"]
        assert self._links(plain) == ["i1\x1fn1a"]

    def test_an_element_id_two_codes_share_is_left_as_saved(self):
        """Audit 105 N1 (P3): "Gam ma" and "Gam_ma" have one element id; a
        coding saved under it went to whichever code was listed first."""
        s = _login(self.server, "n1c")
        a, b = self._mk(s, "Gam ma"), self._mk(s, "Gam_ma")
        self._save(s, "i2", "themes__cb__Gam_ma")
        assert self._saved(s, "i2") == ["themes__cb__Gam_ma"]
        assert self._links(a) == [] and self._links(b) == []

    def _stale_tab_save(self, s, iid, *names):
        """What a page opened before the change posts when it saves."""
        self._save(s, iid, *names)

    def test_a_stale_tab_does_not_undo_a_rename(self):
        """Audit 105 N2: a tab opened before a rename saved the old name back,
        a coding with no code and no link."""
        s = _login(self.server, "n2r")
        pi = self._mk(s, "pi")
        self._save(s, "i3", "pi")
        assert s.patch(f"{self.base}/api/codebook/{pi}",
                       json={"name": "pi2"}).status_code == 200
        self._stale_tab_save(s, "i3", "pi")
        assert self._saved(s, "i3") == ["pi2"]
        assert self._on_disk("n2r", "i3") == ["pi2"]
        assert self._links(pi) == ["i3\x1fn2r"]

    def test_a_stale_tab_does_not_undo_a_merge_or_a_split(self):
        s = _login(self.server, "n2m")
        mx, my = self._mk(s, "n2-mx"), self._mk(s, "n2-my")
        lam = self._mk(s, "n2-lam")
        self._save(s, "i4", "n2-mx", "n2-lam")
        r = s.post(f"{self.base}/api/codebook/admin/merge",
                   json={"src_id": mx, "dst_id": my}, headers=self._admin())
        assert r.status_code == 200, r.text
        r = s.post(f"{self.base}/api/codebook/admin/split",
                   json={"src_id": lam, "annotator": "n2m", "new_name": "n2-lam2"},
                   headers=self._admin())
        assert r.status_code == 200, r.text
        lam2 = r.json()["target_id"]
        self._stale_tab_save(s, "i4", "n2-mx", "n2-lam")
        assert self._saved(s, "i4") == ["n2-lam2", "n2-my"]
        assert self._on_disk("n2m", "i4") == ["n2-lam2", "n2-my"]
        assert self._links(my) == ["i4\x1fn2m"] and self._links(lam2) == ["i4\x1fn2m"]
        assert self._links(lam) == [] and self._links(mx) == []

    def test_a_rename_then_a_merge_is_followed_to_the_end(self):
        s = _login(self.server, "n2c")
        a, b = self._mk(s, "n2-a"), self._mk(s, "n2-b")
        self._save(s, "i5", "n2-a")
        assert s.patch(f"{self.base}/api/codebook/{a}",
                       json={"name": "n2-a2"}).status_code == 200
        assert s.post(f"{self.base}/api/codebook/admin/merge",
                      json={"src_id": a, "dst_id": b},
                      headers=self._admin()).status_code == 200
        self._stale_tab_save(s, "i5", "n2-a")
        assert self._saved(s, "i5") == ["n2-b"]

    def test_a_stale_tab_after_a_split_of_a_shared_code_and_the_repair(self):
        """Audit 105 D1: the source stays live while another coder uses it, so
        the stale tab writes it back; splitting again onto the same target
        moves it back, as codebook.md says."""
        alice, bob = _login(self.server, "d1a"), _login(self.server, "d1b")
        src = self._mk(alice, "d1-src")
        self._save(alice, "i6", "d1-src")
        self._save(bob, "i6", "d1-src")
        split = {"src_id": src, "annotator": "d1a", "new_name": "d1-dst"}
        r = alice.post(f"{self.base}/api/codebook/admin/split", json=split,
                       headers=self._admin())
        assert r.status_code == 200, r.text
        dst = r.json()["target_id"]
        self._stale_tab_save(alice, "i6", "d1-src")
        assert self._saved(alice, "i6") == ["d1-src"]
        assert self._links(dst) == []
        r = alice.post(f"{self.base}/api/codebook/admin/split",
                       json={"src_id": src, "annotator": "d1a", "target_id": dst},
                       headers=self._admin())
        assert r.status_code == 200 and r.json()["moved"] == 1, r.text
        assert self._saved(alice, "i6") == ["d1-dst"]
        assert self._on_disk("d1a", "i6") == ["d1-dst"]
        assert self._links(dst) == ["i6\x1fd1a"] and self._links(src) == ["i6\x1fd1b"]
