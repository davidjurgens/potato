"""`potato codebook` CLI determinism/idempotency + ICL-sync listener."""

import textwrap

import pytest

from potato.codebook import clear_change_listeners, create_code
from potato.codebook.codebook import Codebook
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.codebook_cli import deterministic_code_id, init_codebook, main
from potato.codebook.schema_bridge import (
    _icl_sync_listener,
    install_codebook_icl_sync,
)
from potato.persistence import (
    clear_db_cache,
    clear_migrations,
    register_migration,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    clear_change_listeners()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()


def _write_config(tmp_path, labels=("a", "b", "c")):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "data").mkdir()
    (proj / "data" / "d.json").write_text('[{"id":"1","text":"x"}]')
    cfg = proj / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""
        annotation_task_name: P
        task_dir: .
        data_files: [data/d.json]
        annotation_schemes:
        - annotation_type: radio
          name: s
          description: d
          codebook: true
          labels: [{', '.join(labels)}]
    """))
    return str(cfg), str(proj)


class TestDeterministicId:
    def test_stable_across_calls(self):
        a = deterministic_code_id("P", "", "Sentiment")
        b = deterministic_code_id("P", "", "Sentiment")
        assert a == b and len(a) == 32

    def test_varies_by_project_and_name(self):
        assert deterministic_code_id("P", "", "x") != \
            deterministic_code_id("Q", "", "x")
        assert deterministic_code_id("P", "", "x") != \
            deterministic_code_id("P", "", "y")


class TestInitCodebookCLI:
    def test_creates_codes(self, tmp_path):
        cfg, proj = _write_config(tmp_path)
        res = init_codebook(cfg)
        assert res == {"created": 3, "existing": 0}
        assert Codebook.load(proj, "P").labels() == ["a", "b", "c"]

    def test_idempotent(self, tmp_path):
        cfg, proj = _write_config(tmp_path)
        init_codebook(cfg)
        res2 = init_codebook(cfg)
        assert res2 == {"created": 0, "existing": 3}
        assert len(Codebook.load(proj, "P")) == 3

    def test_uses_deterministic_ids(self, tmp_path):
        cfg, proj = _write_config(tmp_path)
        init_codebook(cfg)
        cb = Codebook.load(proj, "P")
        a = next(c for c in cb._codes if c["name"] == "a")
        assert a["id"] == deterministic_code_id("P", "", "a")

    def test_dry_run_writes_nothing(self, tmp_path):
        cfg, proj = _write_config(tmp_path)
        res = init_codebook(cfg, dry_run=True)
        assert res["created"] == 3
        assert Codebook.load(proj, "P").is_empty()

    def test_main_missing_config_returns_2(self, tmp_path):
        assert main([str(tmp_path / "nope.yaml")]) == 2

    def test_main_ok_returns_0(self, tmp_path):
        cfg, _ = _write_config(tmp_path)
        assert main([cfg]) == 0


class TestICLSyncListener:
    def test_listener_refreshes_live_config_labels(self, tmp_path, monkeypatch):
        proj = tmp_path / "p"
        proj.mkdir()
        td = str(proj)
        scheme = {"name": "s", "annotation_type": "radio",
                  "codebook": True, "labels": ["seed"]}
        live = {"task_dir": td, "annotation_task_name": "P",
                "annotation_schemes": [scheme]}

        import potato.server_utils.config_module as cm
        monkeypatch.setattr(cm, "config", live)

        create_code(td, project="P", name="seed", created_by="x")
        create_code(td, project="P", name="added_at_runtime",
                    created_by="annotator")

        _icl_sync_listener(td, "P")
        assert "added_at_runtime" in scheme["labels"]

    def test_listener_ignores_other_projects(self, tmp_path, monkeypatch):
        td = str(tmp_path)
        scheme = {"name": "s", "codebook": True, "labels": ["orig"]}
        live = {"task_dir": td, "annotation_task_name": "P",
                "annotation_schemes": [scheme]}
        import potato.server_utils.config_module as cm
        monkeypatch.setattr(cm, "config", live)
        _icl_sync_listener(td, "OTHER")  # different project
        assert scheme["labels"] == ["orig"]

    def test_install_registers_and_fires(self, tmp_path, monkeypatch):
        proj = tmp_path / "q"
        proj.mkdir()
        td = str(proj)
        scheme = {"name": "s", "codebook": True, "labels": ["one"]}
        live = {"task_dir": td, "annotation_task_name": "P",
                "annotation_schemes": [scheme]}
        import potato.server_utils.config_module as cm
        monkeypatch.setattr(cm, "config", live)

        install_codebook_icl_sync()
        create_code(td, project="P", name="one", created_by="x")
        create_code(td, project="P", name="two", created_by="x")
        assert set(scheme["labels"]) == {"one", "two"}
