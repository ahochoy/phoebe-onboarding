"""Idle tracking (R20): the API records activity, the sweeper skips when idle."""

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


def test_one_visit_wakes_the_database_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # R25: stale deadline T+60m, expiry deadline T+24h+1h.
    store, sdb = _armed(monkeypatch, tmp_path)
    timeline = [
        (timedelta(minutes=30), False),
        (timedelta(minutes=61), True),  # stale_due passed
        (timedelta(hours=2), False),
        (timedelta(hours=25), True),  # expiry_due passed
        (timedelta(hours=26), False),
        (timedelta(hours=60), False),
    ]
    for offset, swept in timeline:
        _at(monkeypatch, T + offset)
        before = sdb.sweeps
        out = sweeper.handler({}, None)
        assert (sdb.sweeps > before) is swept, offset
        assert ("skipped" not in out) is swept, offset
        if swept:
            assert store.read(SWEEP_KEY) == int((T + offset).timestamp())


def test_new_activity_re_arms_both_deadlines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, sdb = _armed(monkeypatch, tmp_path)
    for offset in (timedelta(minutes=61), timedelta(hours=25)):
        _at(monkeypatch, T + offset)
        sweeper.handler({}, None)
    assert sdb.sweeps == 2
    t2 = T + timedelta(hours=30)
    store.write(ACTIVITY_KEY, int(t2.timestamp()))
    expected = [
        (timedelta(minutes=30), 2),
        (timedelta(minutes=61), 3),
        (timedelta(hours=3), 3),
        (timedelta(hours=25), 4),
        (timedelta(hours=26), 4),
    ]
    for offset, sweeps in expected:
        _at(monkeypatch, t2 + offset)
        sweeper.handler({}, None)
        assert sdb.sweeps == sweeps, offset


def test_idle_skip_makes_no_db_call_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = CountingStore()
    store.write(ACTIVITY_KEY, int(T.timestamp()))
    store.write(SWEEP_KEY, int((T + timedelta(hours=25)).timestamp()))
    store.writes.clear()
    nodb = NoDb()
    _sweeper_deps(monkeypatch, tmp_path, nodb, store)
    _at(monkeypatch, T + timedelta(days=10))
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
