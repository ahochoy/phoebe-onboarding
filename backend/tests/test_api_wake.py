"""POST /api/wake: a signed-in nudge that starts a paused database resuming."""

import pytest
from fastapi.testclient import TestClient

from conftest import CSRF
from phoebe.api import routes_status


def test_wake_needs_a_session(client: TestClient) -> None:
    assert client.post("/api/wake", headers=CSRF).status_code == 401


def test_wake_needs_csrf(logged_in: TestClient) -> None:
    assert logged_in.post("/api/wake").status_code == 403


def test_wake_reports_an_awake_database(logged_in: TestClient) -> None:
    r = logged_in.post("/api/wake", headers=CSRF)
    assert r.status_code == 200
    assert r.json() == {"database": "awake"}


def test_wake_returns_at_once_while_resuming(
    logged_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes_status, "wake_database", lambda db: False)
    r = logged_in.post("/api/wake", headers=CSRF)
    assert r.status_code == 202
    assert r.json() == {"database": "waking"}
