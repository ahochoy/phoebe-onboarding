import json
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest

from conftest import MIGRATIONS_DIR, SEED_DIR, seed_org
from phoebe.api.app import Deps
from phoebe.config import Settings
from phoebe.db import Database, DatabaseUnavailable
from phoebe.embed import HashEmbedder
from phoebe.jobs import InlineJobQueue
from phoebe.lambdas import dlq, ops, runtime, worker
from phoebe.sessions import InMemorySessionStore
from phoebe.storage import BlobUnavailable, LocalBlobStore


def _sqs(*bodies: str) -> dict[str, Any]:
    return {
        "Records": [
            {"messageId": f"m{i}", "body": body} for i, body in enumerate(bodies)
        ]
    }


def _body(doc_id: str) -> str:
    return json.dumps({"document_id": doc_id})


@pytest.fixture
def deps(db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Deps:
    settings = Settings(
        database_url="postgresql://unused", seed_dir=SEED_DIR, blob_dir=tmp_path
    )
    d = Deps(
        db,
        InMemorySessionStore(),
        LocalBlobStore(tmp_path / "blobs"),
        HashEmbedder(),
        InlineJobQueue(lambda _: None),
        settings,
    )
    monkeypatch.setattr(runtime, "deps", lambda: d)
    return d


def _processing_doc(db: Database, sid: str = "s" * 64) -> str:
    if not db.fetch("select 1 from groups where id = 'platform'"):
        seed_org(db)
    return db.fetch(
        """
        insert into documents (session_id, title, doc_type, group_id, source_uri)
        values (:sid, 'T', 'markdown', 'platform', 'blob://x') returning id::text as id
        """,
        {"sid": sid},
    )[0]["id"]


def test_worker_reports_only_retryable_failures(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake(db, blobs, embedder, doc_id, **kw):
        calls.append((doc_id, kw["retry_transient"]))
        if doc_id == "bad":
            raise BlobUnavailable

    monkeypatch.setattr(worker, "index_document", fake)
    out = worker.handler(_sqs(_body("good"), _body("bad")), None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert calls == [("good", True), ("bad", True)]


def test_worker_embedding_unavailable_is_retried(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    from phoebe.embed import EmbeddingUnavailable

    def fake(*a, **kw):
        raise EmbeddingUnavailable

    monkeypatch.setattr(worker, "index_document", fake)
    assert worker.handler(_sqs(_body("x")), None) == {
        "batchItemFailures": [{"itemIdentifier": "m0"}]
    }


def test_worker_leaves_document_processing_on_transient_error(
    deps: Deps, db: Database
) -> None:
    doc = _processing_doc(db)

    class Flaky:
        def get(self, key: str) -> bytes:
            raise BlobUnavailable

    deps.blobs = Flaky()  # type: ignore[assignment]
    db.execute(
        "update documents set source_uri = :u where id = :i::uuid",
        {"u": f"blob://uploads/{'s' * 64}/f", "i": doc},
    )
    out = worker.handler(_sqs(_body(doc)), None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "m0"}]}
    status = db.fetch("select status from documents where id = :i::uuid", {"i": doc})
    assert status[0]["status"] == "processing"


def test_worker_marks_permanent_errors_failed(deps: Deps, db: Database) -> None:
    doc = _processing_doc(db)  # blob key outside the session prefix? missing blob
    db.execute(
        "update documents set source_uri = :u where id = :i::uuid",
        {"u": f"blob://uploads/{'s' * 64}/missing", "i": doc},
    )
    assert worker.handler(_sqs(_body(doc)), None) == {"batchItemFailures": []}
    row = db.fetch(
        "select status, failure_reason from documents where id = :i::uuid",
        {"i": doc},
    )[0]
    assert row["status"] == "failed"
    assert row["failure_reason"] == "Source file missing"


def test_worker_acks_deleted_document_and_logs_skipped(
    deps: Deps, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        out = worker.handler(_sqs(_body(str(uuid.uuid4()))), None)
    assert out == {"batchItemFailures": []}
    assert "skipped" in caplog.text


def test_worker_acks_malformed_body_without_logging_it(
    deps: Deps, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        out = worker.handler(_sqs("SECRET-BODY-TEXT"), None)
    assert out == {"batchItemFailures": []}
    assert "SECRET" not in caplog.text
    assert "skipped" in caplog.text


def test_worker_does_not_log_bodies(
    deps: Deps, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake(*a, **kw):
        raise DatabaseUnavailable("SECRET-MESSAGE")

    monkeypatch.setattr(worker, "index_document", fake)
    body = json.dumps({"document_id": "d1", "note": "SECRET-BODY-TEXT"})
    with caplog.at_level(logging.DEBUG):
        worker.handler(_sqs(body), None)
    assert "SECRET" not in caplog.text


def test_dlq_marks_failed_with_exact_reason(deps: Deps, db: Database) -> None:
    doc = _processing_doc(db)
    assert dlq.handler(_sqs(_body(doc)), None) == {"batchItemFailures": []}
    row = db.fetch(
        "select status, failure_reason from documents where id = :i::uuid",
        {"i": doc},
    )[0]
    assert row == {"status": "failed", "failure_reason": "Indexing timed out"}


def test_dlq_leaves_indexed_document_alone(deps: Deps, db: Database) -> None:
    doc = _processing_doc(db)
    db.execute(
        "update documents set status = 'indexed' where id = :i::uuid", {"i": doc}
    )
    dlq.handler(_sqs(_body(doc), _body(str(uuid.uuid4())), "junk"), None)
    row = db.fetch("select status from documents where id = :i::uuid", {"i": doc})
    assert row[0]["status"] == "indexed"


def test_ops_migrate_applies_migrations(
    deps: Deps, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.execute("drop schema public cascade")
    db.execute("create schema public")
    monkeypatch.setattr(ops, "MIGRATIONS_DIR", MIGRATIONS_DIR)
    out = ops.handler({"task": "migrate"}, None)
    assert out["applied"]
    assert ops.handler({"task": "migrate"}, None) == {"applied": []}
    assert ops.handler({"task": "status"}, None)["migrations"] == len(out["applied"])


def test_ops_seed_if_empty_seeds_then_noops(deps: Deps, db: Database) -> None:
    out = ops.handler({"task": "seed_if_empty"}, None)
    assert out["seeded"] is True
    assert out["groups"] > 0
    groups = db.fetch("select count(*) n from groups")[0]["n"]
    # Visitor data must survive a second call (never wipes).
    db.execute(
        "insert into documents (session_id, title, doc_type, group_id, source_uri) "
        "values ('v', 'Mine', 'markdown', 'platform', 'blob://x')"
    )
    assert ops.handler({"task": "seed_if_empty"}, None) == {"seeded": False}
    assert db.fetch("select count(*) n from groups")[0]["n"] == groups
    assert (
        db.fetch("select count(*) n from documents where session_id = 'v'")[0]["n"] == 1
    )
    assert ops.handler({"task": "status"}, None)["seed_groups"] == groups


def _seed_counts(db: Database) -> dict[str, int]:
    return {
        t: db.fetch(f"select count(*) n from {t}")[0]["n"]
        for t in ("groups", "people", "tasks", "documents", "chunks")
    }


def test_reseed_clears_visitors_then_reloads(deps: Deps, db: Database) -> None:
    ops.handler({"task": "seed_if_empty"}, None)
    fresh = _seed_counts(db)
    sid = "v" * 64
    db.execute("insert into sandboxes (id) values (:sid)", {"sid": sid})
    key = f"uploads/{sid}/a.md"
    deps.blobs.put(key, b"# hi")
    db.execute(
        "insert into groups (id, name, kind, parent_id, session_id) "
        "values ('mine', 'Mine', 'team', 'platform', :sid)",
        {"sid": sid},
    )
    db.execute(
        "insert into documents (session_id, title, doc_type, group_id, source_uri) "
        "values (:sid, 'Mine', 'markdown', 'mine', :uri)",
        {"sid": sid, "uri": f"blob://{key}"},
    )
    task = db.fetch("select id::text as id from tasks where session_id is null")[0][
        "id"
    ]
    db.execute(
        "insert into task_completions (person_id, task_id, session_id, done) "
        "select id, :tid::uuid, :sid, true from people limit 1",
        {"tid": task, "sid": sid},
    )
    db.execute(
        "insert into chat_turns (session_id, role, text) values (:sid, 'user', 'q')",
        {"sid": sid},
    )
    out = ops.handler({"task": "reseed"}, None)
    assert out["reseeded"] is True and out["visitors_cleared"] == 1
    for t in (
        "chat_turns",
        "task_completions",
        "overrides",
        "tasks",
        "documents",
        "groups",
    ):
        n = db.fetch(
            f"select count(*) n from {t} where session_id = :sid", {"sid": sid}
        )
        assert n[0]["n"] == 0, t
    assert db.fetch("select count(*) n from sandboxes")[0]["n"] == 0
    with pytest.raises(KeyError):
        deps.blobs.get(key)
    assert _seed_counts(db) == fresh
    assert out["groups"] == fresh["groups"]


def test_reseed_clears_orphan_visitor_rows(deps: Deps, db: Database) -> None:
    ops.handler({"task": "seed_if_empty"}, None)
    db.execute(
        "insert into overrides (session_id, entity_kind, entity_id, hidden) "
        "values ('orphan', 'group', 'platform', true)"
    )
    out = ops.handler({"task": "reseed"}, None)
    assert out["visitors_cleared"] == 1
    assert db.fetch("select count(*) n from overrides")[0]["n"] == 0


def test_deploy_never_calls_reseed() -> None:
    deploy = Path(__file__).resolve().parents[2] / "ci" / "deploy.sh"
    assert "reseed" not in deploy.read_text(encoding="utf-8")


@pytest.mark.parametrize("event", [{"task": "drop"}, {}, {"task": 3}, "x", None])
def test_ops_rejects_unknown_task(deps: Deps, event: Any) -> None:
    assert ops.handler(event, None) == {"error": "unknown_task"}


def test_inline_queue_keeps_marking_failed_on_transient_errors(
    db: Database, tmp_path: Path
) -> None:
    from phoebe.ingest.pipeline import index_document

    doc = _processing_doc(db)
    db.execute(
        "update documents set source_uri = :u where id = :i::uuid",
        {"u": f"blob://uploads/{'s' * 64}/f", "i": doc},
    )

    class Flaky:
        def get(self, key: str) -> bytes:
            raise BlobUnavailable

    with pytest.raises(BlobUnavailable):
        index_document(db, Flaky(), HashEmbedder(), doc)  # type: ignore[arg-type]
    row = db.fetch("select status from documents where id = :i::uuid", {"i": doc})
    assert row[0]["status"] == "failed"


def test_budget_handler_importable_from_both_paths() -> None:
    from phoebe import budget_handler
    from phoebe.lambdas import budget

    assert budget_handler.handler is budget.handler
