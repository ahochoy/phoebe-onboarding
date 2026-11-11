"""Kill switch: `open`, `chat_paused` (browsing works, AI off) or `closed`."""

import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol, get_args

from botocore.exceptions import BotoCoreError, ClientError

from phoebe.config import ControlSettings, Settings
from phoebe.limits import LimitsUnavailable, state_table

KillState = Literal["open", "chat_paused", "closed"]
STATES: tuple[str, ...] = get_args(KillState)


def _valid(value: object) -> KillState:
    if value not in STATES:
        raise LimitsUnavailable
    return value  # type: ignore[return-value]


class ControlStore(Protocol):
    def get(self) -> KillState: ...

    def set(self, state: KillState) -> None: ...


class FileControlStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def get(self) -> KillState:
        try:
            text = self._path.read_text()
        except FileNotFoundError:
            return "open"
        except OSError:
            raise LimitsUnavailable from None
        try:
            data = json.loads(text)
        except ValueError:
            raise LimitsUnavailable from None
        if not isinstance(data, dict):
            raise LimitsUnavailable
        return _valid(data.get("state"))

    def set(self, state: KillState) -> None:
        _valid(state)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".control-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"state": state}, f)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


class DynamoDBControlStore:
    _KEY: ClassVar[dict[str, Any]] = {"pk": {"S": "control"}}

    def __init__(self, table: str, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("dynamodb")
        self._client = client
        self._table = table

    def get(self) -> KillState:
        try:
            resp = self._client.get_item(
                TableName=self._table, Key=self._KEY, ConsistentRead=True
            )
        except ClientError, BotoCoreError:
            raise LimitsUnavailable from None
        item = resp.get("Item")
        if item is None:
            return "open"
        try:
            return _valid(item["state"]["S"])
        except KeyError, TypeError:
            raise LimitsUnavailable from None

    def set(self, state: KillState) -> None:
        _valid(state)
        try:
            self._client.put_item(
                TableName=self._table,
                Item={**self._KEY, "state": {"S": state}},
            )
        except ClientError, BotoCoreError:
            raise LimitsUnavailable from None


class CachedControlStore:
    """Caches reads. An inner failure fails closed for AI (`chat_paused`) while
    browsing keeps working, and the failure is not cached."""

    def __init__(
        self,
        inner: ControlStore,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._clock = clock
        self._cached: tuple[KillState, float] | None = None

    def get(self) -> KillState:
        now = self._clock()
        if self._cached is not None and now < self._cached[1]:
            return self._cached[0]
        try:
            state = self._inner.get()
        except LimitsUnavailable:
            self._cached = None
            return "chat_paused"
        self._cached = (state, now + self._ttl)
        return state

    def set(self, state: KillState) -> None:
        self._cached = None
        self._inner.set(state)


def make_inner_control(settings: Settings | ControlSettings) -> ControlStore:
    if settings.control_backend == "dynamodb":
        return DynamoDBControlStore(state_table(settings))
    return FileControlStore(settings.control_file)


def make_control(settings: Settings | ControlSettings) -> ControlStore:
    return CachedControlStore(
        make_inner_control(settings), settings.kill_switch_cache_seconds
    )
