"""Rate counters for chat, uploads and login attempts.

Counters share the DynamoDB state table with sessions and the kill switch. A
logical key such as `chat#<sandbox>` gets `#<window>` appended by the store.
"""

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from botocore.exceptions import BotoCoreError, ClientError

from phoebe.config import ControlSettings, Settings

EXPIRY_GRACE_SECONDS = 3600


class LimitsUnavailable(Exception):
    """A limits or control store could not answer. Callers fail closed."""


class CounterStore(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Count one event. False, without incrementing, if already at limit."""
        ...

    def peek(self, key: str, window_seconds: int) -> int: ...


def _window(now: float, window_seconds: int) -> int:
    return int(now // window_seconds)


class InMemoryCounterStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def _key(self, key: str, window_seconds: int) -> str:
        return f"{key}#{_window(self._clock(), window_seconds)}"

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        k = self._key(key, window_seconds)
        with self._lock:
            n = self._counts.get(k, 0)
            if n >= limit:
                return False
            self._counts[k] = n + 1
            return True

    def peek(self, key: str, window_seconds: int) -> int:
        with self._lock:
            return self._counts.get(self._key(key, window_seconds), 0)


class DynamoDBCounterStore:
    def __init__(
        self,
        table: str,
        client: Any = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client("dynamodb")
        self._client = client
        self._table = table
        self._clock = clock

    def _pk(self, key: str, window: int) -> dict[str, Any]:
        return {"pk": {"S": f"counter#{key}#{window}"}}

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        window = _window(self._clock(), window_seconds)
        expires = (window + 1) * window_seconds + EXPIRY_GRACE_SECONDS
        try:
            self._client.update_item(
                TableName=self._table,
                Key=self._pk(key, window),
                UpdateExpression="SET expires_at = :ea ADD n :one",
                ConditionExpression="attribute_not_exists(n) OR n < :limit",
                ExpressionAttributeValues={
                    ":one": {"N": "1"},
                    ":limit": {"N": str(limit)},
                    ":ea": {"N": str(expires)},
                },
            )
        except self._client.exceptions.ConditionalCheckFailedException:
            return False
        except ClientError, BotoCoreError:
            raise LimitsUnavailable from None
        return True

    def peek(self, key: str, window_seconds: int) -> int:
        window = _window(self._clock(), window_seconds)
        try:
            resp = self._client.get_item(
                TableName=self._table,
                Key=self._pk(key, window),
                ConsistentRead=True,
            )
        except ClientError, BotoCoreError:
            raise LimitsUnavailable from None
        item = resp.get("Item")
        if item is None:
            return 0
        try:
            return int(item["n"]["N"])
        except KeyError, ValueError:
            raise LimitsUnavailable from None


def state_table(settings: Settings | ControlSettings) -> str:
    table = settings.state_table or settings.sessions_table
    if not table:
        raise RuntimeError("PHOEBE_STATE_TABLE (or PHOEBE_SESSIONS_TABLE) is required")
    return table


def make_counters(settings: Settings) -> CounterStore:
    if settings.limits_backend == "dynamodb":
        return DynamoDBCounterStore(state_table(settings))
    return InMemoryCounterStore()
