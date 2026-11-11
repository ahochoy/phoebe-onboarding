import logging
from datetime import date

from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from conftest import CSRF, PW, make_task, seed_org
from phoebe.api.app import Deps
from phoebe.api.security import require_csrf, require_session
from phoebe.db import Database
from phoebe.sessions import sandbox_id


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


def test_login_while_logged_in_wipes_old_session(
    db: Database, logged_in: TestClient
) -> None:
    task_id, key = _own_stuff(db, logged_in)
    old = logged_in.cookies["phoebe_session"]
    assert (
        logged_in.post("/api/login", json={"password": PW}, headers=CSRF).status_code
        == 204
    )
    assert deps_of(logged_in).sessions.get(old) is None
    assert _task_count(db, task_id) == 0
    try:
        deps_of(logged_in).blobs.get(key)
        raise AssertionError("blob should be deleted")
    except KeyError:
        pass


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


def _all_calls(dependant) -> list:
    out = []
    for d in dependant.dependencies:
        out.append(d.call)
        out.extend(_all_calls(d))
    return out


def test_every_state_changing_route_is_guarded(client: TestClient) -> None:
    contexts = list(iter_route_contexts(client.app.routes))  # type: ignore[attr-defined]
    assert contexts
    for c in contexts:
        if not isinstance(c.route, APIRoute):
            # Mounts, WebSockets and plain Starlette routes bypass the dependency
            # check, so they are only allowed when they are GET/HEAD-only.
            methods = c.methods
            assert methods is not None and methods <= {"GET", "HEAD"}, c.path
            continue
        unsafe = (c.methods or set()) - {"GET", "HEAD", "OPTIONS"}
        if not unsafe:
            continue
        assert (c.path or "").startswith("/api/"), c.path
        calls = _all_calls(c.route.dependant)
        assert require_csrf in calls, c.path
        if c.path != "/api/login":
            assert require_session in calls, c.path


def test_reset_requires_session(client: TestClient) -> None:
    assert client.post("/api/reset", headers=CSRF).status_code == 401


def _own_stuff(db: Database, c: TestClient) -> tuple[str, str]:
    sid = sandbox_id(c.cookies["phoebe_session"])
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


def test_login_429_when_scrypt_slots_exhausted(client: TestClient, monkeypatch) -> None:
    import threading

    from phoebe.api import routes_auth

    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    monkeypatch.setattr(routes_auth, "_scrypt_slots", sem)

    def boom(*_a, **_k):
        raise AssertionError("scrypt must not run")

    monkeypatch.setattr(routes_auth, "verify_password", boom)
    r = client.post("/api/login", json={"password": PW}, headers=CSRF)
    assert r.status_code == 429 and r.json() == {"detail": "too_many_attempts"}


def test_scrypt_slot_released_after_attempt(client: TestClient) -> None:
    for _ in range(6):
        r = client.post("/api/login", json={"password": "nope"}, headers=CSRF)
        assert r.status_code == 401


def test_no_cors_headers_on_preflight(client: TestClient) -> None:
    r = client.options(
        "/api/reset",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-phoebe-csrf",
        },
    )
    assert not [h for h in r.headers if h.lower().startswith("access-control-")]


def test_non_code_http_exception_detail_not_leaked(client: TestClient, caplog) -> None:
    from fastapi import HTTPException

    @client.app.get("/api/leaky")  # type: ignore[attr-defined]
    def leaky() -> None:
        raise HTTPException(400, "bad doc: secret doc text")

    with caplog.at_level(logging.DEBUG):
        r = client.get("/api/leaky")
    assert r.status_code == 500 and r.json() == {"detail": "internal_error"}
    assert "secret doc text" not in r.text + caplog.text
    assert "/api/leaky" in caplog.text


def test_run_guarded_swallows_and_logs_type_only(caplog) -> None:
    from phoebe.api.background import run_guarded

    def job(_doc: str) -> None:
        raise ValueError("secret doc text")

    with caplog.at_level(logging.DEBUG):
        run_guarded(job, "d1", request_id="rid123")
    assert "ValueError" in caplog.text and "rid123" in caplog.text
    assert "secret doc text" not in caplog.text
    for rec in caplog.records:
        assert rec.exc_info is None and "secret doc text" not in rec.getMessage()


def _sandbox_rows(db: Database, sid: str) -> list[dict]:
    return db.fetch(
        "select created_at, last_seen from sandboxes where id = :id", {"id": sid}
    )


def test_sandbox_row_created_on_first_authenticated_request(
    db: Database, logged_in: TestClient
) -> None:
    sid = sandbox_id(logged_in.cookies["phoebe_session"])
    assert _sandbox_rows(db, sid) == []
    assert logged_in.get("/api/groups").status_code == 200
    assert len(_sandbox_rows(db, sid)) == 1


def test_sandbox_row_not_rewritten_within_a_minute(
    db: Database, logged_in: TestClient
) -> None:
    sid = sandbox_id(logged_in.cookies["phoebe_session"])
    logged_in.get("/api/groups")
    first = _sandbox_rows(db, sid)[0]["last_seen"]
    logged_in.get("/api/groups")
    assert _sandbox_rows(db, sid)[0]["last_seen"] == first
    db.execute(
        "update sandboxes set last_seen = now() - interval '2 minutes' where id = :id",
        {"id": sid},
    )
    stale = _sandbox_rows(db, sid)[0]["last_seen"]
    logged_in.get("/api/groups")
    assert _sandbox_rows(db, sid)[0]["last_seen"] > stale


def test_reset_keeps_and_logout_removes_sandbox_row(
    db: Database, logged_in: TestClient
) -> None:
    sid = sandbox_id(logged_in.cookies["phoebe_session"])
    logged_in.get("/api/groups")
    assert logged_in.post("/api/reset", headers=CSRF).status_code == 204
    assert len(_sandbox_rows(db, sid)) == 1
    assert logged_in.post("/api/logout", headers=CSRF).status_code == 204
    assert _sandbox_rows(db, sid) == []


def test_wipe_sandbox_logs_blob_delete_errors_by_type(
    db: Database, logged_in: TestClient, caplog
) -> None:
    _, key = _own_stuff(db, logged_in)

    class Broken:
        def delete(self, k):
            raise OSError(f"disk on fire at {k}")

    deps_of(logged_in).blobs = Broken()  # type: ignore[assignment]
    with caplog.at_level(logging.ERROR, logger="phoebe.api"):
        assert logged_in.post("/api/reset", headers=CSRF).status_code == 204
    assert "blob delete failed OSError" in caplog.text
    assert key not in caplog.text and "disk on fire" not in caplog.text
