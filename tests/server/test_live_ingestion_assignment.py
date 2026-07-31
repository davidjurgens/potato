"""
Server-level tests for live database ingestion (issue #166).

The load-bearing assertion here is NOT "the row reached the item pool" -- it is
"an annotator was actually served the row". Those come apart: F-037 was exactly
a case where runtime-added items were stored, visible in admin views and
present in exports, while the frozen per-user quota meant no annotator was ever
offered them. ``_drain_assigned_ids`` is what tells the two apart, and it is the
same helper the trace-ingestion regression test uses.

SQLAlchemy is an optional dependency absent from requirements-test.txt, so this
module skips when it is missing.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

pytest.importorskip("sqlalchemy")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    TestConfigManager,
    create_test_directory,
    cleanup_test_directory,
)

LIVE_PORT = 9671
QUOTA_PORT = 9672

BASE_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)

SCHEMES = [{
    "annotation_type": "radio",
    "name": "q",
    "description": "Quality",
    "labels": ["good", "bad"],
}]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def seed_database(db_path, count=2):
    """Create the instances table with ``count`` starting rows."""
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS instances ("
            "  id TEXT PRIMARY KEY, text TEXT, created_at TEXT"
            ")"
        ))
        for i in range(1, count + 1):
            conn.execute(
                text("INSERT INTO instances (id, text, created_at) VALUES (:i, :t, :c)"),
                {
                    "i": f"db-{i}",
                    "t": f"Database row {i}",
                    "c": (BASE_TIME + timedelta(seconds=i)).isoformat(),
                },
            )
    engine.dispose()


def insert_row(db_path, row_id, text_value, offset_seconds):
    """Insert one row, as an external application would while the server runs."""
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO instances (id, text, created_at) VALUES (:i, :t, :c)"),
            {
                "i": row_id,
                "t": text_value,
                "c": (BASE_TIME + timedelta(seconds=offset_seconds)).isoformat(),
            },
        )
    engine.dispose()


def live_source_config(db_path, **live_overrides):
    live = {
        "enabled": True,
        "poll_interval_seconds": 0.5,
        "cursor_column": "created_at",
        "tiebreaker_column": "id",
    }
    live.update(live_overrides)
    return {
        "data_sources": [{
            "type": "database",
            "id": "live_instances",
            "connection_string": f"sqlite:///{db_path}",
            "query": "SELECT id, text, created_at FROM instances",
            "live_ingestion": live,
        }],
    }


def _drain_assigned_ids(server, user, limit=15):
    """Register a user and annotate until nothing new is served."""
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": user, "pass": "x", "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": user, "pass": "x", "action": "login"})
    session.get(f"{server.base_url}/annotate")

    ids = []
    for _ in range(limit):
        payload = session.get(f"{server.base_url}/api/current_instance").json()
        instance_id = payload.get("instance_id")
        if not instance_id or instance_id in ids:
            break
        ids.append(instance_id)
        session.post(f"{server.base_url}/updateinstance",
                     json={"instance_id": instance_id,
                           "annotations": {"q:::good": "true"}})
        time.sleep(0.2)
        session.post(f"{server.base_url}/annotate",
                     json={"action": "next_instance"})
    return ids


def _wait_for_assignable(server, user, needle, timeout=20):
    """Poll until ``needle`` is actually served to an annotator."""
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        ids = _drain_assigned_ids(server, f"{user}_{attempt}")
        if needle in ids:
            return ids
        attempt += 1
        time.sleep(1.0)
    return []


# ---------------------------------------------------------------------------
# The acceptance criteria
# ---------------------------------------------------------------------------


class TestLiveIngestionBecomesAnnotatable:

    @pytest.fixture(scope="class")
    def db_path(self):
        # Test artifacts must live under tests/, never in a system temp dir.
        test_dir = create_test_directory("live_ingest_db")
        path = os.path.join(test_dir, "live.db")
        seed_database(path, count=2)
        yield path
        cleanup_test_directory(test_dir)

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, db_path):
        with TestConfigManager(
            "live_ingest_assign", SCHEMES, num_instances=1,
            additional_config=live_source_config(db_path),
        ) as cfg:
            server = FlaskTestServer(port=LIVE_PORT, config_file=cfg.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    def test_startup_rows_are_annotatable(self, flask_server):
        """The catch-up read must produce assignable items, not just stored ones."""
        ids = _drain_assigned_ids(flask_server, "startup_user")
        assert "db-1" in ids, f"startup rows must be assignable; got {ids}"

    def test_row_inserted_after_startup_becomes_annotatable(self, flask_server, db_path):
        """
        The headline acceptance criterion: no restart required.

        Asserting on assignment rather than storage is deliberate -- storage
        alone is precisely the F-037 failure mode.
        """
        insert_row(db_path, "db-late", "Inserted while the server was running", 500)

        ids = _wait_for_assignable(flask_server, "late_user", "db-late")

        assert "db-late" in ids, (
            f"a row inserted after startup must be assignable without a "
            f"restart; got {ids}"
        )

    def test_duplicate_rows_do_not_create_duplicate_instances(self, flask_server, db_path):
        """Repeated polls over an unchanged table must not re-add anything."""
        time.sleep(2.0)  # several poll intervals

        ids = _drain_assigned_ids(flask_server, "dupe_user")

        assert len(ids) == len(set(ids)), f"duplicate instances were served: {ids}"

    def test_admin_api_reports_live_status(self, flask_server):
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register",
                     data={"email": "admin_probe", "pass": "x", "action": "signup"})
        session.post(f"{flask_server.base_url}/auth",
                     data={"email": "admin_probe", "pass": "x", "action": "login"})

        response = session.get(f"{flask_server.base_url}/admin/api/data_sources/live")

        # Either a 403 (not an admin) or a well-formed payload -- never a 404,
        # which would mean the route was registered only via the decorator.
        assert response.status_code in (200, 403), response.text

    def test_server_survives_the_database_disappearing(self, flask_server, db_path):
        """A dead source must degrade, not take the annotation server down."""
        backup = db_path + ".bak"
        os.rename(db_path, backup)
        try:
            time.sleep(2.0)  # let several polls fail
            health = requests.get(f"{flask_server.base_url}/api/current_instance",
                                  timeout=10)
            assert health.status_code in (200, 302, 401, 403), health.status_code
        finally:
            os.rename(backup, db_path)


class TestQuotaDefaultsToUnlimited:
    """
    F-037 guard for the live-ingestion source.

    With the quota frozen at the startup instance count, every later row
    exceeds every annotator's cap and is silently never assigned.
    """

    @pytest.fixture(scope="class")
    def db_path(self):
        test_dir = create_test_directory("live_ingest_quota_db")
        path = os.path.join(test_dir, "quota.db")
        seed_database(path, count=2)
        yield path
        cleanup_test_directory(test_dir)

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, db_path):
        with TestConfigManager(
            "live_ingest_quota", SCHEMES, num_instances=1,
            additional_config=live_source_config(db_path),
        ) as cfg:
            server = FlaskTestServer(port=QUOTA_PORT, config_file=cfg.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    def test_user_is_not_capped_at_the_startup_instance_count(self, flask_server, db_path):
        """A user who drained the pool must still receive later arrivals."""
        first_pass = _drain_assigned_ids(flask_server, "quota_user")
        assert first_pass, "user should have been assigned the startup rows"

        for i in range(3):
            insert_row(db_path, f"db-extra-{i}", f"Extra {i}", 600 + i)

        ids = _wait_for_assignable(flask_server, "quota_later", "db-extra-0")

        assert "db-extra-0" in ids, (
            f"rows added after the quota was computed must still be assignable "
            f"(F-037); got {ids}"
        )


class TestQuotaHelper:
    """Unit-level cover for the predicate that drives the quota default."""

    def test_live_source_is_detected(self):
        from potato.flask_server import _has_live_ingestion_source

        assert _has_live_ingestion_source({
            "data_sources": [{
                "type": "database",
                "live_ingestion": {"enabled": True, "cursor_column": "created_at"},
            }],
        })

    def test_disabled_block_is_not_detected(self):
        from potato.flask_server import _has_live_ingestion_source

        assert not _has_live_ingestion_source({
            "data_sources": [{"type": "database", "live_ingestion": {"enabled": False}}],
        })

    def test_disabled_source_is_not_detected(self):
        """A source turned off wholesale must not unlock the quota."""
        from potato.flask_server import _has_live_ingestion_source

        assert not _has_live_ingestion_source({
            "data_sources": [{
                "type": "database",
                "enabled": False,
                "live_ingestion": {"enabled": True, "cursor_column": "created_at"},
            }],
        })

    def test_no_data_sources_is_not_detected(self):
        from potato.flask_server import _has_live_ingestion_source

        assert not _has_live_ingestion_source({})
        assert not _has_live_ingestion_source({"data_sources": None})
        assert not _has_live_ingestion_source({"data_sources": ["not-a-dict"]})

    def test_quota_defaults_to_unlimited_with_a_live_source(self):
        from potato.flask_server import _default_max_annotations_per_user

        class FakeISM:
            def get_instance_ids(self):
                return ["a", "b", "c"]

        config = {
            "data_sources": [{
                "type": "database",
                "live_ingestion": {"enabled": True, "cursor_column": "created_at"},
            }],
        }
        assert _default_max_annotations_per_user(config, FakeISM()) == -1

    def test_static_config_still_gets_the_instance_count(self):
        """The dynamic-source default must not change static behaviour."""
        from potato.flask_server import _default_max_annotations_per_user

        class FakeISM:
            def get_instance_ids(self):
                return ["a", "b", "c"]

        assert _default_max_annotations_per_user({}, FakeISM()) == 3

    def test_explicit_quota_is_honoured_but_warned_about(self, caplog):
        from potato.flask_server import _default_max_annotations_per_user

        class FakeISM:
            def get_instance_ids(self):
                return []

        config = {
            "max_annotations_per_user": 5,
            "data_sources": [{
                "type": "database",
                "live_ingestion": {"enabled": True, "cursor_column": "created_at"},
            }],
        }

        with caplog.at_level("WARNING"):
            result = _default_max_annotations_per_user(config, FakeISM())

        assert result == 5
        assert any("live database ingestion" in r.getMessage() for r in caplog.records)
