"""Unit tests for the universal search backend (FTS5 + abstraction)."""

import pytest

from potato.persistence import clear_db_cache
from potato.search import (
    FTS5Backend,
    VectorBackend,
    clear_search,
    get_search,
    init_search,
    search_settings,
)
from potato.search.fts5 import _to_match_query


@pytest.fixture(autouse=True)
def _isolate():
    clear_db_cache()
    clear_search()
    yield
    clear_db_cache()
    clear_search()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


ROWS = [
    ("1", "The quick brown fox jumps over the lazy dog"),
    ("2", "A rare black swan appeared on the river"),
    ("3", "Quick thinking saved the project deadline"),
]


class TestMatchQuerySanitization:
    def test_tokenizes_and_prefixes(self):
        assert _to_match_query("quick fox") == '"quick"* "fox"*'

    def test_punctuation_is_safe(self):
        # Raw FTS5 would choke on these; we must not.
        assert _to_match_query('"; DROP TABLE x; --') == '"DROP"* "TABLE"* "x"*'

    def test_empty_returns_empty(self):
        assert _to_match_query("   ") == ""
        assert _to_match_query("!!!") == ""


class TestFTS5Backend:
    def test_available(self, td):
        assert FTS5Backend(td).available() is True

    def test_index_and_query(self, td):
        be = FTS5Backend(td)
        assert be.index(ROWS) == 3
        hits = be.query("quick")
        ids = {h.instance_id for h in hits}
        assert ids == {"1", "3"}
        assert all(h.snippet for h in hits)

    def test_query_ranked_and_limited(self, td):
        be = FTS5Backend(td)
        be.index(ROWS)
        hits = be.query("quick", limit=1)
        assert len(hits) == 1

    def test_no_match_returns_empty(self, td):
        be = FTS5Backend(td)
        be.index(ROWS)
        assert be.query("zzzznotpresent") == []

    def test_empty_query_returns_empty(self, td):
        be = FTS5Backend(td)
        be.index(ROWS)
        assert be.query("   ") == []

    def test_reindex_replaces(self, td):
        be = FTS5Backend(td)
        be.index(ROWS)
        be.index([("9", "completely different content here")])
        assert be.query("quick") == []
        assert {h.instance_id for h in be.query("different")} == {"9"}

    def test_injection_query_is_harmless(self, td):
        be = FTS5Backend(td)
        be.index(ROWS)
        assert be.query('"; DROP TABLE instance_fts; --') == []
        # table still works
        assert be.index(ROWS) == 3


class TestVectorBackendStub:
    def test_not_available(self):
        assert VectorBackend().available() is False


class TestService:
    def test_defaults(self):
        s = search_settings({})
        assert s == {
            "enabled": True, "backend": "fts5",
            "max_instances": 100000, "annotator_claim": False,
        }

    def test_overrides(self):
        s = search_settings({"search": {"enabled": False,
                                        "annotator_claim": True}})
        assert s["enabled"] is False and s["annotator_claim"] is True

    def test_init_disabled_returns_none(self, td):
        assert init_search({"search": {"enabled": False},
                            "task_dir": td}) is None
        assert get_search() is None

    def test_init_builds_and_indexes(self, td):
        be = init_search({"task_dir": td}, rows=ROWS)
        assert be is not None
        assert {h.instance_id for h in be.query("swan")} == {"2"}
        assert get_search() is be

    def test_init_twice_keeps_singleton(self, td):
        a = init_search({"task_dir": td}, rows=ROWS)
        b = init_search({"task_dir": td})
        assert a is b
