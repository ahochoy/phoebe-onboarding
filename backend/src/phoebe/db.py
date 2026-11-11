import re
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

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


class PsycopgDatabase:
    """Database backed by one psycopg connection; autocommit outside `transaction()`."""

    def __init__(self, url: str) -> None:
        self._conn = psycopg.Connection[dict[str, Any]].connect(
            url, autocommit=True, row_factory=dict_row
        )

    def fetch(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(to_pyformat(sql).encode(), params or {})
            return cur.fetchall() if cur.description else []

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        with self._conn.cursor() as cur:
            cur.execute(to_pyformat(sql).encode(), params or {})
            return cur.rowcount

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        # conn.transaction() commits on clean exit and rolls back on exception.
        with self._conn.transaction():
            yield self

    def close(self) -> None:
        self._conn.close()
