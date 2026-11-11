import logging
from datetime import date

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from conftest import CSRF, PW, make_task, seed_org
from phoebe.api.app import Deps
from phoebe.api.routes_auth import router as auth_router
from phoebe.api.security import require_csrf
from phoebe.db import Database


def deps_of(c: TestClient) -> Deps:
    return c.app.state.deps  # type: ignore[attr-defined]


def test_health_needs_no_session(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_login_sets_strict_httponly_cookie(client: TestClient) -> None:
    r = client.post("/api/login", json={"password": PW}, headers=CSRF)
    c = r.headers["set-cookie"]
    assert r.status_code == 204
    assert "phoebe_session=" in c
    assert "HttpOnly" in c and "SameSite=strict" in c
    assert "Max-Age=86400" in c and "Path=/" in c
    assert "Secure" not in c  # cookie_secure=False in tests


def test_login_cookie_secure_when_configured(client: TestClient) -> None:
    deps_of(client).settings.cookie_secure = True
    r = client.post("/api/login", json={"password": PW}, headers=CSRF)
    assert "Secure" in r.headers["set-cookie"]


def test_wrong_password_401(client: TestClient) -> None:
    r = client.post("/api/login", json={"password": "nope"}, headers=CSRF)
    assert r.status_code == 401 and r.json() == {"detail": "invalid_password"}
    assert "set-cookie" not in r.headers


def test_login_requires_csrf_header(client: TestClient) -> None:
    r = client.post("/api/login", json={"password": PW})
    assert r.status_code == 403 and r.json() == {"detail": "csrf_required"}


def test_overlong_password_422_without_scrypt(client: TestClient, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("scrypt must not run")

    monkeypatch.setattr("phoebe.api.routes_auth.verify_password", boom)
    r = client.post("/api/login", json={"password": "x" * 257}, headers=CSRF)
    assert r.status_code == 422 and r.json() == {"detail": "invalid_request"}
    assert "xxxx" not in r.text


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    r = client.post("/api/login", json={"pw": "secret-value"}, headers=CSRF)
    assert r.status_code == 422 and r.json() == {"detail": "invalid_request"}


def test_login_while_logged_in_issues_fresh_session(logged_in: TestClient) -> None:
    old = logged_in.cookies["phoebe_session"]
    r = logged_in.post("/api/login", json={"password": PW}, headers=CSRF)
    assert r.status_code == 204
    assert logged_in.cookies["phoebe_session"] != old


def test_me_requires_session(client: TestClient) -> None:
    r = client.get("/api/me")
    assert r.status_code == 401 and r.json() == {"detail": "session_expired"}


def test_me_with_garbage_cookie_401(client: TestClient) -> None:
    client.cookies.set("phoebe_session", "garbage")
    assert client.get("/api/me").status_code == 401


def test_me_returns_alex(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/me").json()["id"] == "alex-rivera"


def test_me_day_number_from_injected_clock(db: Database, logged_in: TestClient) -> None:
    seed_org(db)  # alex starts 2026-11-02
    deps_of(logged_in).today = lambda: date(2026, 11, 2)
    body = logged_in.get("/api/me").json()
    assert body["day_number"] == 1 and body["team_name"] == "Platform"
    assert body["start_date"] == "2026-11-02"
    deps_of(logged_in).today = lambda: date(2026, 11, 11)
    assert logged_in.get("/api/me").json()["day_number"] == 10


def test_post_without_csrf_header_403(logged_in: TestClient) -> None:
    assert logged_in.post("/api/reset").status_code == 403
    assert logged_in.post("/api/logout").status_code == 403
    assert (
        logged_in.post("/api/reset", headers={"X-Phoebe-Csrf": "0"}).status_code == 403
    )


def test_every_non_get_route_has_csrf_dependency() -> None:
    # Later tasks append their routers here.
    routes = [r for rt in (auth_router,) for r in rt.routes if isinstance(r, APIRoute)]
    assert routes
    for r in routes:
        if (r.methods or set()) - {"GET", "HEAD", "OPTIONS"}:
            calls = [d.call for d in r.dependant.dependencies]
            assert require_csrf in calls, r.path


def test_reset_requires_session(client: TestClient) -> None:
    assert client.post("/api/reset", headers=CSRF).status_code == 401


def _own_stuff(db: Database, c: TestClient) -> tuple[str, str]:
    sid = c.cookies["phoebe_session"]
    seed_org(db)
    task_id = make_task(db, group_id="platform", session_id=sid)
    key = f"uploads/{sid}/f1"
    deps_of(c).blobs.put(key, b"data")
    db.execute(
        """
        insert into documents (session_id, title, doc_type, group_id, source_uri)
        values (:sid, 'mine', 'markdown', 'platform', :uri)
        """,
        {"sid": sid, "uri": f"blob://{key}"},
    )
    return task_id, key


def _task_count(db: Database, task_id: str) -> int:
    return len(db.fetch("select 1 from tasks where id = :i::uuid", {"i": task_id}))


def test_reset_restores_seed(db: Database, logged_in: TestClient) -> None:
    task_id, key = _own_stuff(db, logged_in)
    assert _task_count(db, task_id) == 1
    assert logged_in.post("/api/reset", headers=CSRF).status_code == 204
    assert _task_count(db, task_id) == 0
    try:
        deps_of(logged_in).blobs.get(key)
        raise AssertionError("blob should be deleted")
    except KeyError:
        pass
    assert logged_in.get("/api/me").status_code == 200  # session survives


def test_reset_ignores_missing_blob(db: Database, logged_in: TestClient) -> None:
    _, key = _own_stuff(db, logged_in)
    deps_of(logged_in).blobs.delete(key)

    class Strict:
        def __init__(self, inner):
            self.inner = inner

        def delete(self, k):
            raise KeyError(k)

    deps_of(logged_in).blobs = Strict(deps_of(logged_in).blobs)  # type: ignore[assignment]
    assert logged_in.post("/api/reset", headers=CSRF).status_code == 204


def test_reset_does_not_touch_other_session(
    db: Database, logged_in: TestClient, second_client: TestClient
) -> None:
    other_task, _ = _own_stuff(db, second_client)
    logged_in.post("/api/reset", headers=CSRF)
    assert _task_count(db, other_task) == 1


def test_logout_invalidates(db: Database, logged_in: TestClient) -> None:
    task_id, _ = _own_stuff(db, logged_in)
    sid = logged_in.cookies["phoebe_session"]
    r = logged_in.post("/api/logout", headers=CSRF)
    assert r.status_code == 204
    assert "phoebe_session=" in r.headers["set-cookie"]
    assert "Max-Age=0" in r.headers["set-cookie"]
    assert logged_in.get("/api/me").status_code == 401
    assert deps_of(logged_in).sessions.get(sid) is None
    assert _task_count(db, task_id) == 0


def test_unknown_route_json_404(client: TestClient) -> None:
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"detail": "not_found"}


def test_method_not_allowed_json(client: TestClient) -> None:
    r = client.post("/api/health", headers=CSRF)
    assert r.status_code == 405 and r.json() == {"detail": "method_not_allowed"}


def test_security_headers_and_request_id(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    rid = r.headers["x-request-id"]
    assert len(rid) == 32 and int(rid, 16) >= 0
    assert client.get("/api/health").headers["x-request-id"] != rid


def test_security_headers_on_errors(client: TestClient) -> None:
    r = client.get("/api/me")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert "x-request-id" in r.headers


def test_unhandled_exception_is_500_internal_error(client: TestClient, caplog) -> None:
    @client.app.get("/api/boom")  # type: ignore[attr-defined]
    def boom() -> None:
        raise RuntimeError("secret detail")

    with caplog.at_level(logging.DEBUG):
        r = client.get("/api/boom")
    assert r.status_code == 500 and r.json() == {"detail": "internal_error"}
    assert "x-request-id" in r.headers
    assert "RuntimeError" in caplog.text
    assert "secret detail" not in caplog.text
    assert "Traceback" not in caplog.text


def test_request_log_is_metadata_only(
    db: Database, logged_in: TestClient, caplog
) -> None:
    from phoebe.sessions import session_hash

    seed_org(db)

    sid = logged_in.cookies["phoebe_session"]
    with caplog.at_level(logging.INFO, logger="phoebe.api"):
        logged_in.get("/api/me?token=hunter2")
    text = caplog.text
    assert "GET" in text and "/api/me" in text and "200" in text
    assert session_hash(sid) in text
    assert sid not in text
    assert "hunter2" not in text


def test_request_log_uses_route_template_and_dash_for_anonymous(
    client: TestClient, caplog
) -> None:
    with caplog.at_level(logging.INFO, logger="phoebe.api"):
        client.get("/totally/unknown/path?x=1")
    assert "/totally/unknown/path" not in caplog.text
    assert "x=1" not in caplog.text
    assert " - " in caplog.text or caplog.text.rstrip().endswith("-")
