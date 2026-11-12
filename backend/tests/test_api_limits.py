from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import CSRF, PW, SEED_DIR, _login, seed_org
from phoebe.api.app import Deps, create_app
from phoebe.api.limits import client_ip
from phoebe.auth import hash_password
from phoebe.config import Settings
from phoebe.control import InMemoryControlStore
from phoebe.embed import HashEmbedder
from phoebe.ingest.pipeline import index_document
from phoebe.jobs import InlineJobQueue
from phoebe.limits import InMemoryCounterStore, LimitsUnavailable
from phoebe.sessions import InMemorySessionStore, sandbox_id
from phoebe.storage import LocalBlobStore


class DownCounters:
    def hit(self, key, limit, window_seconds):
        raise LimitsUnavailable

    def peek(self, key, window_seconds):
        raise LimitsUnavailable


def make_client(db, tmp_path: Path, *, counters=None, control=None, **over):
    blobs = LocalBlobStore(tmp_path / "blobs")
    embedder = HashEmbedder()
    kw = {
        "database_url": "postgresql://unused",
        "password_hash": hash_password(PW),
        "cookie_secure": False,
        "blob_dir": tmp_path / "blobs",
        "seed_dir": SEED_DIR,
        "login_per_ip_window": 3,
        "uploads_per_session_day": 2,
        "uploads_global_day": 3,
    }
    seed_org(db)  # groups for uploads, persona for /api/tasks
    settings = Settings(**{**kw, **over})
    jobs = InlineJobQueue(
        lambda d: index_document(db, blobs, embedder, d, seed_root=settings.seed_dir)
    )
    deps = Deps(
        db,
        InMemorySessionStore(),
        blobs,
        embedder,
        jobs,
        settings,
        counters=counters or InMemoryCounterStore(),
        control=control or InMemoryControlStore(),
    )
    return TestClient(create_app(deps))


def up(c, n=1):
    return c.post(
        "/api/documents/upload",
        files={"file": (f"a{n}.md", b"# hi\n\ntext")},
        data={"title": "T", "purpose": "p", "group_id": "platform"},
        headers=CSRF,
    )


def link(c):
    return c.post(
        "/api/documents/link",
        json={
            "url": "https://example.com/x",
            "title": "L",
            "purpose": "p",
            "group_id": "platform",
        },
        headers=CSRF,
    )


def login(c, pw=PW, headers=None):
    return c.post(
        "/api/login", json={"password": pw}, headers={**CSRF, **(headers or {})}
    )


def test_login_throttled_per_ip(db, tmp_path, monkeypatch):
    import phoebe.api.routes_auth as ra

    c = make_client(db, tmp_path)
    for _ in range(3):
        assert login(c, "wrong").status_code == 401
    calls = []
    monkeypatch.setattr(ra, "verify_password", lambda *a: calls.append(1) or True)
    r = login(c)
    assert (r.status_code, r.json()) == (429, {"detail": "too_many_attempts"})
    assert calls == []


def test_login_ignores_x_forwarded_for_by_default(db, tmp_path):
    c = make_client(db, tmp_path)
    for i in range(3):
        assert login(c, "wrong", {"X-Forwarded-For": f"1.2.3.{i}"}).status_code == 401
    assert login(c, PW, {"X-Forwarded-For": "9.9.9.9"}).status_code == 429


def test_client_ip_header_used_when_configured(db, tmp_path):
    c = make_client(db, tmp_path, client_ip_header="cloudfront-viewer-address")
    h = "cloudfront-viewer-address"
    for _ in range(3):
        assert login(c, "wrong", {h: "203.0.113.5:443"}).status_code == 401
    assert login(c, "wrong", {h: "203.0.113.5:999"}).status_code == 429
    for _ in range(3):
        assert login(c, "wrong", {h: "[2001:db8::1]:443"}).status_code == 401
    assert login(c, "wrong", {h: "[2001:db8::1]:1"}).status_code == 429
    assert login(c, PW, {h: "198.51.100.1:1"}).status_code == 204


def test_client_ip_parsing_and_fallback():
    from starlette.requests import Request

    def req(headers):
        return Request({"type": "http", "headers": headers, "client": ("10.0.0.1", 1)})

    hdr = [(b"h", b"[2001:db8::1]:443")]
    assert client_ip(req(hdr), "h") == "2001:db8::1"
    assert client_ip(req([(b"h", b"203.0.113.5:443")]), "h") == "203.0.113.5"
    assert client_ip(req([]), "h") == "10.0.0.1"
    assert client_ip(req(hdr), None) == "10.0.0.1"


def test_upload_cap_per_session(db, tmp_path):
    c = make_client(db, tmp_path)
    _login(c)
    assert up(c).status_code == 202
    assert up(c, 2).status_code == 202
    r = up(c, 3)
    assert (r.status_code, r.json()) == (429, {"detail": "session_upload_limit"})


def test_link_counts_toward_upload_cap(db, tmp_path):
    c = make_client(db, tmp_path)
    _login(c)
    assert up(c).status_code == 202
    assert link(c).status_code == 202
    assert link(c).json() == {"detail": "session_upload_limit"}
    assert up(c, 2).status_code == 429


def test_global_upload_cap_across_sessions(db, tmp_path):
    c = make_client(db, tmp_path, uploads_per_session_day=5)
    _login(c)
    for i in range(2):
        assert up(c, i).status_code == 202
    c.cookies.clear()
    _login(c)
    assert up(c, 3).status_code == 202
    r = up(c, 4)
    assert (r.status_code, r.json()) == (429, {"detail": "global_upload_limit"})


def test_upload_rejected_when_chat_paused(db, tmp_path):
    counters = InMemoryCounterStore()
    c = make_client(
        db, tmp_path, counters=counters, control=InMemoryControlStore("chat_paused")
    )
    _login(c)
    sb = sandbox_id(c.cookies["phoebe_session"])

    def owned() -> int:
        return db.fetch(
            "select count(*) as n from documents where session_id = :s", {"s": sb}
        )[0]["n"]

    r = up(c)
    assert (r.status_code, r.json()) == (503, {"detail": "chat_paused"})
    assert owned() == 0
    assert counters.peek(f"upload#{sb}", 86400) == 0
    assert counters.peek("upload#global", 86400) == 0
    assert link(c).status_code == 503
    assert owned() == 0
    assert counters.peek(f"upload#{sb}", 86400) == 0
    assert counters.peek("upload#global", 86400) == 0


def search(c):
    return c.post("/api/search", json={"query": "onboarding"}, headers=CSRF)


def test_search_rejected_when_paused(db, tmp_path):
    counters = InMemoryCounterStore()
    c = make_client(
        db, tmp_path, counters=counters, control=InMemoryControlStore("chat_paused")
    )
    _login(c)
    r = search(c)
    assert (r.status_code, r.json()) == (503, {"detail": "chat_paused"})
    assert counters.peek("chat#global", 86400) == 0


def test_search_counts_against_chat_cap(db, tmp_path):
    c = make_client(db, tmp_path, chat_per_session_hour=2)
    _login(c)
    assert search(c).status_code == 200
    assert search(c).status_code == 200
    r = search(c)
    assert (r.status_code, r.json()) == (429, {"detail": "session_chat_limit"})


def test_client_ip_garbage_header_falls_back():
    from starlette.requests import Request

    r = Request(
        {
            "type": "http",
            "headers": [(b"h", b"not-an-ip:80")],
            "client": ("10.0.0.1", 1),
        }
    )
    assert client_ip(r, "h") == "10.0.0.1"


def test_status_reports_chat_limits_when_seeded(db, tmp_path):
    counters = InMemoryCounterStore()
    c = make_client(
        db, tmp_path, counters=counters, chat_per_session_hour=2, chat_global_day=3
    )
    _login(c)
    sb = sandbox_id(c.cookies["phoebe_session"])
    for _ in range(2):
        counters.hit(f"chat#{sb}", 2, 3600)
    s = c.get("/api/status").json()
    assert s["chat_available"] is False and s["reasons"] == ["session_chat_limit"]
    counters.hit("chat#global", 3, 86400)
    c.cookies.clear()
    assert c.get("/api/status").json()["reasons"] == []
    counters.hit("chat#global", 3, 86400)
    counters.hit("chat#global", 3, 86400)
    s = c.get("/api/status").json()
    assert s["chat_available"] is False and s["reasons"] == ["global_chat_limit"]


def test_closed_blocks_api_but_not_status_or_health(db, tmp_path):
    c = make_client(db, tmp_path, control=InMemoryControlStore("closed"))
    r = c.get("/api/tasks")
    assert (r.status_code, r.json()) == (503, {"detail": "demo_closed"})
    assert login(c).status_code == 503
    assert c.get("/api/health").status_code == 200
    s = c.get("/api/status")
    assert s.status_code == 200
    assert s.json()["state"] == "closed"
    assert s.json()["reasons"] == ["demo_closed"]
    assert s.json()["chat_available"] is False


def test_status_reports_limits_without_consuming(db, tmp_path):
    counters = InMemoryCounterStore()
    c = make_client(db, tmp_path, counters=counters)
    _login(c)
    assert up(c).status_code == 202
    before = dict(counters._counts)
    for _ in range(5):
        assert c.get("/api/status").status_code == 200
    assert counters._counts == before
    assert up(c, 2).status_code == 202
    s = c.get("/api/status").json()
    assert s["upload_available"] is False
    assert "session_upload_limit" in s["reasons"]
    assert s["chat_available"] is True
    assert s["state"] == "open"


def test_status_anonymous_has_no_session_reasons(db, tmp_path):
    c = make_client(db, tmp_path)
    _login(c)
    up(c)
    up(c, 2)
    c.cookies.clear()
    s = c.get("/api/status").json()
    assert s == {
        "state": "open",
        "chat_available": True,
        "upload_available": True,
        "reasons": [],
    }


def test_status_paused(db, tmp_path):
    c = make_client(db, tmp_path, control=InMemoryControlStore("chat_paused"))
    s = c.get("/api/status").json()
    assert s["state"] == "chat_paused"
    assert s["reasons"] == ["chat_paused"]
    assert not s["chat_available"] and not s["upload_available"]


def test_limits_store_down_fails_closed(db, tmp_path):
    c = make_client(db, tmp_path, counters=DownCounters())
    r = login(c)
    assert (r.status_code, r.json()) == (503, {"detail": "chat_paused"})
    # browsing keeps working without the limits store
    c2 = c
    deps = c2.app.state.deps  # type: ignore[attr-defined]
    deps.counters = InMemoryCounterStore()
    _login(c2)
    deps.counters = DownCounters()
    r = up(c2)
    assert (r.status_code, r.json()) == (503, {"detail": "chat_paused"})
    assert c2.get("/api/tasks").status_code == 200
    s = c2.get("/api/status").json()
    assert s["reasons"] == ["chat_paused"] and not s["chat_available"]


def test_default_deps_are_offline(db, tmp_path):
    # Deps built without counters/control must not touch the cwd.
    blobs = LocalBlobStore(tmp_path / "b")
    d = Deps(db, InMemorySessionStore(), blobs, HashEmbedder(), None, None)  # type: ignore[arg-type]
    assert d.control.get() == "open"
    assert isinstance(d.counters, InMemoryCounterStore)


@pytest.mark.parametrize("path", ["/api/status"])
def test_status_is_plain_get(db, tmp_path, path):
    c = make_client(db, tmp_path)
    assert c.get(path).status_code == 200
