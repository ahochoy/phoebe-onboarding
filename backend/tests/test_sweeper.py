from datetime import UTC, datetime, timedelta
from pathlib import Path

from conftest import make_task, seed_org
from phoebe.db import Database
from phoebe.embed import HashEmbedder
from phoebe.ingest.pipeline import index_document
from phoebe.lambdas.sweeper import SweepReport, sweep
from phoebe.sandbox import touch_sandbox
from phoebe.storage import LocalBlobStore

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
OLD = "o" * 64
FRESH = "f" * 64


def _count(db: Database, sql: str, sid: str | None = None) -> int:
    params = {"sid": sid} if sid else None
    return db.fetch(sql, params)[0]["n"]


def _sandbox(db: Database, sid: str, last_seen: datetime) -> None:
    touch_sandbox(db, sid)
    db.execute(
        "update sandboxes set last_seen = :ts where id = :sid",
        {"ts": last_seen, "sid": sid},
    )


def _owned_doc(db: Database, blobs: LocalBlobStore, sid: str) -> str:
    key = f"uploads/{sid}/note.md"
    blobs.put(key, b"# Title\n\nSome text about onboarding.\n")
    rows = db.fetch(
        """
        insert into documents (session_id, title, doc_type, group_id, source_uri)
        values (:sid, 'Mine', 'markdown', 'platform', :uri) returning id::text as id
        """,
        {"sid": sid, "uri": f"blob://{key}"},
    )
    index_document(db, blobs, HashEmbedder(), rows[0]["id"])
    return rows[0]["id"]


def _populate(db: Database, blobs: LocalBlobStore, sid: str) -> None:
    _owned_doc(db, blobs, sid)
    db.execute(
        "insert into chat_turns (session_id, role, text) values (:sid, 'user', 'hi')",
        {"sid": sid},
    )
    task = make_task(db, group_id="platform", session_id=sid)
    db.execute(
        "insert into overrides (session_id, entity_kind, entity_id, hidden) "
        "values (:sid, 'task', :t, true)",
        {"sid": sid, "t": task},
    )


def _rows(db: Database, sid: str) -> dict[str, int]:
    tables = {
        "sandboxes": "id",
        "documents": "session_id",
        "chat_turns": "session_id",
        "overrides": "session_id",
        "tasks": "session_id",
    }
    out = {
        t: _count(db, f"select count(*) n from {t} where {col} = :sid", sid)
        for t, col in tables.items()
    }
    out["chunks"] = _count(
        db,
        "select count(*) n from chunks c join documents d on d.id = c.document_id "
        "where d.session_id = :sid",
        sid,
    )
    return out


def test_sweep_removes_old_sandbox_only(db: Database, tmp_path: Path) -> None:
    seed_org(db)
    blobs = LocalBlobStore(tmp_path / "blobs")
    _sandbox(db, OLD, NOW - timedelta(hours=25))
    _sandbox(db, FRESH, NOW - timedelta(hours=1))
    _populate(db, blobs, OLD)
    _populate(db, blobs, FRESH)
    fresh_before = _rows(db, FRESH)
    assert all(v > 0 for v in _rows(db, OLD).values())

    report = sweep(db, blobs, NOW)

    assert all(v == 0 for v in _rows(db, OLD).values())
    assert _rows(db, FRESH) == fresh_before
    assert report.sandboxes == 1
    assert report.blobs == 1
    assert report.chunks > 0
    assert report.stale_docs == 0
    import pytest

    with pytest.raises(KeyError):
        blobs.get(f"uploads/{OLD}/note.md")
    assert blobs.get(f"uploads/{FRESH}/note.md")


def test_sweep_fails_stale_processing_documents(db: Database, tmp_path: Path) -> None:
    seed_org(db)
    blobs = LocalBlobStore(tmp_path / "blobs")
    _sandbox(db, FRESH, NOW - timedelta(minutes=1))
    ids = {}
    for name, age in (("old", 16), ("young", 2)):
        row = db.fetch(
            """
            insert into documents (session_id, title, doc_type, group_id,
                                   source_uri, created_at)
            values (:sid, :t, 'markdown', 'platform', 'blob://x', :ts)
            returning id::text as id
            """,
            {"sid": FRESH, "t": name, "ts": NOW - timedelta(minutes=age)},
        )
        ids[name] = row[0]["id"]

    report = sweep(db, blobs, NOW)

    assert report.stale_docs == 1
    old = db.fetch(
        "select status, failure_reason from documents where id = :i::uuid",
        {"i": ids["old"]},
    )[0]
    assert old == {"status": "failed", "failure_reason": "Indexing timed out"}
    young = db.fetch(
        "select status from documents where id = :i::uuid", {"i": ids["young"]}
    )[0]
    assert young["status"] == "processing"


def test_sweep_never_touches_seed_rows(db: Database, tmp_path: Path) -> None:
    seed_org(db)
    blobs = LocalBlobStore(tmp_path / "blobs")
    db.execute(
        """
        insert into documents (title, doc_type, group_id, source_uri, created_at)
        values ('Seed', 'markdown', 'platform', 'seed://x', :ts)
        """,
        {"ts": NOW - timedelta(days=3)},
    )
    make_task(db, group_id="platform")
    before = (
        _count(db, "select count(*) n from groups"),
        _count(db, "select count(*) n from tasks"),
        _count(db, "select count(*) n from people"),
    )

    report = sweep(db, blobs, NOW)

    assert report == SweepReport(sandboxes=0, chunks=0, blobs=0, stale_docs=0)
    assert before == (
        _count(db, "select count(*) n from groups"),
        _count(db, "select count(*) n from tasks"),
        _count(db, "select count(*) n from people"),
    )
    assert db.fetch("select status from documents")[0]["status"] == "processing"
