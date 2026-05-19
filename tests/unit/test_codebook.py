"""Unit tests for potato.codebook store + service (tree, cycles, audit)."""

import pytest

from potato.codebook import (
    Codebook,
    CodebookCycleError,
    CodeNotFound,
    DuplicateCodeError,
    apply_code,
    clear_change_listeners,
    codes_on,
    create_code,
    delete_code,
    move_under,
    recolor_code,
    register_change_listener,
    remove_code,
    rename_code,
)
from potato.codebook import store
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


def _c(td, name, **kw):
    base = dict(project="p", name=name, created_by="alice")
    base.update(kw)
    return create_code(td, **base)


class TestCreateTree:
    def test_create_root(self, td):
        c = _c(td, "Theme A")
        assert c["parent_id"] == store.ROOT
        assert c["created_by"] == "alice"
        assert c["sort_order"] == 0

    def test_nested_and_labels_in_tree_order(self, td):
        a = _c(td, "A")
        _c(td, "A1", parent_id=a["id"])
        _c(td, "A2", parent_id=a["id"])
        _c(td, "B")
        cb = Codebook.load(td, "p")
        assert cb.labels() == ["A", "A1", "A2", "B"]
        assert [n["name"] for n in cb.as_tree()] == ["A", "B"]
        assert cb.label_to_id()["A1"]

    def test_duplicate_sibling_rejected(self, td):
        _c(td, "Dup")
        with pytest.raises(DuplicateCodeError):
            _c(td, "Dup")

    def test_same_name_different_parents_ok(self, td):
        a = _c(td, "A")
        b = _c(td, "B")
        _c(td, "child", parent_id=a["id"])
        _c(td, "child", parent_id=b["id"])  # no raise

    def test_empty_name_rejected(self, td):
        with pytest.raises(Exception):
            _c(td, "   ")

    def test_missing_parent_rejected(self, td):
        with pytest.raises(CodeNotFound):
            _c(td, "x", parent_id="nope")

    def test_deterministic_code_id(self, td):
        c = _c(td, "Fixed", code_id="deadbeef")
        assert c["id"] == "deadbeef"


class TestMutations:
    def test_rename(self, td):
        c = _c(td, "Old")
        r = rename_code(td, c["id"], new_name="New", project="p")
        assert r["name"] == "New"

    def test_rename_clash_rejected(self, td):
        _c(td, "Taken")
        c = _c(td, "Free")
        with pytest.raises(DuplicateCodeError):
            rename_code(td, c["id"], new_name="Taken", project="p")

    def test_recolor(self, td):
        c = _c(td, "C")
        assert recolor_code(
            td, c["id"], color="#ff0000", project="p")["color"] == "#ff0000"

    def test_move_under(self, td):
        a = _c(td, "A")
        b = _c(td, "B")
        move_under(td, b["id"], new_parent_id=a["id"], project="p")
        assert [n["name"] for n in Codebook.load(td, "p").as_tree()] == ["A"]

    def test_move_cycle_rejected(self, td):
        a = _c(td, "A")
        a1 = _c(td, "A1", parent_id=a["id"])
        with pytest.raises(CodebookCycleError):
            move_under(td, a["id"], new_parent_id=a1["id"], project="p")

    def test_self_parent_rejected(self, td):
        a = _c(td, "A")
        with pytest.raises(CodebookCycleError):
            move_under(td, a["id"], new_parent_id=a["id"], project="p")

    def test_delete_recursive(self, td):
        a = _c(td, "A")
        a1 = _c(td, "A1", parent_id=a["id"])
        _c(td, "A1a", parent_id=a1["id"])
        assert delete_code(td, a["id"], project="p") == 3
        assert Codebook.load(td, "p").is_empty()


class TestAnnotationLinks:
    def test_apply_and_list(self, td):
        c = _c(td, "Sentiment")
        apply_code(td, project="p", annotation_id="ann1",
                   code_id=c["id"], created_by="alice")
        rows = codes_on(td, "ann1")
        assert rows[0]["code_id"] == c["id"]
        assert rows[0]["name"] == "Sentiment"

    def test_apply_unknown_code_rejected(self, td):
        with pytest.raises(CodeNotFound):
            apply_code(td, project="p", annotation_id="a",
                       code_id="ghost", created_by="x")

    def test_remove_link(self, td):
        c = _c(td, "C")
        apply_code(td, project="p", annotation_id="a",
                   code_id=c["id"], created_by="x")
        assert remove_code(td, annotation_id="a", code_id=c["id"]) is True
        assert codes_on(td, "a") == []

    def test_delete_code_cascades_links(self, td):
        c = _c(td, "C")
        apply_code(td, project="p", annotation_id="a",
                   code_id=c["id"], created_by="x")
        delete_code(td, c["id"], project="p")
        assert codes_on(td, "a") == []

    def test_temporal_span_link(self, td):
        c = _c(td, "Step")
        apply_code(td, project="p", annotation_id="t",
                   code_id=c["id"], created_by="llm:gpt",
                   started_at=1.0, ended_at=2.5)
        row = codes_on(td, "t")[0]
        assert row["started_at"] == 1.0 and row["ended_at"] == 2.5
        assert row["created_by"] == "llm:gpt"


class TestChangeListener:
    def test_listener_fires_on_mutation(self, td):
        seen = []
        register_change_listener(lambda t, p: seen.append((t, p)))
        c = _c(td, "X")
        rename_code(td, c["id"], new_name="Y", project="p")
        delete_code(td, c["id"], project="p")
        assert len(seen) == 3  # create, rename, delete
        assert seen[0] == (td, "p")

    def test_listener_exception_does_not_break_mutation(self, td):
        register_change_listener(lambda t, p: 1 / 0)
        c = _c(td, "Z")  # must not raise
        assert c["name"] == "Z"
