import hmac
import logging

import pytest
from fastapi.testclient import TestClient

from conftest import CSRF, PW, SEED_DIR, seed_org
from phoebe.api import origin as origin_mod
from phoebe.api.app import Deps, create_app
from phoebe.auth import hash_password
from phoebe.config import Settings
from phoebe.control import InMemoryControlStore
from phoebe.embed import HashEmbedder
from phoebe.jobs import InlineJobQueue
from phoebe.sessions import InMemorySessionStore
from phoebe.storage import LocalBlobStore

SECRET = "s3cr3t"
HDR = "X-Phoebe-Origin"
FORBIDDEN = {"detail": "forbidden"}


class SpyCounters:
    def __init__(self):
        self.calls = 0

    def hit(self, key, limit, window_seconds):
        self.calls += 1
        return True

    def peek(self, key, window_seconds):
        return 0


class SpyControl(InMemoryControlStore):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def get(self):
        self.calls += 1
        return super().get()


def make(db, tmp_path, secret: str | None = SECRET):
    seed_org(db)
    blobs = LocalBlobStore(tmp_path / "blobs")
    settings = Settings(
        database_url="postgresql://unused",
        password_hash=hash_password(PW),
        cookie_secure=False,
        blob_dir=tmp_path / "blobs",
        seed_dir=SEED_DIR,
        origin_secret=secret,
    )
    counters, control = SpyCounters(), SpyControl()
    deps = Deps(
        db,
        InMemorySessionStore(),
        blobs,
        HashEmbedder(),
        InlineJobQueue(lambda d: None),
        settings,
        counters=counters,
        control=control,
    )
    return TestClient(create_app(deps)), counters, control


@pytest.mark.parametrize("headers", [{}, {HDR: "wrong"}, {HDR: ""}])
def test_missing_or_wrong_header_is_forbidden(db, tmp_path, headers):
    c, counters, control = make(db, tmp_path)
    for r in (
        c.get("/api/me", headers=headers),
        c.post("/api/login", json={"password": PW}, headers={**CSRF, **headers}),
    ):
        assert (r.status_code, r.json()) == (403, FORBIDDEN)
    # Rejected before the throttle, the kill switch or the session store.
    assert counters.calls == 0
    assert control.calls == 0


def test_rejection_logs_one_metadata_line(db, tmp_path, caplog):
    c, _, _ = make(db, tmp_path)
    with caplog.at_level(logging.WARNING, logger="phoebe.api"):
        r = c.get("/api/me?q=private", headers={HDR: "wrong-value-xyz"})
    assert r.status_code == 403
    lines = [
        rec.getMessage() for rec in caplog.records if "origin guard" in rec.getMessage()
    ]
    assert lines == ["origin guard rejected path=/api/me status=403"]
    assert "wrong-value-xyz" not in caplog.text and "private" not in caplog.text


def test_right_header_behaves_normally(db, tmp_path):
    c, counters, _ = make(db, tmp_path)
    h = {HDR: SECRET}
    assert c.get("/api/me", headers=h).status_code == 401
    r = c.post("/api/login", json={"password": PW}, headers={**CSRF, **h})
    assert r.status_code == 204
    assert counters.calls == 1
    assert c.get("/api/me", headers=h).status_code == 200


def test_health_is_always_allowed(db, tmp_path):
    c, _, _ = make(db, tmp_path)
    assert c.get("/api/health").json() == {"status": "ok"}
    assert c.get("/api/health", headers={HDR: "wrong"}).status_code == 200


def test_no_secret_means_no_guard(db, tmp_path):
    c, _, _ = make(db, tmp_path, secret=None)
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/me", headers={HDR: "anything"}).status_code == 401


def test_comparison_uses_compare_digest(db, tmp_path, monkeypatch):
    seen = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(origin_mod.hmac, "compare_digest", spy)
    c, _, _ = make(db, tmp_path)
    c.get("/api/me", headers={HDR: SECRET})
    assert seen
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in seen)


def test_non_ascii_header_does_not_crash(db, tmp_path):
    c, _, _ = make(db, tmp_path)
    r = c.get("/api/me", headers={HDR.encode(): "é".encode("latin-1")})
    assert (r.status_code, r.json()) == (403, FORBIDDEN)


def test_client_ip_header_ignored_without_origin_secret(db, tmp_path):
    from test_api_limits import login, make_client

    c = make_client(db, tmp_path, client_ip_header="cloudfront-viewer-address")
    h = "cloudfront-viewer-address"
    # Different spoofed addresses all share the socket peer's bucket.
    for i in range(3):
        assert login(c, "wrong", {h: f"203.0.113.{i}:443"}).status_code == 401
    assert login(c, "wrong", {h: "198.51.100.9:1"}).status_code == 429
