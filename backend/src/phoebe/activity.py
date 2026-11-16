"""Idle tracking, so the hourly sweeper can leave a sleeping database asleep.

The API records `activity#last` (epoch seconds) on login and on every
authenticated sandbox request (where `touch_sandbox` bumps `last_seen`); the
sweeper records `sweep#last_started` (the start time of its last completed
database sweep) and only touches the database when a deadline armed by the
last activity is due (ruling R25, see `lambdas/sweeper.py`). Both keys live in
the DynamoDB state table, beside sessions, counters and the kill switch. Logs
carry error types only.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from botocore.exceptions import BotoCoreError, ClientError

from phoebe.config import Settings
from phoebe.limits import LimitsUnavailable, state_table

ACTIVITY_KEY = "activity#last"
SWEEP_KEY = "sweep#last_started"
ACTIVITY_INTERVAL_S = 60.0

_log = logging.getLogger(__name__)


class ActivityStore(Protocol):
    def read(self, key: str) -> int | None:
        """Epoch seconds stored under `key`, or None. Raises LimitsUnavailable."""
        ...

    def write(self, key: str, epoch: int) -> None: ...


class InMemoryActivityStore:
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._lock = threading.Lock()

    def read(self, key: str) -> int | None:
        with self._lock:
            return self._values.get(key)

    def write(self, key: str, epoch: int) -> None:
        with self._lock:
            self._values[key] = epoch


class DynamoDBActivityStore:
    def __init__(
        self, table: str, client: Any = None, region: str | None = None
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client("dynamodb", region_name=region)
        self._client = client
        self._table = table

    def read(self, key: str) -> int | None:
        try:
            resp = self._client.get_item(
                TableName=self._table, Key={"pk": {"S": key}}, ConsistentRead=True
            )
        except ClientError, BotoCoreError:
            raise LimitsUnavailable from None
        item = resp.get("Item")
        if item is None:
            return None
        try:
            return int(item["at"]["N"])
        except KeyError, TypeError, ValueError:
            raise LimitsUnavailable from None

    def write(self, key: str, epoch: int) -> None:
        try:
            self._client.put_item(
                TableName=self._table,
                Item={"pk": {"S": key}, "at": {"N": str(int(epoch))}},
            )
        except ClientError, BotoCoreError:
            raise LimitsUnavailable from None


class ActivityRecorder:
    """Writes `activity#last` at most once per `interval_s` per container. A
    failed write is logged (type only) and never fails the caller."""

    def __init__(
        self,
        store: ActivityStore,
        clock: Callable[[], float] = time.time,
        interval_s: float = ACTIVITY_INTERVAL_S,
    ) -> None:
        self.store = store
        self._clock = clock
        self._interval = interval_s
        self._last: float | None = None
        self._lock = threading.Lock()

    def touch(self) -> None:
        now = self._clock()
        with self._lock:
            if self._last is not None and now - self._last < self._interval:
                return
            self._last = now  # also on failure: never retry in a tight loop
        try:
            self.store.write(ACTIVITY_KEY, int(now))
        except Exception as exc:  # noqa: BLE001 - best effort, type only
            _log.warning("activity write failed error=%s", type(exc).__name__)


def make_activity(settings: Settings) -> ActivityRecorder:
    if settings.limits_backend == "dynamodb":
        store: ActivityStore = DynamoDBActivityStore(
            state_table(settings), region=settings.aws_region
        )
    else:
        store = InMemoryActivityStore()
    return ActivityRecorder(store)
