"""
Unit tests for MySQL UserState implementation.

This module tests the MySQL-backed UserState implementation to ensure
it behaves identically to the file-based implementation.
"""

import pytest
import tempfile
import os
import json
from unittest.mock import Mock, patch, MagicMock

pytest.importorskip("mysql.connector", reason="mysql-connector-python is required for MySQL database tests")

# Import the modules we're testing
from potato.database.connection import DatabaseManager
from potato.database.mysql_user_state import MysqlUserState
from potato.user_state_management import InMemoryUserState
from potato.phase import UserPhase
from potato.item_state_management import Item, Label, SpanAnnotation


class TestDatabaseManager:
    """Test the DatabaseManager class."""

    def test_init_with_valid_config(self):
        """Test DatabaseManager initialization with valid config."""
        config = {
            'database': {
                'type': 'mysql',
                'host': 'localhost',
                'port': 3306,
                'database': 'test_db',
                'username': 'test_user',
                'password': 'test_pass',
                'charset': 'utf8mb4',
                'pool_size': 5
            }
        }

        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_pool.return_value = Mock()
            db_manager = DatabaseManager(config)

            assert db_manager.config == config
            assert db_manager.pool is not None

    def test_init_missing_required_fields(self):
        """Test DatabaseManager initialization with missing required fields."""
        config = {
            'database': {
                'type': 'mysql',
                'host': 'localhost'
                # Missing database, username, password
            }
        }

        with pytest.raises(ValueError, match="Missing required database field"):
            DatabaseManager(config)

    def test_connection_context_manager(self):
        """Test the connection context manager."""
        config = {
            'database': {
                'type': 'mysql',
                'host': 'localhost',
                'database': 'test_db',
                'username': 'test_user',
                'password': 'test_pass'
            }
        }

        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_connection = Mock()
            mock_pool.return_value.get_connection.return_value = mock_connection

            db_manager = DatabaseManager(config)

            with db_manager.get_connection() as conn:
                assert conn == mock_connection

            mock_connection.close.assert_called_once()

    def test_connection_error_handling(self):
        """Test connection error handling."""
        config = {
            'database': {
                'type': 'mysql',
                'host': 'localhost',
                'database': 'test_db',
                'username': 'test_user',
                'password': 'test_pass'
            }
        }

        with patch('mysql.connector.pooling.MySQLConnectionPool') as mock_pool:
            mock_pool.side_effect = Exception("Connection failed")

            with pytest.raises(Exception, match="Connection failed"):
                DatabaseManager(config)


class _DocumentStore:
    """A stand-in for the two MySQL tables, behind the DatabaseManager API.

    It answers only the statements MysqlUserState issues. The real-server
    test, tests/server/test_testgap2_mysql.py, runs them against MySQL.
    """

    def __init__(self):
        self.documents, self.history = {}, {}

    def get_connection(self):
        store = self

        class Cursor:
            def execute(self, sql, params=()):
                self._rows = []
                if sql.startswith("INSERT INTO user_state_documents"):
                    store.documents[params[0]] = params[1]
                elif sql.startswith("SELECT state_json"):
                    doc = store.documents.get(params[0])
                    self._rows = [(doc,)] if doc is not None else []
                elif sql.startswith("SELECT action_json"):
                    self._rows = [(a,) for _, a in sorted(store.history.get(params[0], {}).items())]
                elif sql.startswith("SELECT user_id FROM user_state_documents"):
                    self._rows = [(u,) for u in store.documents]
                else:
                    raise AssertionError("unexpected SQL: " + sql)

            def executemany(self, sql, rows):
                assert sql.startswith("INSERT INTO annotation_history_log")
                for user, seq, action in rows:
                    assert seq not in store.history.setdefault(user, {})
                    store.history[user][seq] = action

            def fetchone(self):
                return self._rows[0] if self._rows else None

            def fetchall(self):
                return self._rows

        class Conn:
            def cursor(self):
                return Cursor()

            def commit(self):
                pass

        class Ctx:
            def __enter__(self):
                return Conn()

            def __exit__(self, *exc):
                return False
        return Ctx()


class TestMysqlUserState:
    """MysqlUserState is the file backend's state object stored in MySQL, so
    what goes in must come back: every kind of answer, the history, and the
    queue."""

    @pytest.fixture
    def items(self):
        import potato.item_state_management as ism_mod
        previous = ism_mod.ITEM_STATE_MANAGER
        ism_mod.ITEM_STATE_MANAGER = None
        ism = ism_mod.init_item_state_manager({})
        ism.add_items({"i1": {"id": "i1", "text": "x"}})
        yield ism
        ism_mod.ITEM_STATE_MANAGER = previous

    def test_a_saved_state_loads_back_unchanged(self, items):
        from potato.annotation_history import AnnotationHistoryManager
        db = _DocumentStore()
        state = MysqlUserState("u1", 5, db_manager=db)
        state.advance_to_phase(UserPhase.ANNOTATION, None)
        state.assign_instance(Item("i1", {"text": "x"}))
        state.add_label_annotation("i1", Label("s", "a"), "a")
        state.add_label_annotation("i1", Label("score", "slider"), 0)
        state.add_span_annotation("i1", SpanAnnotation("ent", "X", "X", 2, 5, id="sp1",
                                                       target_field="text", kb_id="Q1",
                                                       kb_source="wikidata", kb_label="One"), True)
        state.add_annotation_action(AnnotationHistoryManager.create_action(
            user_id="u1", instance_id="i1", action_type="add_label", schema_name="s",
            label_name="a", old_value=None, new_value="a"))
        state.save()
        state.save()   # a second save must not repeat the history

        loaded = MysqlUserState.load_from_db("u1", db)
        assert loaded.to_json() == state.to_json()
        assert len(loaded.annotation_history) == 1
        span = next(iter(loaded.get_span_annotations("i1")))
        assert (span.get_id(), span.get_target_field(), span.get_kb_id()) == ("sp1", "text", "Q1")
        assert loaded.get_label_annotations("i1")[Label("score", "slider")] == 0

    def test_an_unknown_user_is_not_created_by_looking(self):
        db = _DocumentStore()
        assert MysqlUserState.load_from_db("nobody", db) is None
        assert MysqlUserState.stored_user_ids(db) == []

    def test_the_annotation_count_is_items_not_rows(self):
        state = MysqlUserState("u1", db_manager=_DocumentStore())
        state.advance_to_phase(UserPhase.ANNOTATION, None)
        for iid in ("a", "b", "c"):
            state.add_label_annotation(iid, Label("s", "x"), "x")
        for iid in ("a", "b"):
            state.add_span_annotation(iid, SpanAnnotation("e", "X", "X", 0, 1), True)
        assert state.get_annotation_count() == 3


class TestDatabaseConfiguration:
    """Test database configuration validation."""

    def test_valid_mysql_config(self):
        """Test valid MySQL configuration."""
        config = {
            'database': {
                'type': 'mysql',
                'host': 'localhost',
                'database': 'test_db',
                'username': 'test_user',
                'password': 'test_pass'
            }
        }

        from tests.unit.test_config_validation import validate_database_config
        # Should not raise any exceptions
        validate_database_config(config)

    def test_invalid_database_type(self):
        """Test invalid database type."""
        config = {
            'database': {
                'type': 'invalid_type',
                'host': 'localhost',
                'database': 'test_db',
                'username': 'test_user',
                'password': 'test_pass'
            }
        }

        from tests.unit.test_config_validation import validate_database_config
        with pytest.raises(ValueError, match="Unsupported database type"):
            validate_database_config(config)

    def test_missing_mysql_password(self):
        """Test missing MySQL password."""
        config = {
            'database': {
                'type': 'mysql',
                'host': 'localhost',
                'database': 'test_db',
                'username': 'test_user'
                # Missing password
            }
        }

        from tests.unit.test_config_validation import validate_database_config
        with pytest.raises(ValueError, match="MySQL database requires password"):
            validate_database_config(config)

    def test_missing_required_fields(self):
        """Test missing required database fields."""
        config = {
            'database': {
                'type': 'mysql',
                'host': 'localhost'
                # Missing database, username, password
            }
        }

        from tests.unit.test_config_validation import validate_database_config
        with pytest.raises(ValueError, match="Missing required database field"):
            validate_database_config(config)
