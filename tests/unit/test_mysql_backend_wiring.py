"""The MySQL user-state backend has to turn on when it is configured.

Until 2.10.2 it never did. user_state_management imported potato.database at
module level, and potato.database.mysql_user_state imports UserState back from
the half-initialised user_state_management. The circular ImportError was
swallowed, DATABASE_AVAILABLE was False in every install, and a server with
`database: {type: mysql}` validated, served, and wrote annotations to files
with nothing in the log. A missing driver or an unreachable server took the
same silent path. Both now stop the server.
"""

import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from potato.server_utils.config_module import ConfigValidationError, validate_database_config
from potato.user_state_management import UserStateManager


def mysql_config(port=3306):
    return {"database": {"type": "mysql", "host": "127.0.0.1", "port": port,
                         "database": "potato", "username": "u", "password": "p"}}


class TestTheBackendTurnsOn:
    def test_a_fresh_interpreter_turns_the_backend_on(self):
        """The circular import bit when user_state_management was imported
        first, which is the server's order, so run that order in a clean
        interpreter. Importing potato.database afterwards succeeds either way,
        so the test has to ask the manager, not the import."""
        pytest.importorskip("mysql.connector")
        code = ("import potato.user_state_management as u\n"
                "from unittest.mock import Mock, patch\n"
                "with patch('mysql.connector.pooling.MySQLConnectionPool', return_value=Mock()), \\\n"
                "        patch('potato.database.connection.DatabaseManager.create_tables'):\n"
                "    m = u.UserStateManager({'database': {'type': 'mysql', 'host': 'h',\n"
                "        'database': 'd', 'username': 'u', 'password': 'p'}})\n"
                "assert m.use_database, 'MySQL backend did not turn on'\n")
        result = subprocess.run([sys.executable, "-c", code],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_configured_mysql_creates_mysql_user_states(self):
        pytest.importorskip("mysql.connector")
        from potato.database import MysqlUserState
        with patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock()), \
                patch("potato.database.connection.DatabaseManager.create_tables"):
            manager = UserStateManager(mysql_config())
        assert manager.use_database is True
        assert manager._mysql_user_state_cls is MysqlUserState


class TestNoSilentFallbackToFiles:
    def test_an_unreachable_server_stops_startup(self):
        pytest.importorskip("mysql.connector")
        # Port 9 (discard) has nothing listening on a test machine.
        with pytest.raises(RuntimeError, match="does not fall back to files"):
            UserStateManager(mysql_config(port=9))

    def test_a_missing_driver_stops_startup_and_names_the_extra(self):
        with patch.dict(sys.modules, {"potato.database": None}):
            with pytest.raises(RuntimeError, match=r"potato-annotation\[mysql\]"):
                UserStateManager(mysql_config())

    def test_validate_names_the_extra_when_the_driver_is_missing(self):
        with patch("importlib.util.find_spec", return_value=None):
            with pytest.raises(ConfigValidationError, match=r"potato-annotation\[mysql\]"):
                validate_database_config(mysql_config()["database"])

    def test_no_database_block_means_files(self):
        manager = UserStateManager({})
        assert manager.use_database is False
