"""Unit tests for potato.codebook.blocks (content block store)."""

import pytest

from potato.codebook import blocks
from potato.codebook.blocks import _BLOCKS_MIGRATION, StaleScopeError
from potato.codebook.store import _CODEBOOK_MIGRATION
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
    register_migration(_BLOCKS_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _blk(t, body, **kw):
    b = {"block_type": t, "body_md": body}
    b.update(kw)
    return b


class TestReplaceAndList:
    def test_empty_scope_version_is_zero(self, td):
        assert blocks.scope_version(td, "p", code_id="c1") == 0
        assert blocks.list_blocks(td, "p", code_id="c1") == []

    def test_first_save_sets_version_one(self, td):
        out = blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="alice",
            blocks=[_blk("definition", "x")])
        assert len(out) == 1
        assert out[0]["version"] == 1
        assert out[0]["ordinal"] == 0
        assert blocks.scope_version(td, "p", code_id="c1") == 1

    def test_replace_archives_old_and_bumps_version(self, td):
        blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="alice",
            blocks=[_blk("definition", "v1")])
        out = blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="bob",
            blocks=[_blk("definition", "v2"), _blk("use_when", "when")])
        assert blocks.scope_version(td, "p", code_id="c1") == 2
        live = blocks.list_blocks(td, "p", code_id="c1")
        assert [b["body_md"] for b in live] == ["v2", "when"]
        assert all(b["version"] == 2 for b in live)
        # exactly the live set is returned; no archived rows leak in
        assert len(live) == 2

    def test_ordinals_assigned_in_order(self, td):
        out = blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="a",
            blocks=[_blk("definition", "a"), _blk("use_when", "b"),
                    _blk("example", "c")])
        assert [b["ordinal"] for b in out] == [0, 1, 2]

    def test_invalid_type_coerced_to_custom(self, td):
        out = blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="a",
            blocks=[_blk("not_a_real_type", "x")])
        assert out[0]["block_type"] == "custom"
        assert out[0]["custom_label"]  # falls back to a heading


class TestScopeIsolation:
    def test_code_and_doc_scopes_independent(self, td):
        blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="a",
            blocks=[_blk("definition", "code")])
        blocks.replace_scope_blocks(
            td, project="p", section="preamble", actor="a",
            blocks=[_blk("custom", "doc", custom_label="Preamble")])
        assert blocks.scope_version(td, "p", code_id="c1") == 1
        assert blocks.scope_version(td, "p", section="preamble") == 1
        assert blocks.list_blocks(td, "p", code_id="c1")[0]["body_md"] == "code"
        assert blocks.list_blocks(
            td, "p", section="preamble")[0]["body_md"] == "doc"

    def test_two_codes_independent(self, td):
        blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="a",
            blocks=[_blk("definition", "one")])
        blocks.replace_scope_blocks(
            td, project="p", code_id="c2", actor="a",
            blocks=[_blk("definition", "two")])
        assert blocks.scope_version(td, "p", code_id="c1") == 1
        assert blocks.scope_version(td, "p", code_id="c2") == 1


class TestOptimisticConcurrency:
    def test_matching_base_version_succeeds(self, td):
        blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="a",
            blocks=[_blk("definition", "v1")], base_version=0)
        blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="a",
            blocks=[_blk("definition", "v2")], base_version=1)
        assert blocks.list_blocks(
            td, "p", code_id="c1")[0]["body_md"] == "v2"

    def test_stale_base_version_raises(self, td):
        blocks.replace_scope_blocks(
            td, project="p", code_id="c1", actor="a",
            blocks=[_blk("definition", "v1")])
        with pytest.raises(StaleScopeError) as exc:
            blocks.replace_scope_blocks(
                td, project="p", code_id="c1", actor="a",
                blocks=[_blk("definition", "bad")], base_version=0)
        assert exc.value.current_version == 1
        # the stale write did not land
        assert blocks.list_blocks(
            td, "p", code_id="c1")[0]["body_md"] == "v1"
