"""
SQL Database data source.

This module provides data loading from SQL databases using SQLAlchemy,
supporting PostgreSQL, MySQL, SQLite, and other databases.
"""

import logging
import re
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
    - Live ingestion: cursor-based polling for rows added after startup

    Live ingestion configuration::

        type: database
        connection_string: "${DATABASE_URL}"
        query: "SELECT id, text, created_at FROM instances"
        live_ingestion:
          enabled: true
          poll_interval_seconds: 5
          cursor_column: created_at
          tiebreaker_column: id      # defaults to id_column

    Potato generates the keyset predicate, the ordering and the LIMIT. If the
    query instead contains its own ``:cursor`` placeholder, Potato only binds
    the value and the admin owns correctness -- including the tie-breaker.

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

    # Pattern for safe SQL identifiers (table/column names)
    # Allows: word chars, dots for schema.table, backticks/brackets for quoted identifiers
    _SAFE_IDENTIFIER_RE = re.compile(r'\A[\w][\w.$]*\Z', re.ASCII)

    @staticmethod
    def _validate_identifier(name: str) -> str:
        """
        Validate a SQL identifier (table or column name) against injection.

        Only allows alphanumeric characters, underscores, dots (for schema.table),
        and dollar signs. Rejects anything else to prevent SQL injection.

        Raises:
            ValueError: If the identifier contains unsafe characters
        """
        if not name or not DatabaseSource._SAFE_IDENTIFIER_RE.match(name):
            raise ValueError(
                f"Invalid SQL identifier: '{name}'. "
                f"Only alphanumeric characters, underscores, dots, and "
                f"dollar signs are allowed."
            )
        return name

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

        # Live ingestion (cursor-based polling for rows added after startup)
        from potato.data_sources.live_ingestion import LiveIngestionConfig
        self._live = LiveIngestionConfig.from_dict(config.config.get("live_ingestion"))

        self._engine = None
        self._total_count: Optional[int] = None
        self._live_columns: Optional[List[str]] = None

    def get_source_id(self) -> str:
        """Get unique identifier."""
        return self._source_id

    @property
    def live_config(self):
        """The parsed ``live_ingestion`` block for this source."""
        return self._live

    def _uses_explicit_cursor(self) -> bool:
        """
        True when the admin's own query carries a ``:cursor`` placeholder.

        In that mode Potato binds the value and otherwise stays out of the
        way -- the admin owns the WHERE clause, the ordering and the
        tie-breaker.
        """
        return ":cursor" in (self._query or "")

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

        # Validate table name if provided (prevent SQL injection)
        if self._table:
            try:
                self._validate_identifier(self._table)
            except ValueError as e:
                errors.append(str(e))

        errors.extend(self._validate_live_config())

        return errors

    def _validate_live_config(self) -> List[str]:
        """
        Validate the ``live_ingestion`` block.

        Surfaced through ``validate_config()`` so a bad block is reported by
        ``DataSourceManager._init_sources()`` rather than silently dropping
        the source (that method catches every exception per source and moves
        on, which is how a misconfigured source can vanish with one log line).
        """
        if not self._live.enabled:
            return []

        errors = [f"live_ingestion.{e}" for e in self._live.validate()]

        if self._uses_explicit_cursor():
            # ``x > NULL`` is NULL, so an unset cursor matches zero rows --
            # forever, silently. Refuse to start in that state.
            if self._live.initial_cursor is None:
                errors.append(
                    "query contains ':cursor', so live_ingestion.initial_cursor "
                    "is required (a NULL cursor makes 'col > :cursor' match no "
                    "rows at all)"
                )
        elif not self._live.cursor_column:
            errors.append(
                "live_ingestion requires 'cursor_column' (or a query containing "
                "a ':cursor' placeholder)"
            )

        for field_name in ("cursor_column", "tiebreaker_column"):
            value = getattr(self._live, field_name)
            if value:
                try:
                    self._validate_identifier(value)
                except ValueError:
                    errors.append(
                        f"live_ingestion.{field_name} '{value}' is not a valid SQL "
                        f"identifier (letters, digits, underscores and dots only)"
                    )

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
            # Validate table name to prevent SQL injection
            safe_table = self._validate_identifier(self._table)
            base_query = f"SELECT * FROM {safe_table}"

        # Add pagination using validated integer values
        if limit is not None or offset > 0:
            if limit is not None:
                base_query += f" LIMIT {int(limit)}"
            if offset > 0:
                base_query += f" OFFSET {int(offset)}"

        return base_query

    def _base_subquery(self) -> str:
        """The admin-supplied query (or table select) as a wrappable subquery."""
        if self._query:
            return self._query.rstrip(';')
        safe_table = self._validate_identifier(self._table)
        return f"SELECT * FROM {safe_table}"

    def _tiebreak_column(self) -> str:
        """Second sort key. Defaults to the id column."""
        return self._live.tiebreaker_column or self._id_column

    def _build_live_query(self, has_cursor: bool, has_tiebreak: bool, limit: int) -> str:
        """
        Build the managed keyset query (mode A).

        Notes on portability, each of which is a bug avoided:

        - The no-cursor case emits a *different string* rather than
          ``:cursor_value IS NULL OR ...``. An untyped NULL bind inside a
          comparison makes some PostgreSQL drivers raise "could not determine
          data type of parameter", and it leaves a dead predicate for the
          planner to chew on.
        - The tie-break uses the three-term OR form, not row-value syntax
          ``(a, b) > (c, d)``. SQL Server has no row-value comparison and
          SQLite only gained it in 3.15.
        - Identifiers are validated, never bound; values are bound, never
          interpolated.
        """
        cursor_col = self._validate_identifier(self._live.cursor_column)
        tiebreak_col = self._validate_identifier(self._tiebreak_column())

        sql = f"SELECT * FROM ({self._base_subquery()}) AS potato_live"

        clauses = []
        if has_cursor:
            if has_tiebreak:
                clauses.append(
                    f"({cursor_col} > :cursor_value OR "
                    f"({cursor_col} = :cursor_value AND {tiebreak_col} > :cursor_tiebreak))"
                )
            else:
                clauses.append(f"{cursor_col} > :cursor_value")

        if self._live.safety_lag_seconds > 0:
            # Keep the read frontier behind the write frontier, so a
            # transaction still in flight cannot be stepped over.
            clauses.append(f"{cursor_col} <= :safety_horizon")

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += f" ORDER BY {cursor_col}, {tiebreak_col} LIMIT {int(limit)}"
        return sql

    def _build_explicit_cursor_query(self, limit: int) -> str:
        """
        Mode B: the admin's query already contains ``:cursor``.

        Potato only appends the LIMIT. Ordering and tie-breaking are the
        admin's responsibility, as documented.
        """
        return f"{self._query.rstrip(';')} LIMIT {int(limit)}"

    def _safety_horizon(self):
        """Upper bound on readable rows when ``safety_lag_seconds`` is set."""
        from datetime import datetime, timedelta, timezone
        return datetime.now(timezone.utc) - timedelta(seconds=self._live.safety_lag_seconds)

    def supports_live_ingestion(self) -> bool:
        """True when a ``live_ingestion`` block enabled polling for this source."""
        return bool(self._live.enabled)

    def read_since(
        self,
        cursor: Optional[Any] = None,
        tiebreaker: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Read rows ordered after ``(cursor, tiebreaker)``.

        Yields:
            LiveRow instances carrying the item dict, the RAW cursor value and
            the row id.

        Raises:
            RuntimeError: If live ingestion is not enabled, or the cursor
                column is missing from the query's result columns
        """
        from sqlalchemy import text

        from potato.data_sources.base import LiveRow

        if not self._live.enabled:
            raise RuntimeError(
                f"Source {self.source_id} does not have live_ingestion enabled"
            )

        batch = int(limit or self._live.batch_size)
        params: Dict[str, Any] = {}

        if self._uses_explicit_cursor():
            sql = self._build_explicit_cursor_query(batch)
            params["cursor"] = cursor if cursor is not None else self._live.initial_cursor
            if ":cursor_id" in sql:
                params["cursor_id"] = tiebreaker
        else:
            sql = self._build_live_query(
                has_cursor=cursor is not None,
                has_tiebreak=tiebreaker is not None,
                limit=batch,
            )
            if cursor is not None:
                params["cursor_value"] = cursor
                if tiebreaker is not None:
                    params["cursor_tiebreak"] = tiebreaker
            if self._live.safety_lag_seconds > 0:
                params["safety_horizon"] = self._safety_horizon()

        engine = self._get_engine()
        cursor_col = self._live.cursor_column

        if not self._uses_explicit_cursor():
            # Check the column exists before running the real query. The
            # generated ORDER BY references it, so otherwise the backend
            # raises its own opaque "no such column" first and the admin
            # never sees the actionable message.
            self._assert_cursor_column_present(engine, cursor_col)

        with engine.connect() as connection:
            result = connection.execute(text(sql), params)
            columns = list(result.keys())

            id_index = columns.index(self._id_column) if self._id_column in columns else 0
            cursor_index = columns.index(cursor_col) if cursor_col in columns else None

            for row in result:
                # Read the cursor from the RAW row, before _row_to_dict
                # isoformat()s any datetime. Re-binding an ISO string against
                # a typed timestamp column is not reliable across backends.
                raw_cursor = row[cursor_index] if cursor_index is not None else None
                self._reject_opaque_cursor(raw_cursor, cursor_col)

                item = self._row_to_dict(row, columns)
                yield LiveRow(
                    item=item,
                    cursor_value=raw_cursor,
                    row_id=str(row[id_index]),
                )

    def _assert_cursor_column_present(self, engine, cursor_col: str) -> None:
        """
        Verify the cursor column is in the query's result columns.

        Uses a ``LIMIT 0`` probe, so it costs a round trip but reads no rows.
        The result is cached: this only needs to be true once.
        """
        if self._live_columns is not None:
            return

        from sqlalchemy import text

        probe = f"SELECT * FROM ({self._base_subquery()}) AS potato_live LIMIT 0"
        with engine.connect() as connection:
            self._live_columns = list(connection.execute(text(probe)).keys())

        if cursor_col not in self._live_columns:
            raise RuntimeError(
                f"live_ingestion cursor_column '{cursor_col}' is not present in "
                f"the query result columns {self._live_columns}; add it to the "
                f"SELECT list"
            )

    @staticmethod
    def _reject_opaque_cursor(value: Any, column: str) -> None:
        """Fail fast on a cursor type that cannot be compared after a restart."""
        if isinstance(value, (bytes, bytearray, memoryview)):
            raise RuntimeError(
                f"live_ingestion cursor_column '{column}' holds binary data, which "
                f"cannot be persisted and re-bound reliably. Use a timestamp, "
                f"integer or text column."
            )

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

        # A live source's query may carry an unbound ':cursor' placeholder,
        # which would raise StatementError here. Route through the cursor
        # path instead, which binds it. (Without this, the documented
        # live-ingestion config crashes at startup.)
        if self._live.enabled:
            for live_row in self.read_since(cursor=None, limit=count or self._live.batch_size):
                yield live_row.item
            return

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
        """
        Get total number of items, or None when there is no meaningful total.

        Returns None for a live source: an unbounded, still-growing stream has
        no fixed total, and wrapping a ':cursor' query in ``SELECT COUNT(*)``
        would raise on the unbound parameter. This method is reached from
        ``get_status()`` via ``GET /admin/api/data_sources``, i.e. on a
        request thread, so it must not be allowed to raise.
        """
        if self._live.enabled or self._uses_explicit_cursor():
            return None

        if self._total_count is not None:
            return self._total_count

        from sqlalchemy import text

        try:
            engine = self._get_engine()

            if self._query:
                # Wrap query in count (query is admin-provided from YAML config)
                count_query = f"SELECT COUNT(*) FROM ({self._query.rstrip(';')}) AS subquery"
            else:
                # Validate table name to prevent SQL injection
                safe_table = self._validate_identifier(self._table)
                count_query = f"SELECT COUNT(*) FROM {safe_table}"

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
        status["live_ingestion_enabled"] = bool(self._live.enabled)
        return status

    def close(self) -> None:
        """Close the database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
        self._total_count = None
        self._live_columns = None
