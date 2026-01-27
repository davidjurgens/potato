"""
Database connection management for Potato annotation platform.

This module provides connection pooling and management for MySQL database operations.
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
        """Create all required database tables if they don't exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Create user_states table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_states (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL UNIQUE,
                    current_phase VARCHAR(50) NOT NULL,
                    current_page VARCHAR(255),
                    current_instance_index INT DEFAULT -1,
                    max_assignments INT DEFAULT -1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_user_id (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create user_instance_assignments table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_instance_assignments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    instance_id VARCHAR(255) NOT NULL,
                    assignment_order INT NOT NULL,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_user_instance (user_id, instance_id),
                    INDEX idx_user_order (user_id, assignment_order),
                    FOREIGN KEY (user_id) REFERENCES user_states(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create label_annotations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS label_annotations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    instance_id VARCHAR(255) NOT NULL,
                    schema_name VARCHAR(255) NOT NULL,
                    label_name VARCHAR(255) NOT NULL,
                    label_value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_annotation (user_id, instance_id, schema_name, label_name),
                    INDEX idx_user_instance (user_id, instance_id),
                    FOREIGN KEY (user_id) REFERENCES user_states(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create span_annotations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS span_annotations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    instance_id VARCHAR(255) NOT NULL,
                    schema_name VARCHAR(255) NOT NULL,
                    span_name VARCHAR(255) NOT NULL,
                    span_title VARCHAR(255),
                    start_pos INT NOT NULL,
                    end_pos INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_instance (user_id, instance_id),
                    FOREIGN KEY (user_id) REFERENCES user_states(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create phase_annotations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS phase_annotations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    phase_name VARCHAR(50) NOT NULL,
                    page_name VARCHAR(255) NOT NULL,
                    schema_name VARCHAR(255) NOT NULL,
                    label_name VARCHAR(255) NOT NULL,
                    label_value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_phase_annotation (user_id, phase_name, page_name, schema_name, label_name),
                    FOREIGN KEY (user_id) REFERENCES user_states(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create behavioral_data table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS behavioral_data (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    instance_id VARCHAR(255) NOT NULL,
                    data_key VARCHAR(255) NOT NULL,
                    data_value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_instance (user_id, instance_id),
                    FOREIGN KEY (user_id) REFERENCES user_states(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create ai_hints table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_hints (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    instance_id VARCHAR(255) NOT NULL,
                    hint_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_hint (user_id, instance_id),
                    FOREIGN KEY (user_id) REFERENCES user_states(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            conn.commit()
            logger.info("Database tables created successfully")

    def drop_tables(self):
        """Drop all database tables (for testing)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Drop tables in reverse dependency order
            tables = [
                'ai_hints',
                'behavioral_data',
                'phase_annotations',
                'span_annotations',
                'label_annotations',
                'user_instance_assignments',
                'user_states'
            ]

            for table in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")

            conn.commit()
            logger.info("Database tables dropped successfully")

    def close(self):
        """Close the database connection pool."""
        if self.pool:
            self.pool.close()
            logger.info("Database connection pool closed")