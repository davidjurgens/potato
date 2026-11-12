"""
Database connection management for Potato annotation platform.

Connection pooling and management for MySQL database operations.
"""

import mysql.connector
from mysql.connector import pooling
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages database connections and provides connection pooling for MySQL.

    This class handles the creation and management of database connections,
    including connection pooling for better performance and resource management.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the database manager with configuration.

        Args:
            config: Configuration dictionary containing database settings
        """
        self.config = config
        self.pool = None
        self._create_connection_pool()

    def _create_connection_pool(self):
        """Create the MySQL connection pool."""
        db_config = self.config.get('database', {})

        # Validate required database configuration
        required_fields = ['host', 'database', 'username', 'password']
        for field in required_fields:
            if field not in db_config:
                raise ValueError(f"Missing required database field: {field}")

        pool_config = {
            'host': db_config.get('host', 'localhost'),
            'port': db_config.get('port', 3306),
            'database': db_config['database'],
            'user': db_config['username'],
            'password': db_config['password'],
            'charset': db_config.get('charset', 'utf8mb4'),
            'pool_name': 'potato_pool',
            'pool_size': db_config.get('pool_size', 10),
            'pool_reset_session': True,
            'autocommit': False,  # We'll handle transactions explicitly
            'raise_on_warnings': True
        }

        try:
            self.pool = pooling.MySQLConnectionPool(**pool_config)
            logger.info(f"Created MySQL connection pool with {pool_config['pool_size']} connections")
        except mysql.connector.Error as e:
            logger.error(f"Failed to create database connection pool: {e}")
            raise

    @contextmanager
    def get_connection(self):
        """
        Get a database connection from the pool.

        Yields:
            mysql.connector.connection.MySQLConnection: Database connection

        Raises:
            mysql.connector.Error: If connection cannot be established
        """
        connection = None
        try:
            connection = self.pool.get_connection()
            yield connection
        except mysql.connector.Error as e:
            logger.error(f"Database connection error: {e}")
            if connection:
                connection.rollback()
            raise
        finally:
            if connection:
                try:
                    connection.close()
                except mysql.connector.Error as e:
                    logger.warning(f"Error closing connection: {e}")

    def test_connection(self) -> bool:
        """
        Test the database connection.

        Returns:
            bool: True if connection is successful, False otherwise
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                return result[0] == 1
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False

    def create_tables(self):
        """Create the tables annotator state is stored in, if they don't exist.

        Each table is looked for first. ``CREATE TABLE IF NOT EXISTS`` on an
        existing table raises warning 1050, and the pool raises on warnings,
        so the second boot against any database failed.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM information_schema.tables "
                           "WHERE table_schema = DATABASE()")
            existing = {row[0].lower() for row in cursor.fetchall()}

            # One document per annotator: the same JSON the file backend
            # writes to user_state.json.
            if "user_state_documents" not in existing:
                cursor.execute("""
                CREATE TABLE user_state_documents (
                    user_id VARCHAR(255) NOT NULL PRIMARY KEY,
                    state_json LONGTEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """)

            # Append-only annotation history, the counterpart of
            # annotation_history.jsonl.
            if "annotation_history_log" not in existing:
                cursor.execute("""
                CREATE TABLE annotation_history_log (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    seq INT NOT NULL,
                    action_json LONGTEXT NOT NULL,
                    UNIQUE KEY unique_user_seq (user_id, seq)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """)

            conn.commit()
            logger.info("Database tables created successfully")

    def drop_tables(self):
        """Drop all database tables (for testing)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Drop tables in reverse dependency order
            tables = ['annotation_history_log', 'user_state_documents']

            cursor.execute("SELECT table_name FROM information_schema.tables "
                           "WHERE table_schema = DATABASE()")
            existing = {row[0].lower() for row in cursor.fetchall()}
            for table in tables:
                if table in existing:
                    cursor.execute(f"DROP TABLE {table}")

            conn.commit()
            logger.info("Database tables dropped successfully")

    def close(self):
        """Close the database connection pool."""
        if self.pool:
            self.pool.close()
            logger.info("Database connection pool closed")