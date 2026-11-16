"""`Database` over the RDS Data API (Aurora Serverless v2, no VPC needed).

The Data API takes `:name` placeholders and `::type` casts natively, so SQL is
sent unchanged. Logs carry operation names and counts only: never SQL, parameter
values or result text.
"""

import copy
import json
import logging
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from phoebe.db import Database, DatabaseUnavailable

_log = logging.getLogger("phoebe.db")

__all__ = ["DataApiDatabase", "DatabaseUnavailable", "encode_params"]

# Error codes on the rds-data client (all arrive as `ClientError`).
_RESUMING = "DatabaseResumingException"
_STATEMENT_TIMEOUT = "StatementTimeoutException"
_OUTAGE = frozenset(
    {
        "DatabaseUnavailableException",
        "ServiceUnavailableError",
        "InternalServerErrorException",
    }
)

# The Data API caps each result row at 64 KB (and a response at 1 MB); text
# columns are read in slices this long: at most 60 KB even at 4 bytes/char.
TEXT_SLICE_CHARS = 15_000

_FIRST_DELAY_S = 0.5
_MAX_DELAY_S = 8.0
_MAX_TIMEOUT_RETRIES = 2

_WRITE_WORD = re.compile(
    r"\b(insert|update|delete|merge|truncate|alter|create|drop|call|do|copy)\b"
)


# ---- parameters -----------------------------------------------------------


def _array_element(item: Any) -> str:
    if item is None:
        return "NULL"
    if isinstance(item, bool):
        return "true" if item else "false"
    if isinstance(item, int | float | Decimal):
        return str(item)
    if isinstance(item, UUID):
        return f'"{item}"'
    if isinstance(item, str):
        return '"' + item.replace("\\", "\\\\").replace('"', '\\"') + '"'
    raise TypeError(f"unsupported array element {type(item).__name__}")


def _is_scalar(item: Any) -> bool:
    return item is None or isinstance(item, str | int | float | bool | Decimal | UUID)


def _encode_value(value: Any) -> tuple[dict[str, Any], str | None]:
    """The Data API `Field` for `value`, and its optional `typeHint`."""
    if value is None:
        return {"isNull": True}, None
    if isinstance(value, Enum):
        return _encode_value(value.value)
    if isinstance(value, bool):  # before int: bool is an int subclass
        return {"booleanValue": value}, None
    if isinstance(value, int):
        return {"longValue": value}, None
    if isinstance(value, float):
        return {"doubleValue": value}, None
    if isinstance(value, str):
        return {"stringValue": str(value)}, None
    if isinstance(value, UUID):
        return {"stringValue": str(value)}, "UUID"
    if isinstance(value, datetime):  # before date: datetime is a date subclass
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return {"stringValue": value.strftime("%Y-%m-%d %H:%M:%S.%f")}, "TIMESTAMP"
    if isinstance(value, date):
        return {"stringValue": value.isoformat()}, "DATE"
    if isinstance(value, Decimal):
        return {"stringValue": str(value)}, "DECIMAL"
    if isinstance(value, Mapping):
        return {"stringValue": json.dumps(value)}, None
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        if all(_is_scalar(i) for i in value):
            # Postgres array literal, for `:x::text[]`-style casts in the SQL.
            return {
                "stringValue": "{" + ",".join(map(_array_element, value)) + "}"
            }, None
        return {"stringValue": json.dumps(value)}, None  # JSON array
    raise TypeError(f"unsupported parameter type {type(value).__name__}")


def encode_params(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """`:name` parameters as Data API `SqlParameter` dicts."""
    out: list[dict[str, Any]] = []
    for name, value in params.items():
        field, hint = _encode_value(value)
        param: dict[str, Any] = {"name": name, "value": field}
        if hint is not None:
            param["typeHint"] = hint
        out.append(param)
    return out


# ---- results --------------------------------------------------------------


def _decode_rows(resp: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = resp.get("formattedRecords")
    # No type sniffing: jsonb/date/timestamp/decimal arrive as JSON strings and
    # are decoded where the column is read (see `db.json_column`).
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


def _is_read_only(sql: str) -> bool:
    """Conservative: a statement that might write is never retried after a timeout."""
    s = sql.lstrip().lower()
    return s.startswith(("select", "with")) and not _WRITE_WORD.search(s)


# ---- adapter --------------------------------------------------------------


class DataApiDatabase(Database):
    """Each call is one Data API request; `transaction()` holds a transaction id.

    Transient states are handled here: a resuming cluster is retried with backoff
    for up to `resume_timeout_s`, then `DatabaseUnavailable`. Nothing inside a
    transaction is retried.
    """

    text_slice_chars = TEXT_SLICE_CHARS

    def __init__(
        self,
        cluster_arn: str,
        secret_arn: str,
        database: str,
        *,
        client: Any = None,
        resume_timeout_s: float = 40.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client if client is not None else boto3.client("rds-data")
        self._target: dict[str, Any] = {
            "resourceArn": cluster_arn,
            "secretArn": secret_arn,
            "database": database,
        }
        self._resume_timeout_s = resume_timeout_s
        self._sleep = sleep
        self._tx_id: str | None = None

    def _invoke(self, op: str, *, retry_timeouts: bool = False, **kwargs: Any) -> Any:
        method = getattr(self._client, op)
        delay, waited, timeouts = _FIRST_DELAY_S, 0.0, 0
        while True:
            try:
                return method(**kwargs)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code == _RESUMING:
                    # Not executed, so safe to resend; but never mid-transaction.
                    if (
                        self._tx_id is not None
                        or waited + delay > self._resume_timeout_s
                    ):
                        _log.warning(
                            "database still resuming op=%s waited=%.1fs", op, waited
                        )
                        raise DatabaseUnavailable("database is resuming") from None
                    _log.info("database resuming op=%s retry_in=%.1fs", op, delay)
                    self._sleep(delay)
                    waited += delay
                    delay = min(delay * 2, _MAX_DELAY_S)
                elif (
                    code == _STATEMENT_TIMEOUT
                    and retry_timeouts
                    and self._tx_id is None
                    and timeouts < _MAX_TIMEOUT_RETRIES
                ):
                    timeouts += 1
                    _log.info("statement timeout op=%s retry=%d", op, timeouts)
                elif code in _OUTAGE:
                    _log.warning("database unavailable op=%s code=%s", op, code)
                    raise DatabaseUnavailable(code) from None
                else:
                    raise
            except BotoCoreError as exc:
                _log.warning("database unreachable op=%s %s", op, type(exc).__name__)
                raise DatabaseUnavailable(type(exc).__name__) from None

    def _statement(
        self, sql: str, params: Mapping[str, Any] | None, **extra: Any
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {**self._target, "sql": sql, **extra}
        if params:
            kwargs["parameters"] = encode_params(params)
        if self._tx_id is not None:
            kwargs["transactionId"] = self._tx_id
        return self._invoke(
            "execute_statement", retry_timeouts=_is_read_only(sql), **kwargs
        )

    def wake(self) -> bool:
        """One `select 1` that never waits: True if the cluster answered, False
        if it is resuming. Calling a paused cluster is what starts the resume."""
        try:
            self._client.execute_statement(**self._target, sql="select 1")
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code == _RESUMING:
                _log.info("database resuming op=wake")
                return False
            if code in _OUTAGE:
                _log.warning("database unavailable op=wake code=%s", code)
                raise DatabaseUnavailable(code) from None
            raise
        except BotoCoreError as exc:
            _log.warning("database unreachable op=wake %s", type(exc).__name__)
            raise DatabaseUnavailable(type(exc).__name__) from None
        return True

    def fetch(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        resp = self._statement(sql, params, formatRecordsAs="JSON")
        return _decode_rows(resp)

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        resp = self._statement(sql, params)
        return int(resp.get("numberOfRecordsUpdated", 0))

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        if self._tx_id is not None:
            # No savepoints in the Data API: a nested block joins the outer one.
            yield self
            return
        begin = self._invoke("begin_transaction", **self._target)
        tx = copy.copy(self)
        tx._tx_id = begin["transactionId"]
        ids = {
            "resourceArn": self._target["resourceArn"],
            "secretArn": self._target["secretArn"],
            "transactionId": tx._tx_id,
        }
        try:
            yield tx
        except BaseException:
            try:
                tx._invoke("rollback_transaction", **ids)
            except Exception as exc:  # noqa: BLE001 - never mask the original error
                _log.warning("rollback failed %s", type(exc).__name__)
            raise
        tx._invoke("commit_transaction", **ids)

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
