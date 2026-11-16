"""Idle tracking (R20): the API records activity, the sweeper skips when idle."""

import logging
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


def test_idle_sweeper_makes_no_db_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, nodb = CountingStore(), NoDb()
    store.write(ACTIVITY_KEY, 100)
    store.write(SWEEP_KEY, 200)
    store.writes.clear()
    _sweeper_deps(monkeypatch, tmp_path, nodb, store)
    assert sweeper.handler({}, None) == {"skipped": True}
    assert nodb.calls == 0
    assert store.writes == []


def test_never_any_activity_after_a_sweep_is_idle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, nodb = CountingStore(), NoDb()
    store.write(SWEEP_KEY, 200)
    _sweeper_deps(monkeypatch, tmp_path, nodb, store)
    assert sweeper.handler({}, None) == {"skipped": True}
    assert nodb.calls == 0


def test_activity_after_last_sweep_sweeps_and_marks_complete(
    db: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = CountingStore()
    store.write(SWEEP_KEY, 100)
    store.write(ACTIVITY_KEY, 150)
    store.writes.clear()
    _sweeper_deps(monkeypatch, tmp_path, db, store)
    out = sweeper.handler({}, None)
    assert out == {"sandboxes": 0, "chunks": 0, "blobs": 0, "stale_docs": 0}
    assert [k for k, _ in store.writes] == [SWEEP_KEY]
    assert (store.read(SWEEP_KEY) or 0) > 150
    # Nothing new since: the next run is idle.
    assert sweeper.handler({}, None) == {"skipped": True}


def test_first_sweep_runs_without_a_completion_mark(
    db: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = CountingStore()
    _sweeper_deps(monkeypatch, tmp_path, db, store)
    assert "sandboxes" in sweeper.handler({}, None)
    assert store.read(SWEEP_KEY) is not None


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
