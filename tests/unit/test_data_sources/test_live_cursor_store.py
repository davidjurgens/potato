"""
Tests for cursor serialization and persistence.

These deliberately avoid SQLAlchemy: it is an optional dependency and is not
in requirements.txt or requirements-test.txt, so CI has no SQLAlchemy. Cursor
round-tripping is core correctness and must be covered there.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from potato.data_sources.live_ingestion import CursorCodec, LiveCursorStore


class TestCursorCodec:
    """Type-tagged encode/decode of cursor values."""

    @pytest.mark.parametrize("value", [
        None,
        42,
        -1,
        3.5,
        "abc",
        True,
        False,
    ])
    def test_scalar_roundtrip(self, value):
        """Scalars survive encode -> JSON -> decode unchanged."""
        payload = json.loads(json.dumps(CursorCodec.encode(value)))
        assert CursorCodec.decode(payload) == value

    def test_bool_is_not_decoded_as_int(self):
        """bool subclasses int, so ordering in encode() matters."""
        assert CursorCodec.encode(True)["kind"] == "bool"
        assert CursorCodec.decode(CursorCodec.encode(True)) is True

    def test_datetime_roundtrip_preserves_timezone(self):
        """A tz-aware cursor must not come back naive.

        A naive datetime compared against a PostgreSQL timestamptz column is
        interpreted in the server's timezone, which silently shifts the
        ingestion boundary.
        """
        value = datetime(2026, 7, 29, 13, 45, 30, tzinfo=timezone(timedelta(hours=-4)))
        decoded = CursorCodec.decode(CursorCodec.encode(value))

        assert isinstance(decoded, datetime)
        assert decoded == value
        assert decoded.utcoffset() == value.utcoffset()

    def test_naive_datetime_roundtrip(self):
        value = datetime(2026, 7, 29, 13, 45, 30)
        decoded = CursorCodec.decode(CursorCodec.encode(value))
        assert decoded == value
        assert decoded.tzinfo is None

    def test_date_roundtrip(self):
        value = date(2026, 7, 29)
        decoded = CursorCodec.decode(CursorCodec.encode(value))
        assert isinstance(decoded, date)
        assert decoded == value

    def test_unknown_type_falls_back_to_str_with_warning(self, caplog):
        """Decimal/UUID degrade to text, and the operator is told once."""
        CursorCodec._WARNED_KINDS.discard("Decimal")

        with caplog.at_level("WARNING"):
            payload = CursorCodec.encode(Decimal("10.5"))

        assert payload == {"kind": "str", "raw": "10.5"}
        assert any("Decimal" in r.getMessage() for r in caplog.records)

    def test_unknown_type_warns_only_once(self, caplog):
        """A per-row warning would flood the log at poll frequency."""
        CursorCodec._WARNED_KINDS.discard("Decimal")
        CursorCodec.encode(Decimal("1"))

        caplog.clear()
        with caplog.at_level("WARNING"):
            CursorCodec.encode(Decimal("2"))

        assert not caplog.records

    def test_decode_of_garbage_returns_none(self):
        assert CursorCodec.decode(None) is None
        assert CursorCodec.decode({}) is None
        assert CursorCodec.decode("not a dict") is None

    def test_undecodable_datetime_degrades_to_text(self, caplog):
        """A corrupted stored value must not crash the poller."""
        with caplog.at_level("WARNING"):
            result = CursorCodec.decode({"kind": "datetime", "raw": "not-a-date"})

        assert result == "not-a-date"
        assert caplog.records


class TestLiveCursorStore:
    """Durable, atomic cursor persistence."""

    def test_get_before_set_returns_empty_pair(self, tmp_path):
        store = LiveCursorStore(str(tmp_path))
        assert store.get("nope") == (None, None)

    def test_set_then_get(self, tmp_path):
        store = LiveCursorStore(str(tmp_path))
        store.set("src", 17, "17")
        assert store.get("src") == (17, "17")

    def test_cursor_persists_across_new_store_instance(self, tmp_path):
        """This is the whole point: survive a restart."""
        moment = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
        LiveCursorStore(str(tmp_path)).set("src", moment, "99")

        reopened = LiveCursorStore(str(tmp_path))
        cursor, tiebreak = reopened.get("src")

        assert cursor == moment
        assert isinstance(cursor, datetime)
        assert tiebreak == "99"

    def test_sources_are_independent(self, tmp_path):
        store = LiveCursorStore(str(tmp_path))
        store.set("a", 1, "1")
        store.set("b", 2, "2")

        assert store.get("a") == (1, "1")
        assert store.get("b") == (2, "2")

    def test_clear_forgets_one_source_only(self, tmp_path):
        store = LiveCursorStore(str(tmp_path))
        store.set("a", 1, "1")
        store.set("b", 2, "2")
        store.clear("a")

        assert store.get("a") == (None, None)
        assert store.get("b") == (2, "2")

    def test_clear_of_unknown_source_is_a_noop(self, tmp_path):
        store = LiveCursorStore(str(tmp_path))
        store.clear("never-seen")  # must not raise

    def test_write_is_atomic_and_leaves_no_temp_file(self, tmp_path):
        """A crash mid-write must not be able to truncate the real file."""
        store = LiveCursorStore(str(tmp_path))
        store.set("src", 5, "5")

        files = os.listdir(tmp_path)
        assert LiveCursorStore.STATE_FILENAME in files
        assert not [f for f in files if f.endswith(".tmp")]

    def test_corrupt_state_file_resets_without_crashing(self, tmp_path, caplog):
        """Truncated JSON costs a re-ingest, not a failed boot."""
        path = tmp_path / LiveCursorStore.STATE_FILENAME
        path.write_text('{"src": {"cursor": {"kind": "int", "ra')

        with caplog.at_level("WARNING"):
            store = LiveCursorStore(str(tmp_path))

        assert store.get("src") == (None, None)
        assert caplog.records

    def test_non_dict_state_file_is_ignored(self, tmp_path):
        (tmp_path / LiveCursorStore.STATE_FILENAME).write_text('["not", "a", "map"]')
        store = LiveCursorStore(str(tmp_path))
        assert store.get("src") == (None, None)

    def test_output_dir_is_created_on_first_write(self, tmp_path):
        target = tmp_path / "does" / "not" / "exist"
        store = LiveCursorStore(str(target))
        store.set("src", 1, "1")

        assert (target / LiveCursorStore.STATE_FILENAME).exists()

    def test_all_returns_full_snapshot(self, tmp_path):
        store = LiveCursorStore(str(tmp_path))
        store.set("a", 1, "1")

        snapshot = store.all()
        assert "a" in snapshot
        assert snapshot["a"]["tiebreaker"] == "1"
        assert "updated_at" in snapshot["a"]
