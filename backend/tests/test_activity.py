"""Idle tracking: the API records activity, the sweeper skips when idle."""

import itertools
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from conftest import CSRF, PW
from phoebe.activity import (
    ACTIVITY_KEY,
    SWEEP_KEY,
    ActivityRecorder,
    DynamoDBActivityStore,
    InMemoryActivityStore,
)
from phoebe.api.app import Deps, build_deps
from phoebe.config import Settings
from phoebe.db import DatabaseUnavailable
from phoebe.embed import HashEmbedder
from phoebe.jobs import InlineJobQueue
from phoebe.lambdas import ops, runtime, sweeper
from phoebe.limits import LimitsUnavailable
from phoebe.meta import EmbedderMismatch
from phoebe.sessions import InMemorySessionStore
from phoebe.storage import LocalBlobStore


class Clock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class CountingStore(InMemoryActivityStore):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[str, int]] = []

    def write(self, key: str, epoch: int) -> None:
        self.writes.append((key, epoch))
        super().write(key, epoch)


class BrokenStore:
    def read(self, key: str) -> int | None:
        raise LimitsUnavailable

    def write(self, key: str, epoch: int) -> None:
        raise LimitsUnavailable


# ---- recorder ----------------------------------------------------------------


def test_recorder_writes_at_most_once_per_minute() -> None:
    store, clock = CountingStore(), Clock()
    rec = ActivityRecorder(store, clock=clock)
    rec.touch()
    clock.t += 30
    rec.touch()
    assert store.writes == [(ACTIVITY_KEY, 1_000_000)]
    clock.t += 31
    rec.touch()
    assert store.writes[-1] == (ACTIVITY_KEY, 1_000_061)
    assert len(store.writes) == 2


def test_recorder_failure_is_logged_by_type_and_never_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rec = ActivityRecorder(BrokenStore(), clock=Clock())
    with caplog.at_level(logging.WARNING, logger="phoebe.activity"):
        rec.touch()
        rec.touch()  # throttled: no second attempt
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs == ["activity write failed error=LimitsUnavailable"]


# ---- DynamoDB store ----------------------------------------------------------


class FakeDynamo:
    def __init__(self, fail: bool = False) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.fail = fail

    def _maybe_fail(self, op: str) -> None:
        if self.fail:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, op)

    def get_item(self, **kw: Any) -> dict[str, Any]:
        self._maybe_fail("GetItem")
        assert kw["ConsistentRead"] is True
        item = self.items.get(kw["Key"]["pk"]["S"])
        return {"Item": item} if item else {}

    def put_item(self, **kw: Any) -> dict[str, Any]:
        self._maybe_fail("PutItem")
        self.items[kw["Item"]["pk"]["S"]] = kw["Item"]
        return {}


def test_dynamodb_store_round_trips_and_fails_as_unavailable() -> None:
    fake = FakeDynamo()
    store = DynamoDBActivityStore("state", client=fake)
    assert store.read(ACTIVITY_KEY) is None
    store.write(ACTIVITY_KEY, 42)
    assert fake.items[ACTIVITY_KEY] == {"pk": {"S": ACTIVITY_KEY}, "at": {"N": "42"}}
    assert store.read(ACTIVITY_KEY) == 42
    broken = DynamoDBActivityStore("state", client=FakeDynamo(fail=True))
    with pytest.raises(LimitsUnavailable):
        broken.read(SWEEP_KEY)
    with pytest.raises(LimitsUnavailable):
        broken.write(SWEEP_KEY, 1)


# ---- sweeper -----------------------------------------------------------------


class NoDb:
    """Any database call fails the test: an idle sweep must not wake Aurora."""

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, *_: Any, **__: Any) -> Any:
        self.calls += 1
        raise AssertionError("database touched")

    execute = fetch
    transaction = fetch


def _sweeper_deps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Any, store: Any
) -> Deps:
    d = Deps(
        db,
        InMemorySessionStore(),
        LocalBlobStore(tmp_path / "blobs"),
        HashEmbedder(),
        InlineJobQueue(lambda _: None),
        Settings(database_url="postgresql://unused"),
        activity=ActivityRecorder(store),
    )
    monkeypatch.setattr(runtime, "deps", lambda: d)
    return d


class SweepDb:
    """Counts sweeps: no expired sandboxes, no stale docs. `fail` raises."""

    def __init__(self) -> None:
        self.sweeps = 0
        self.fail = False

    def fetch(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        if self.fail:
            raise DatabaseUnavailable("resuming")
        self.sweeps += 1  # each sweep starts with the expired-sandbox query
        return []

    def execute(self, sql: str, params: Any = None) -> int:
        return 0

    def transaction(self) -> Any:
        raise AssertionError("no transaction without expired sandboxes")


T = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _at(monkeypatch: pytest.MonkeyPatch, when: datetime) -> None:
    monkeypatch.setattr(sweeper, "_now", lambda: when)


def _armed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, SweepDb]:
    """Activity at T; the last completed sweep started well before it."""
    store, sdb = CountingStore(), SweepDb()
    store.write(ACTIVITY_KEY, int(T.timestamp()))
    store.write(SWEEP_KEY, int((T - timedelta(hours=5)).timestamp()))
    _sweeper_deps(monkeypatch, tmp_path, sdb, store)
    return store, sdb


H = timedelta(hours=1)


def _ts(when: datetime) -> int:
    return int(when.timestamp())


def _simulate(
    *,
    activity_at: list[datetime],
    start: datetime,
    hours: int,
    last_started: datetime | None,
) -> list[datetime]:
    """Evaluate the pure rule hourly; each run records its own start time."""
    runs: list[datetime] = []
    for h in range(hours + 1):
        now = start + h * H
        seen = [a for a in activity_at if a <= now]
        last_activity = _ts(max(seen)) if seen else None
        started = _ts(last_started) if last_started else None
        if sweeper.should_sweep(now, last_activity, started):
            runs.append(now)
            last_started = now
    return runs


def test_continuous_activity_sweeps_every_hour() -> None:
    # Activity every 30 min for 48 h must not postpone the sweep.
    activity = [T + timedelta(minutes=30 * i) for i in range(97)]
    start = T + H
    runs = _simulate(
        activity_at=activity, start=start, hours=47, last_started=T - 2 * H
    )
    assert runs == [start + h * H for h in range(48)]


def test_single_activity_sweeps_hourly_until_26h_then_stops() -> None:
    runs = _simulate(activity_at=[T], start=T + H, hours=60, last_started=T - 2 * H)
    # Last run T+26h (the sweep started at T+25h still covers activity T);
    # first skip T+27h. Afterwards only the hard cap (>24 h) sweeps: T+51h.
    assert runs == [T + h * H for h in range(1, 27)] + [T + 51 * H]
    assert T + 27 * H not in runs


def test_idle_for_days_sweeps_only_on_the_hard_cap() -> None:
    long_ago = T - timedelta(days=30)
    runs = _simulate(
        activity_at=[long_ago], start=T, hours=24 * 5, last_started=T - 2 * H
    )
    # One sweep per >24 h: hourly evaluation first exceeds the cap 25 h after
    # each run (the initial last_started is T-2h).
    assert runs == [T + h * H for h in (23, 48, 73, 98)]
    assert all(b - a > timedelta(hours=24) for a, b in itertools.pairwise(runs))


@pytest.mark.parametrize(
    ("activity", "started"),
    [(None, 1_000_000), (1_000_000, None), (None, None)],
)
def test_should_sweep_when_a_value_is_missing(
    activity: int | None, started: int | None
) -> None:
    assert sweeper.should_sweep(T, activity, started) is True


def test_should_sweep_boundaries() -> None:
    activity = _ts(T - 3 * H)
    # Under one interval since the last sweep: skip.
    assert not sweeper.should_sweep(T + timedelta(minutes=59), activity, _ts(T))
    assert sweeper.should_sweep(T + H, activity, _ts(T))
    # A last_started in the future (bad clock or value) sweeps.
    assert sweeper.should_sweep(T, activity, _ts(T + timedelta(seconds=1)))
    # Activity exactly at last_started - 25h still counts, one second older not.
    edge = _ts(T - 25 * H)
    assert sweeper.should_sweep(T + H, edge, _ts(T))
    assert not sweeper.should_sweep(T + H, edge - 1, _ts(T))
    # Hard cap is strictly greater than 24 h.
    assert not sweeper.should_sweep(T + 24 * H, edge - 1, _ts(T))
    assert sweeper.should_sweep(T + 24 * H + timedelta(seconds=1), edge - 1, _ts(T))


def test_handler_sweeps_hourly_while_active_and_marks_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, sdb = _armed(monkeypatch, tmp_path)
    for i in range(1, 5):
        now = T + i * H
        store.write(ACTIVITY_KEY, _ts(now - timedelta(minutes=10)))  # still active
        _at(monkeypatch, now)
        out = sweeper.handler({}, None)
        assert "skipped" not in out
        assert store.read(SWEEP_KEY) == _ts(now)
    assert sdb.sweeps == 4


def test_idle_skip_makes_no_db_call_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = CountingStore()
    store.write(ACTIVITY_KEY, int(T.timestamp()))
    store.write(SWEEP_KEY, int((T + timedelta(hours=27)).timestamp()))
    store.writes.clear()
    nodb = NoDb()
    _sweeper_deps(monkeypatch, tmp_path, nodb, store)
    _at(monkeypatch, T + timedelta(hours=27, minutes=30))
    assert sweeper.handler({}, None) == {"skipped": True}
    assert nodb.calls == 0
    assert store.writes == []


@pytest.mark.parametrize("missing", [ACTIVITY_KEY, SWEEP_KEY])
def test_missing_values_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    store, sdb = CountingStore(), SweepDb()
    present = SWEEP_KEY if missing == ACTIVITY_KEY else ACTIVITY_KEY
    store.write(present, int(T.timestamp()))
    _sweeper_deps(monkeypatch, tmp_path, sdb, store)
    _at(monkeypatch, T + timedelta(minutes=1))
    assert "sandboxes" in sweeper.handler({}, None)
    assert sdb.sweeps == 1


def test_a_failed_sweep_does_not_advance_last_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, sdb = _armed(monkeypatch, tmp_path)
    before = store.read(SWEEP_KEY)
    sdb.fail = True
    _at(monkeypatch, T + timedelta(minutes=61))
    with pytest.raises(DatabaseUnavailable):
        sweeper.handler({}, None)
    assert store.read(SWEEP_KEY) == before
    sdb.fail = False
    assert "sandboxes" in sweeper.handler({}, None)  # still due: retried
    assert store.read(SWEEP_KEY) == int((T + timedelta(minutes=61)).timestamp())


def test_real_sweep_runs_against_postgres_when_due(
    db: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = CountingStore()
    _sweeper_deps(monkeypatch, tmp_path, db, store)
    out = sweeper.handler({}, None)
    assert out == {"sandboxes": 0, "chunks": 0, "blobs": 0, "stale_docs": 0}
    assert [k for k, _ in store.writes] == [SWEEP_KEY]


def test_unreadable_state_table_sweeps_anyway(
    db: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _sweeper_deps(monkeypatch, tmp_path, db, BrokenStore())
    with caplog.at_level(logging.WARNING, logger="phoebe.lambdas.sweeper"):
        out = sweeper.handler({}, None)
    assert out["sandboxes"] == 0  # the DB sweep ran
    msgs = [r.getMessage() for r in caplog.records]
    assert "activity read failed error=LimitsUnavailable" in msgs
    assert "sweep mark failed error=LimitsUnavailable" in msgs


def test_lambda_deps_never_check_the_embedder(tmp_path: Path) -> None:
    # sweeper/dlq/worker build deps this way: no DB call at cold start.
    nodb = NoDb()
    d = build_deps(
        Settings(database_url="postgresql://unused", blob_dir=tmp_path),
        nodb,  # type: ignore[arg-type]
    )
    assert d.db is nodb
    assert nodb.calls == 0


def test_ops_seed_if_empty_still_checks_the_embedder(
    db: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _sweeper_deps(monkeypatch, tmp_path, db, CountingStore())
    db.execute("insert into app_meta (key, value) values ('embedder', 'titan-v2-1024')")
    with pytest.raises(EmbedderMismatch):
        ops.handler({"task": "seed_if_empty"}, None)


# ---- API ---------------------------------------------------------------------


def test_login_and_sandbox_use_record_activity_throttled(client: TestClient) -> None:
    deps: Deps = client.app.state.deps  # type: ignore[attr-defined]
    store, clock = CountingStore(), Clock()
    deps.activity = ActivityRecorder(store, clock=clock)
    assert (
        client.post("/api/login", json={"password": PW}, headers=CSRF).status_code
        == 204
    )
    assert store.writes == [(ACTIVITY_KEY, 1_000_000)]
    assert (
        client.get("/api/documents?scope=all").status_code == 200
    )  # sandboxed, throttled
    assert len(store.writes) == 1
    clock.t += 61
    assert client.get("/api/documents?scope=all").status_code == 200
    assert store.writes[-1] == (ACTIVITY_KEY, 1_000_061)


def test_failed_password_records_nothing(client: TestClient) -> None:
    deps: Deps = client.app.state.deps  # type: ignore[attr-defined]
    store = CountingStore()
    deps.activity = ActivityRecorder(store)
    r = client.post("/api/login", json={"password": "nope"}, headers=CSRF)
    assert r.status_code == 401
    assert store.writes == []


def test_activity_write_failure_never_fails_login(client: TestClient) -> None:
    deps: Deps = client.app.state.deps  # type: ignore[attr-defined]
    deps.activity = ActivityRecorder(BrokenStore())
    assert (
        client.post("/api/login", json={"password": PW}, headers=CSRF).status_code
        == 204
    )
    assert client.get("/api/documents?scope=all").status_code == 200
