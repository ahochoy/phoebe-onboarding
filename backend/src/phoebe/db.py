import re
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_NAMED_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def to_pyformat(sql: str) -> str:
    """Convert `:name` placeholders to `%(name)s`, leaving `::type` casts alone."""
    return _NAMED_PARAM.sub(r"%(\1)s", sql.replace("%", "%%"))


class Database(Protocol):
    def fetch(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int: ...

    def transaction(self) -> AbstractContextManager[Database]: ...


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
