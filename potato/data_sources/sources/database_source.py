"""
SQL Database data source.

This module provides data loading from SQL databases using SQLAlchemy,
supporting PostgreSQL, MySQL, SQLite, and other databases.
"""

import logging
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import quote_plus

from potato.data_sources.base import DataSource, SourceConfig

logger = logging.getLogger(__name__)


class DatabaseSource(DataSource):
    """
    Data source for SQL databases.

    Loads data from SQL databases using SQLAlchemy, supporting:
    - PostgreSQL, MySQL, SQLite
    - Custom SQL queries or simple table select
    - Connection via connection string or individual parameters
    - Incremental loading via OFFSET/LIMIT

    Configuration with connection string:
        type: database
        connection_string: "${DATABASE_URL}"
        query: "SELECT id, text, metadata FROM items WHERE status = 'pending'"

    Configuration with individual parameters:
        type: database
        dialect: postgresql        # postgresql, mysql, sqlite
        host: "localhost"
        port: 5432
        database: "annotations"
        username: "${DB_USER}"
        password: "${DB_PASSWORD}"
        table: "items"             # Simple table select
        id_column: "id"
        text_column: "text"

    Note: Requires SQLAlchemy and appropriate database driver:
          pip install sqlalchemy psycopg2-binary  # PostgreSQL
          pip install sqlalchemy pymysql          # MySQL
    """

    # Check for optional dependencies
    _HAS_SQLALCHEMY = None

    @classmethod
    def _check_dependencies(cls) -> bool:
        """Check if SQLAlchemy is available."""
        if cls._HAS_SQLALCHEMY is None:
            try:
                import sqlalchemy
                cls._HAS_SQLALCHEMY = True
            except ImportError:
                cls._HAS_SQLALCHEMY = False
        return cls._HAS_SQLALCHEMY

    # Dialect to driver mapping
    DIALECT_DRIVERS = {
        'postgresql': 'postgresql+psycopg2',
        'postgres': 'postgresql+psycopg2',
        'mysql': 'mysql+pymysql',
        'sqlite': 'sqlite',
        'mssql': 'mssql+pyodbc',
    }

    def __init__(self, config: SourceConfig):
        """Initialize the database source."""
        super().__init__(config)

        # Connection options
        self._connection_string = config.config.get("connection_string", "")
        self._dialect = config.config.get("dialect", "")
        self._host = config.config.get("host", "localhost")
        self._port = config.config.get("port")
        self._database = config.config.get("database", "")
        self._username = config.config.get("username", "")
        self._password = config.config.get("password", "")

        # Query options
        self._query = config.config.get("query", "")
        self._table = config.config.get("table", "")
        self._id_column = config.config.get("id_column", "id")
        self._text_column = config.config.get("text_column", "text")

        # Connection pooling options
        self._pool_size = config.config.get("pool_size", 5)
        self._pool_timeout = config.config.get("pool_timeout", 30)

        self._engine = None
        self._total_count: Optional[int] = None

    def get_source_id(self) -> str:
        """Get unique identifier."""
        return self._source_id

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = []

        # Must have connection string OR individual parameters
        if not self._connection_string:
            if not self._dialect:
                errors.append(
                    "Either 'connection_string' or 'dialect' is required"
                )
            elif self._dialect not in self.DIALECT_DRIVERS:
                errors.append(
                    f"Unknown dialect '{self._dialect}'. "
                    f"Supported: {', '.join(self.DIALECT_DRIVERS.keys())}"
                )

            if not self._database and self._dialect != 'sqlite':
                errors.append("'database' is required")

        # Must have query OR table
        if not self._query and not self._table:
            errors.append("Either 'query' or 'table' is required")

        return errors

    def is_available(self) -> bool:
        """Check if the source is available."""
        if not self._check_dependencies():
            logger.warning(
                "SQLAlchemy not installed. "
                "Install with: pip install sqlalchemy"
            )
            return False

        return True

    def _build_connection_string(self) -> str:
        """Build connection string from individual parameters."""
        if self._connection_string:
            return self._connection_string

        driver = self.DIALECT_DRIVERS.get(self._dialect, self._dialect)

        if self._dialect == 'sqlite':
            return f"sqlite:///{self._database}"

        # Build URL with credentials
        if self._username:
            userpass = self._username
            if self._password:
                userpass += f":{quote_plus(self._password)}"
            userpass += "@"
        else:
            userpass = ""

        host_port = self._host
        if self._port:
            host_port += f":{self._port}"

        return f"{driver}://{userpass}{host_port}/{self._database}"

    def _get_engine(self):
        """Get or create the SQLAlchemy engine."""
        if self._engine:
            return self._engine

        from sqlalchemy import create_engine

        connection_string = self._build_connection_string()

        # Create engine with connection pooling
        engine_kwargs = {}
        if self._dialect != 'sqlite':
            engine_kwargs = {
                'pool_size': self._pool_size,
                'pool_timeout': self._pool_timeout,
                'pool_pre_ping': True,  # Enable connection health checks
            }

        self._engine = create_engine(connection_string, **engine_kwargs)
        return self._engine

    def _build_query(self, offset: int = 0, limit: Optional[int] = None) -> str:
        """Build the SQL query with optional pagination."""
        if self._query:
            base_query = self._query.rstrip(';')
        else:
            # Build simple SELECT from table
            base_query = f"SELECT * FROM {self._table}"

        # Add pagination
        if limit is not None or offset > 0:
            # Wrap in subquery for safety
            if limit is not None:
                base_query += f" LIMIT {limit}"
            if offset > 0:
                base_query += f" OFFSET {offset}"

        return base_query

    def _row_to_dict(self, row, columns: List[str]) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        item = {}
        for i, col in enumerate(columns):
            value = row[i]
            # Handle special types
            if hasattr(value, 'isoformat'):  # datetime
                value = value.isoformat()
            elif hasattr(value, 'tobytes'):  # memoryview/bytes
                value = value.tobytes().decode('utf-8', errors='replace')
            item[col] = value
        return item

    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Read items from the database."""
        from sqlalchemy import text

        engine = self._get_engine()
        query = self._build_query(offset=start, limit=count)

        with engine.connect() as connection:
            result = connection.execute(text(query))

            # Get column names
            columns = list(result.keys())

            for row in result:
                item = self._row_to_dict(row, columns)
                yield item

    def get_total_count(self) -> Optional[int]:
        """Get total number of items."""
        if self._total_count is not None:
            return self._total_count

        from sqlalchemy import text

        try:
            engine = self._get_engine()

            if self._query:
                # Wrap query in count
                count_query = f"SELECT COUNT(*) FROM ({self._query.rstrip(';')}) AS subquery"
            else:
                count_query = f"SELECT COUNT(*) FROM {self._table}"

            with engine.connect() as connection:
                result = connection.execute(text(count_query))
                self._total_count = result.scalar()
                return self._total_count

        except Exception as e:
            logger.error(f"Error getting count: {e}")
            return None

    def supports_partial_reading(self) -> bool:
        """Database sources support efficient partial reading via OFFSET/LIMIT."""
        return True

    def refresh(self) -> bool:
        """Refresh by clearing cached count."""
        self._total_count = None
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get source status."""
        status = super().get_status()
        status["dialect"] = self._dialect
        status["database"] = self._database
        status["table"] = self._table
        status["has_custom_query"] = bool(self._query)
        return status

    def close(self) -> None:
        """Close the database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
        self._total_count = None
