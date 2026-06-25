"""Unit tests for the codebook distillation pipeline (Phase 3)."""

import pytest

from potato.codebook import content_service as cs
from potato.codebook import create_code
from potato.codebook.distiller import (
    CodebookDistiller, DistillerConfig, concat_procedure, get_procedure,
    register_procedure,
)
from potato.codebook.blocks import _BLOCKS_MIGRATION
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.codebook.revision import (
    _REVISION_MIGRATION, _CODES_REV_MIGRATION, _CONTENT_PROV_MIGRATION)
from potato.codebook.changelog import _CHANGE_MIGRATION
from potato.codebook.service import clear_change_listeners
from potato.persistence import (
    clear_db_cache, clear_migrations, register_migration)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    for m in (_CODEBOOK_MIGRATION, _REVISION_MIGRATION, _CODES_REV_MIGRATION,
              _CHANGE_MIGRATION, _BLOCKS_MIGRATION, _CONTENT_PROV_MIGRATION):
        register_migration(m)
    clear_change_listeners()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _code(td, name):
    return create_code(td, project="p", name=name, created_by="a")["id"]


def _save(td, cid, blocks, base=0):
    return cs.save_scope(
        td, project="p", scope_kind="code", scope_id=cid,
        blocks_in=blocks, base_version=base, actor="a")


class TestConcat:
    def test_per_code_definition_and_rules(self, td):
        cid = _code(td, "cost concerns")
        _save(td, cid, [
            {"block_type": "definition", "body_md": "money worries"},
            {"block_type": "use_when", "body_md": "affordability mentioned"},
            {"block_type": "notes", "body_md": "ignore me by default"},
        ])
        out = CodebookDistiller().distill(td, "p")
        assert "### cost concerns" in out
        assert "Definition: money worries" in out
        assert "Use when: affordability mentioned" in out
        # 'notes' is not in the default include set
        assert "ignore me" not in out

    def test_include_types_config_respected(self, td):
        cid = _code(td, "x")
        _save(td, cid, [
            {"block_type": "definition", "body_md": "DEF"},
            {"block_type": "example", "body_md": "EX"},
        ])
        cfg = DistillerConfig(include_types=("example",))
        out = CodebookDistiller(cfg).distill(td, "p")
        assert "EX" in out and "DEF" not in out

    def test_doc_section_included(self, td):
        cs.save_scope(
            td, project="p", scope_kind="section", scope_id="preamble",
            blocks_in=[{"block_type": "custom", "custom_label": "Intro",
                        "body_md": "overall rules"}],
            base_version=0, actor="a")
        out = CodebookDistiller().distill(td, "p")
        assert "overall rules" in out

    def test_empty_codebook_distills_to_empty(self, td):
        assert CodebookDistiller().distill(td, "p") == ""

    def test_max_chars_truncates(self, td):
        cid = _code(td, "y")
        _save(td, cid, [{"block_type": "definition", "body_md": "z" * 500}])
        out = CodebookDistiller(DistillerConfig(max_chars=80)).distill(td, "p")
        assert len(out) <= 100
        assert "truncated" in out


class TestCache:
    def test_cache_rebuilds_on_content_change(self, td):
        cid = _code(td, "c")
        _save(td, cid, [{"block_type": "definition", "body_md": "first"}])
        d = CodebookDistiller()
        assert "first" in d.distill(td, "p")
        _save(td, cid, [{"block_type": "definition", "body_md": "second"}],
              base=1)
        assert "second" in d.distill(td, "p")

    def test_cache_rebuilds_on_rename(self, td):
        from potato.codebook import rename_code
        cid = _code(td, "oldname")
        _save(td, cid, [{"block_type": "definition", "body_md": "def"}])
        d = CodebookDistiller()
        assert "oldname" in d.distill(td, "p")
        rename_code(td, cid, new_name="newname", project="p")
        assert "newname" in d.distill(td, "p")


class TestProcedureRegistry:
    def test_stub_procedures_registered(self):
        assert get_procedure("llm_summarize") is not None
        assert get_procedure("select_icl_examples") is not None

    def test_unknown_falls_back_to_concat(self):
        assert get_procedure("does_not_exist") is concat_procedure

    def test_custom_procedure_dispatch(self, td):
        cid = _code(td, "c")
        _save(td, cid, [{"block_type": "definition", "body_md": "x"}])
        register_procedure("shout", lambda ctx: "SHOUTED")
        out = CodebookDistiller(DistillerConfig(procedure="shout")).distill(
            td, "p")
        assert out == "SHOUTED"
