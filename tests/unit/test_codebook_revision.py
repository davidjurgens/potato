"""Codebook revision provenance: bump rules, stamping, stale worklist."""

import pytest

from potato.codebook import (
    clear_change_listeners,
    codes_added_since,
    create_code,
    current_revision,
    delete_code,
    instance_revision,
    move_under,
    record_annotation,
    recolor_code,
    rename_code,
    stale_instances,
)
from potato.codebook import revision
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.codebook.revision import (
    _CODES_REV_MIGRATION,
    _REVISION_MIGRATION,
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
    # store's 0001 must register before the ALTER (0002_codes_*).
    register_migration(_CODEBOOK_MIGRATION)
    register_migration(_REVISION_MIGRATION)
    register_migration(_CODES_REV_MIGRATION)
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


class TestRevisionBumpRules:
    def test_starts_at_zero(self, td):
        assert current_revision(td, "P") == 0

    def test_create_bumps(self, td):
        create_code(td, project="P", name="a", created_by="u")
        assert current_revision(td, "P") == 1
        create_code(td, project="P", name="b", created_by="u")
        assert current_revision(td, "P") == 2

    def test_delete_bumps(self, td):
        c = create_code(td, project="P", name="a", created_by="u")
        delete_code(td, c["id"], project="P")
        assert current_revision(td, "P") == 2

    def test_rename_recolor_move_do_not_bump(self, td):
        a = create_code(td, project="P", name="a", created_by="u")
        b = create_code(td, project="P", name="b", created_by="u")
        rev = current_revision(td, "P")  # 2
        rename_code(td, a["id"], new_name="a2", project="P")
        recolor_code(td, a["id"], color="#fff", project="P")
        move_under(td, b["id"], new_parent_id=a["id"], project="P")
        assert current_revision(td, "P") == rev  # unchanged

    def test_created_revision_stamped(self, td):
        a = create_code(td, project="P", name="a", created_by="u")
        b = create_code(td, project="P", name="b", created_by="u")
        assert a["created_revision"] == 1
        assert b["created_revision"] == 2


class TestProvenanceAndStale:
    def test_record_and_read(self, td):
        create_code(td, project="P", name="a", created_by="u")  # rev 1
        rev = record_annotation(td, "P", "i1", "alice")
        assert rev == 1
        assert instance_revision(td, "P", "i1", "alice") == 1

    def test_stale_after_new_code(self, td):
        create_code(td, project="P", name="a", created_by="u")  # rev1
        record_annotation(td, "P", "i1", "alice")               # @rev1
        # no staleness yet
        assert stale_instances(td, "P", "alice") == []
        create_code(td, project="P", name="b", created_by="u")  # rev2
        stale = stale_instances(td, "P", "alice")
        assert len(stale) == 1
        s = stale[0]
        assert s["instance_id"] == "i1"
        assert s["annotated_revision"] == 1
        assert s["current_revision"] == 2
        assert s["codes_added_since"] == ["b"]

    def test_codes_added_since_precision(self, td):
        create_code(td, project="P", name="a", created_by="u")  # rev1
        record_annotation(td, "P", "old", "alice")              # @rev1
        create_code(td, project="P", name="b", created_by="u")  # rev2
        record_annotation(td, "P", "mid", "alice")              # @rev2
        create_code(td, project="P", name="c", created_by="u")  # rev3
        # 'old' predates b & c; 'mid' predates only c
        assert codes_added_since(td, "P", 1) == ["b", "c"]
        assert codes_added_since(td, "P", 2) == ["c"]
        by_inst = {s["instance_id"]: s["codes_added_since"]
                   for s in stale_instances(td, "P", "alice")}
        assert by_inst == {"old": ["b", "c"], "mid": ["c"]}

    def test_re_record_clears_staleness(self, td):
        create_code(td, project="P", name="a", created_by="u")  # rev1
        record_annotation(td, "P", "i1", "alice")               # @rev1
        create_code(td, project="P", name="b", created_by="u")  # rev2
        assert len(stale_instances(td, "P", "alice")) == 1
        record_annotation(td, "P", "i1", "alice")               # re @rev2
        assert stale_instances(td, "P", "alice") == []

    def test_other_user_not_affected(self, td):
        create_code(td, project="P", name="a", created_by="u")
        record_annotation(td, "P", "i1", "alice")
        create_code(td, project="P", name="b", created_by="u")
        assert stale_instances(td, "P", "bob") == []
