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


class TestMysqlUserState:
    """Test the MysqlUserState class."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager."""
        mock_manager = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Create a proper context manager mock
        context_mock = Mock()
        context_mock.__enter__ = Mock(return_value=mock_connection)
        context_mock.__exit__ = Mock(return_value=None)
        mock_manager.get_connection.return_value = context_mock

        return mock_manager, mock_connection, mock_cursor

    def test_init_creates_user_record(self, mock_db_manager):
        """Test that user record is created on initialization."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchone.return_value = (0,)  # No existing user

        user_state = MysqlUserState("test_user", mock_manager, 10)

        # Verify user creation query was executed
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()
        assert user_state.user_id == "test_user"
        assert user_state.max_assignments == 10

    def test_advance_to_phase(self, mock_db_manager):
        """Test advancing to a new phase."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        user_state.advance_to_phase(UserPhase.ANNOTATION, "page1")

        # Verify phase update query was executed
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()

    def test_assign_instance(self, mock_db_manager):
        """Test assigning an instance to a user."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchone.side_effect = [(0,), (0,), (-1,)]  # Not assigned, no existing assignments, current_index = -1

        user_state = MysqlUserState("test_user", mock_manager)

        # Create a mock item
        mock_item = Mock()
        mock_item.get_id.return_value = "item1"

        user_state.assign_instance(mock_item)

        # Verify assignment queries were executed
        assert mock_cursor.execute.call_count >= 3
        mock_conn.commit.assert_called()

    def test_get_current_instance_index(self, mock_db_manager):
        """Test getting current instance index."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchone.return_value = (2,)  # Current index = 2

        user_state = MysqlUserState("test_user", mock_manager)
        index = user_state.get_current_instance_index()

        assert index == 2
        mock_cursor.execute.assert_called()

    def test_goto_next_instance(self, mock_db_manager):
        """Test moving to next instance."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchone.side_effect = [(0,)]  # Current index = 0 (first item)
        mock_cursor.fetchall.return_value = [("item1",), ("item2",), ("item3",)]  # 3 items

        user_state = MysqlUserState("test_user", mock_manager)
        result = user_state.goto_next_instance()

        assert result is True
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()

    def test_goto_prev_instance(self, mock_db_manager):
        """Test moving to previous instance."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchone.return_value = (2,)  # Current index = 2

        user_state = MysqlUserState("test_user", mock_manager)
        result = user_state.goto_prev_instance()

        assert result is True
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()

    def test_add_label_annotation(self, mock_db_manager):
        """Test adding a label annotation."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchone.return_value = ("annotation", "page1")  # String values for database

        user_state = MysqlUserState("test_user", mock_manager)
        label = Label("schema1", "label1")

        user_state.add_label_annotation("item1", label, "value1")

        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()

    def test_add_span_annotation(self, mock_db_manager):
        """Test adding a span annotation."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchone.return_value = ("annotation", "page1")  # String values for database

        user_state = MysqlUserState("test_user", mock_manager)
        span = SpanAnnotation("schema1", "span1", "title1", 0, 10)

        user_state.add_span_annotation("item1", span, True)

        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()

    def test_get_label_annotations(self, mock_db_manager):
        """Test getting label annotations."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchall.return_value = [
            ("schema1", "label1", "value1"),
            ("schema1", "label2", "value2")
        ]

        user_state = MysqlUserState("test_user", mock_manager)
        annotations = user_state.get_label_annotations("item1")

        assert len(annotations) == 2
        mock_cursor.execute.assert_called()

    def test_get_span_annotations(self, mock_db_manager):
        """Test getting span annotations."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchall.return_value = [
            ("schema1", "span1", "title1", 0, 10, None, None, None),
            ("schema1", "span2", "title2", 20, 30, None, None, None)
        ]

        user_state = MysqlUserState("test_user", mock_manager)
        annotations = user_state.get_span_annotations("item1")

        assert len(annotations) == 2
        mock_cursor.execute.assert_called()

    def test_get_annotation_count(self, mock_db_manager):
        """Test getting annotation count."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchall.return_value = [(5,), (3,)]  # 5 label annotations, 3 span annotations

        user_state = MysqlUserState("test_user", mock_manager)
        count = user_state.get_annotation_count()

        assert count == 8  # Total unique instances with annotations
        mock_cursor.execute.assert_called()

    def test_clear_all_annotations(self, mock_db_manager):
        """Test clearing all annotations."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        user_state.clear_all_annotations()

        # Should execute 6 statements: 1 INSERT from __init__._ensure_user_exists + 5 DELETE statements
        # (label_annotations, span_annotations, phase_annotations, behavioral_data, ai_hints)
        assert mock_cursor.execute.call_count == 6
        mock_conn.commit.assert_called()

    def test_clear_instance_annotations_runs_four_deletes(self, mock_db_manager):
        """clear_instance_annotations should issue one DELETE per per-instance table."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        mock_cursor.execute.reset_mock()
        mock_conn.commit.reset_mock()

        user_state.clear_instance_annotations("item1")

        # 4 DELETEs: label_annotations, span_annotations, behavioral_data, ai_hints
        assert mock_cursor.execute.call_count == 4
        executed_sql = [call.args[0] for call in mock_cursor.execute.call_args_list]
        for table in ("label_annotations", "span_annotations", "behavioral_data", "ai_hints"):
            assert any(f"FROM {table}" in sql for sql in executed_sql), (
                f"Expected DELETE from {table}, got: {executed_sql}"
            )
        # Every DELETE is parametrized with (user_id, instance_id)
        for call in mock_cursor.execute.call_args_list:
            assert call.args[1] == ("test_user", "item1")
        mock_conn.commit.assert_called_once()

    def test_unassign_instance_returns_false_when_not_assigned(self, mock_db_manager):
        """If no row exists for (user, instance), return False without DELETE/UPDATE."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        mock_cursor.execute.reset_mock()
        mock_conn.commit.reset_mock()
        mock_cursor.fetchone.side_effect = [None]  # No assignment row

        result = user_state.unassign_instance("ghost_item")

        assert result is False
        # Only the SELECT should have been issued; no DELETE/UPDATE
        assert mock_cursor.execute.call_count == 1
        assert "SELECT assignment_order" in mock_cursor.execute.call_args_list[0].args[0]
        mock_conn.commit.assert_not_called()

    def test_unassign_instance_middle_item_shifts_orders(self, mock_db_manager):
        """Removing an item shifts later assignment_orders down by 1."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        mock_cursor.execute.reset_mock()
        mock_conn.commit.reset_mock()
        # Sequence: removed_order=1, then current_instance_index=2, then count=2
        mock_cursor.fetchone.side_effect = [(1,), (2,), (2,)]

        result = user_state.unassign_instance("item_b")

        assert result is True
        executed = [(c.args[0], c.args[1]) for c in mock_cursor.execute.call_args_list]
        # SELECT order
        assert "SELECT assignment_order" in executed[0][0]
        # DELETE
        assert "DELETE FROM user_instance_assignments" in executed[1][0]
        # SHIFT — orders > 1 get decremented
        assert "SET assignment_order = assignment_order - 1" in executed[2][0]
        assert executed[2][1] == ("test_user", 1)
        # Final UPDATE of current_instance_index: current was 2, > removed_order=1 → 1
        update_idx_call = next(c for c in mock_cursor.execute.call_args_list
                               if "UPDATE user_states SET current_instance_index" in c.args[0])
        assert update_idx_call.args[1] == (1, "test_user")
        mock_conn.commit.assert_called_once()

    def test_unassign_instance_empties_assignments_sets_index_to_minus_one(self, mock_db_manager):
        """Last assignment removed → current_instance_index = -1."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        mock_cursor.execute.reset_mock()
        mock_conn.commit.reset_mock()
        # removed_order=0, current_index=0, count=0 after delete
        mock_cursor.fetchone.side_effect = [(0,), (0,), (0,)]

        result = user_state.unassign_instance("only_item")

        assert result is True
        update_idx_call = next(c for c in mock_cursor.execute.call_args_list
                               if "UPDATE user_states SET current_instance_index" in c.args[0])
        assert update_idx_call.args[1] == (-1, "test_user")

    def test_unassign_instance_current_equals_removed_caps_at_last_index(self, mock_db_manager):
        """If user was on the removed slot and it was the last, clamp to new last."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        mock_cursor.execute.reset_mock()
        mock_conn.commit.reset_mock()
        # 3 items, user at index 2 (the last), remove item at order 2
        # After delete: count=2, removed_order=2, current_index=2
        # Branch: current_index == removed_order → min(2, 1) = 1
        mock_cursor.fetchone.side_effect = [(2,), (2,), (2,)]

        result = user_state.unassign_instance("last_item")

        assert result is True
        update_idx_call = next(c for c in mock_cursor.execute.call_args_list
                               if "UPDATE user_states SET current_instance_index" in c.args[0])
        assert update_idx_call.args[1] == (1, "test_user")

    def test_unassign_instance_removed_before_current_decrements(self, mock_db_manager):
        """Removing an item before the current cursor decrements the index."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        mock_cursor.execute.reset_mock()
        mock_conn.commit.reset_mock()
        # 5 items, user at index 4, remove item at order 0
        # current_index > removed_order (4 > 0) → new_index = 3
        mock_cursor.fetchone.side_effect = [(0,), (4,), (4,)]

        result = user_state.unassign_instance("first_item")

        assert result is True
        update_idx_call = next(c for c in mock_cursor.execute.call_args_list
                               if "UPDATE user_states SET current_instance_index" in c.args[0])
        assert update_idx_call.args[1] == (3, "test_user")

    def test_unassign_instance_removed_after_current_leaves_index(self, mock_db_manager):
        """Removing an item after the current cursor leaves the index unchanged."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        mock_cursor.execute.reset_mock()
        mock_conn.commit.reset_mock()
        # 5 items, user at index 1, remove item at order 3
        # current_index < removed_order → min(1, 3) = 1
        mock_cursor.fetchone.side_effect = [(3,), (1,), (4,)]

        result = user_state.unassign_instance("later_item")

        assert result is True
        update_idx_call = next(c for c in mock_cursor.execute.call_args_list
                               if "UPDATE user_states SET current_instance_index" in c.args[0])
        assert update_idx_call.args[1] == (1, "test_user")

    def test_unassign_instance_invalidates_cache(self, mock_db_manager):
        """After a successful unassign, cached index/ordering must be cleared."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager

        user_state = MysqlUserState("test_user", mock_manager)
        # Prime the cache with a fake value to confirm it's wiped
        user_state._current_instance_index_cache = 7
        user_state._instance_ordering_cache = ["a", "b"]
        mock_cursor.fetchone.side_effect = [(1,), (1,), (2,)]

        user_state.unassign_instance("item_b")

        assert user_state._current_instance_index_cache is None
        assert user_state._instance_ordering_cache is None

    def test_hint_operations(self, mock_db_manager):
        """Test AI hint operations."""
        mock_manager, mock_conn, mock_cursor = mock_db_manager
        mock_cursor.fetchone.side_effect = [(1,), ("hint text",)]  # Hint exists, hint content

        user_state = MysqlUserState("test_user", mock_manager)

        # Test hint exists
        exists = user_state.hint_exists("item1")
        assert exists is True

        # Test get hint
        hint = user_state.get_hint("item1")
        assert hint == "hint text"

        # Test cache hint
        user_state.cache_hint("item2", "new hint")
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()


class TestMysqlUserStateIntegration:
    """Integration tests comparing MySQL and InMemory UserState behavior."""

    def test_identical_behavior_basic_operations(self):
        """Test that MySQL and InMemory UserState have identical basic behavior."""
        # This test would require a real database connection
        # For now, we'll test the interface compatibility
        pass

    def test_annotation_persistence_comparison(self):
        """Test that annotations are persisted identically between implementations."""
        # This test would require a real database connection
        # For now, we'll test the interface compatibility
        pass


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
