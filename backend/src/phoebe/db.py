import json
import re
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_NAMED_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def to_pyformat(sql: str) -> str:
    """Convert `:name` placeholders to `%(name)s`, leaving `::type` casts alone."""
    return _NAMED_PARAM.sub(r"%(\1)s", sql.replace("%", "%%"))


def json_column(value: Any) -> Any:
    """A jsonb value as Python. psycopg returns it parsed; the Data API's JSON
    format returns it as a JSON string. Use as a pydantic before-validator or on
    raw rows so both backends read the same."""
    return json.loads(value) if isinstance(value, str | bytes) else value


def utc_datetime(value: Any) -> Any:
    """A timestamptz as an aware UTC datetime. The Data API returns it as
    "YYYY-MM-DD HH:MM:SS.ffffff" in UTC with no offset."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class DatabaseUnavailable(Exception):
    """The store cannot serve the request right now (resuming, unreachable).

    The API maps it to `503 database_unavailable`. Carries no SQL or parameters.
    """


class Database(Protocol):
    def fetch(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int: ...

    def transaction(self) -> AbstractContextManager[Database]: ...


def wake_database(db: Database) -> bool:
    """Nudge the store awake without waiting: True if it answered, False if it is
    still resuming. A backend that can pause (the Data API) declares `wake()`;
    any other backend is always awake, so a trivial query is enough."""
    wake = getattr(db, "wake", None)
    if callable(wake):
        return bool(wake())
    db.fetch("select 1")
    return True


class ClosableDatabase(Database, Protocol):
    def close(self) -> None: ...


type _Conn = psycopg.Connection[dict[str, Any]]


def _fetch(
    conn: _Conn, sql: str, params: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        # `params or {}`: psycopg only unescapes `%%` when params is not None.
        cur.execute(to_pyformat(sql).encode(), params or {})
        return cur.fetchall() if cur.description else []


def _execute(conn: _Conn, sql: str, params: Mapping[str, Any] | None) -> int:
    with conn.cursor() as cur:
        cur.execute(to_pyformat(sql).encode(), params or {})
        return cur.rowcount


class _Transaction:
    """Database bound to one connection inside an open transaction."""

    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def fetch(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return _fetch(self._conn, sql, params)

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        return _execute(self._conn, sql, params)

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        # Nested conn.transaction() becomes a savepoint.
        with self._conn.transaction():
            yield self


class PsycopgDatabase:
    """Pooled database: each call borrows a connection in autocommit mode;
    `transaction()` holds one dedicated connection for its whole block."""

    def __init__(self, url: str, *, max_size: int = 10) -> None:
        self._pool = ConnectionPool[_Conn](
            url,
            min_size=1,
            max_size=max_size,
            kwargs={"autocommit": True, "row_factory": dict_row},
            # Replace connections lost to a DB restart (typeshed check typing is TupleRow-only).
            check=ConnectionPool.check_connection,  # pyright: ignore[reportArgumentType]
            open=True,
        )
        self._pool.wait()

    def fetch(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            return _fetch(conn, sql, params)

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        with self._pool.connection() as conn:
            return _execute(conn, sql, params)

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        # conn.transaction() commits on clean exit and rolls back on exception.
        with self._pool.connection() as conn, conn.transaction():
            yield _Transaction(conn)

    def close(self) -> None:
        self._pool.close()
