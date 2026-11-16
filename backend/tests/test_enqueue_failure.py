from fastapi.testclient import TestClient

from conftest import CSRF, PW, SEED_DIR, _login, seed_org
from phoebe.api.app import Deps, create_app
from phoebe.auth import hash_password
from phoebe.config import Settings
from phoebe.embed import HashEmbedder
from phoebe.jobs import JobUnavailable
from phoebe.limits import InMemoryCounterStore
from phoebe.sessions import InMemorySessionStore
from phoebe.storage import LocalBlobStore

QUEUE_DOWN = {"detail": "queue_unavailable"}


class DownQueue:
    def enqueue(self, document_id: str) -> None:
        raise JobUnavailable


class RecordingQueue:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def enqueue(self, document_id: str) -> None:
        self.ids.append(document_id)


def make(db, tmp_path, jobs):
    seed_org(db)
    blobs = LocalBlobStore(tmp_path / "blobs")
    counters = InMemoryCounterStore()
    settings = Settings(
        database_url="postgresql://unused",
        password_hash=hash_password(PW),
        cookie_secure=False,
        blob_dir=tmp_path / "blobs",
        seed_dir=SEED_DIR,
        uploads_per_session_day=2,
    )
    deps = Deps(
        db,
        InMemorySessionStore(),
        blobs,
        HashEmbedder(),
        jobs,
        settings,
        counters=counters,
    )
    c = _login(TestClient(create_app(deps)))
    return c, blobs, counters


def upload(c):
    return c.post(
        "/api/documents/upload",
        files={"file": ("a.md", b"# hi\n\ntext")},
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


def blob_files(tmp_path):
    return [p for p in (tmp_path / "blobs").rglob("*") if p.is_file()]


def test_upload_with_failing_queue_is_503_and_leaves_nothing(db, tmp_path):
    c, _, _ = make(db, tmp_path, DownQueue())
    r = upload(c)
    assert (r.status_code, r.json()) == (503, QUEUE_DOWN)
    assert c.get("/api/documents?scope=all").json() == []
    assert blob_files(tmp_path) == []
    rows = db.fetch("select count(*) n from documents where session_id is not null")
    assert rows[0]["n"] == 0  # no sandbox slot stays consumed


def test_link_with_failing_queue_is_503_and_leaves_nothing(db, tmp_path):
    c, _, _ = make(db, tmp_path, DownQueue())
    r = link(c)
    assert (r.status_code, r.json()) == (503, QUEUE_DOWN)
    assert c.get("/api/documents?scope=all").json() == []


def test_failed_enqueue_still_consumes_the_upload_counter(db, tmp_path):
    # Existing behaviour on any failure after the charge: the hit stays counted.
    c, _, _ = make(db, tmp_path, DownQueue())
    assert upload(c).status_code == 503
    assert upload(c).status_code == 503
    r = upload(c)
    assert (r.status_code, r.json()) == (429, {"detail": "session_upload_limit"})


def test_working_queue_is_enqueued_before_the_response(db, tmp_path):
    q = RecordingQueue()
    c, _, _ = make(db, tmp_path, q)
    r = upload(c)
    assert r.status_code == 202
    assert q.ids == [r.json()["id"]]
