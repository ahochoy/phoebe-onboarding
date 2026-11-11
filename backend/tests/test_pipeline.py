from pathlib import Path
from uuid import uuid4

import pytest

from conftest import seed_org
from phoebe.documents import (
    NewDocument,
    create_document,
    delete_document,
    get_document,
)
from phoebe.embed import HashEmbedder
from phoebe.ingest.fetch import FetchedPage, FetchError, UnsafeUrlError
from phoebe.ingest.pipeline import index_document
from phoebe.storage import LocalBlobStore
from test_parse import make_pdf


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


def new_doc(**kw) -> NewDocument:
    base = {"title": "Doc", "doc_type": "markdown", "group_id": "platform"}
    return NewDocument(**{**base, **kw})


def nofetch(url: str) -> FetchedPage:
    raise AssertionError("network used")


def chunk_count(db, d: str) -> int:
    return db.fetch(
        "select count(*) n from chunks where document_id::text=:d", {"d": d}
    )[0]["n"]


def make_seed(db, doc_type: str, uri: str) -> str:
    return db.fetch(
        """insert into documents (title, doc_type, group_id, source_uri)
           values ('Seed', :t, 'platform', :u) returning id::text as id""",
        {"t": doc_type, "u": uri},
    )[0]["id"]


def test_index_markdown_upload(db, blobs):
    seed_org(db)
    d = create_document(
        db, "s1", new_doc(doc_type="markdown", source_uri="blob://uploads/s1/x")
    )
    blobs.put("uploads/s1/x", b"# Leave\nPTO is 20 days.\n")
    index_document(db, blobs, HashEmbedder(), d)
    doc = get_document(db, "s1", d)
    assert doc is not None and doc.status == "indexed"
    assert doc.full_text and "PTO" in doc.full_text
    assert doc.sections and doc.sections[0]["heading_path"] == ["Leave"]
    rows = db.fetch(
        "select heading_path, vector_dims(embedding) dims from chunks where document_id::text=:d",
        {"d": d},
    )
    assert rows[0]["heading_path"].endswith("Leave") and rows[0]["dims"] == 1024


def test_parse_failure_marks_failed(db, blobs):
    seed_org(db)
    d = create_document(
        db, "s1", new_doc(doc_type="pdf", source_uri="blob://uploads/s1/y")
    )
    blobs.put("uploads/s1/y", make_pdf([""]))
    index_document(db, blobs, HashEmbedder(), d)
    doc = get_document(db, "s1", d)
    assert doc is not None and doc.failure_reason is not None
    assert doc.failure_reason.startswith("No extractable text")


def test_index_missing_document_is_noop(db, blobs):
    index_document(db, blobs, HashEmbedder(), str(uuid4()))


def test_delete_mid_index(db, blobs):
    seed_org(db)
    d = create_document(
        db, "s1", new_doc(doc_type="markdown", source_uri="blob://uploads/s1/z")
    )
    blobs.put("uploads/s1/z", b"# A\ntext\n")

    class DeletingEmbedder(HashEmbedder):
        def embed(self, texts):
            delete_document(db, "s1", d)
            return super().embed(texts)

    index_document(db, blobs, DeletingEmbedder(), d)
    assert chunk_count(db, d) == 0


def test_reindex_replaces_chunks(db, blobs):
    seed_org(db)
    d = create_document(
        db, "s1", new_doc(doc_type="markdown", source_uri="blob://uploads/s1/r")
    )
    blobs.put("uploads/s1/r", b"# One\nalpha beta\n\n# Two\ngamma delta\n")
    index_document(db, blobs, HashEmbedder(), d)
    first = chunk_count(db, d)
    assert first == 2
    ids1 = {
        r["id"]
        for r in db.fetch("select id from chunks where document_id::text=:d", {"d": d})
    }
    index_document(db, blobs, HashEmbedder(), d)
    assert chunk_count(db, d) == first
    ids2 = {
        r["id"]
        for r in db.fetch("select id from chunks where document_id::text=:d", {"d": d})
    }
    assert ids1.isdisjoint(ids2)  # replaced, not appended
    # shrinking content shrinks chunks
    blobs.put("uploads/s1/r", b"# One\nalpha beta\n")
    index_document(db, blobs, HashEmbedder(), d)
    assert chunk_count(db, d) == 1


def test_missing_blob_marks_failed(db, blobs):
    seed_org(db)
    d = create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/gone"))
    index_document(db, blobs, HashEmbedder(), d)
    doc = get_document(db, "s1", d)
    assert doc and doc.failure_reason == "Source file missing"


def test_no_indexable_text(db, blobs):
    seed_org(db)
    d = create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/e"))
    blobs.put("uploads/s1/e", b"   \n\n")
    index_document(db, blobs, HashEmbedder(), d)
    doc = get_document(db, "s1", d)
    assert doc and doc.status == "failed" and doc.failure_reason


def test_blob_for_other_session_rejected(db, blobs):
    seed_org(db)
    d = create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/x"))
    db.execute(
        "update documents set source_uri='blob://uploads/s2/x' where id::text=:d",
        {"d": d},
    )
    blobs.put("uploads/s2/x", b"# secret\nother session")
    index_document(db, blobs, HashEmbedder(), d)
    doc = get_document(db, "s1", d)
    assert doc and doc.failure_reason == "Invalid source"
    assert chunk_count(db, d) == 0


def test_web_html_via_injected_fetch(db, blobs):
    seed_org(db)
    d = create_document(
        db, "s1", new_doc(doc_type="web", source_uri="https://example.com/p")
    )
    calls: list[str] = []

    def fake(url: str) -> FetchedPage:
        calls.append(url)
        return FetchedPage(
            url,
            "text/html",
            "<html><body><h1>Hi</h1><p>web text here</p></body></html>",
        )

    index_document(db, blobs, HashEmbedder(), d, fetch=fake)
    doc = get_document(db, "s1", d)
    assert doc and doc.status == "indexed" and calls == ["https://example.com/p"]


def test_web_plain_content_type(db, blobs):
    seed_org(db)
    d = create_document(
        db, "s1", new_doc(doc_type="web", source_uri="https://example.com/t")
    )
    index_document(
        db,
        blobs,
        HashEmbedder(),
        d,
        fetch=lambda u: FetchedPage(u, "text/plain", "just some plain words"),
    )
    doc = get_document(db, "s1", d)
    assert doc and doc.status == "indexed"


def test_google_doc_uses_export_url(db, blobs):
    seed_org(db)
    src = "https://docs.google.com/document/d/abc123/edit"
    d = create_document(db, "s1", new_doc(doc_type="google_doc", source_uri=src))
    calls: list[str] = []

    def fake(url: str) -> FetchedPage:
        calls.append(url)
        return FetchedPage(url, "text/plain", "exported doc words")

    index_document(db, blobs, HashEmbedder(), d, fetch=fake)
    assert calls and "export" in calls[0] and "abc123" in calls[0]
    doc = get_document(db, "s1", d)
    assert doc and doc.status == "indexed"


@pytest.mark.parametrize(
    "exc", [UnsafeUrlError("Blocked address"), FetchError("Fetch failed")]
)
def test_fetch_errors_mark_failed_with_reason(db, blobs, exc):
    seed_org(db)
    d = create_document(
        db, "s1", new_doc(doc_type="web", source_uri="https://example.com/p")
    )

    def boom(url: str) -> FetchedPage:
        raise exc

    index_document(db, blobs, HashEmbedder(), d, fetch=boom)
    doc = get_document(db, "s1", d)
    assert doc and doc.failure_reason == exc.reason


def test_unexpected_error_marks_failed_and_reraises(db, blobs):
    seed_org(db)
    d = create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/x"))
    blobs.put("uploads/s1/x", b"# A\ntext\n")

    class Broken(HashEmbedder):
        def embed(self, texts):
            raise RuntimeError("secret internal detail")

    with pytest.raises(RuntimeError):
        index_document(db, blobs, Broken(), d)
    doc = get_document(db, "s1", d)
    assert doc and doc.failure_reason == "Indexing error"


def test_embeds_in_batches_of_32(db, blobs):
    seed_org(db)
    d = create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/big"))
    blobs.put(
        "uploads/s1/big",
        "".join(f"# H{i}\nword{i} text\n\n" for i in range(70)).encode(),
    )
    sizes: list[int] = []

    class Spy(HashEmbedder):
        def embed(self, texts):
            sizes.append(len(texts))
            return super().embed(texts)

    index_document(db, blobs, Spy(), d)
    assert sizes == [32, 32, 6] and chunk_count(db, d) == 70


def test_seed_markdown_file(db, blobs, tmp_path):
    seed_org(db)
    root = tmp_path / "seed"
    (root / "content").mkdir(parents=True)
    (root / "content" / "h.md").write_text("# Handbook\nWelcome aboard.\n")
    d = make_seed(db, "markdown", "seed://content/h.md")
    index_document(db, blobs, HashEmbedder(), d, seed_root=root)
    assert get_document(db, "s1", d).status == "indexed"  # type: ignore[union-attr]
    assert chunk_count(db, d) >= 1


def test_seed_web_file_parsed_as_html(db, blobs, tmp_path):
    seed_org(db)
    root = tmp_path / "seed"
    root.mkdir()
    (root / "w.html").write_text(
        "<html><body><h1>Page</h1><p>some words</p></body></html>"
    )
    d = make_seed(db, "web", "seed://w.html")
    index_document(db, blobs, HashEmbedder(), d, fetch=nofetch, seed_root=root)
    rows = db.fetch(
        "select heading_path from chunks where document_id::text=:d", {"d": d}
    )
    assert rows and "<" not in rows[0]["heading_path"]


def test_seed_path_traversal_rejected(db, blobs, tmp_path):
    seed_org(db)
    root = tmp_path / "seed"
    root.mkdir()
    (tmp_path / "secret.md").write_text("# Secret\nleak\n")
    d = make_seed(db, "markdown", "seed://../secret.md")
    index_document(db, blobs, HashEmbedder(), d, seed_root=root)
    row = db.fetch(
        "select status, failure_reason from documents where id::text=:d", {"d": d}
    )[0]
    assert row == {"status": "failed", "failure_reason": "Invalid source"}
    assert chunk_count(db, d) == 0


def test_seed_absolute_path_rejected(db, blobs, tmp_path):
    seed_org(db)
    root = tmp_path / "seed"
    root.mkdir()
    d = make_seed(db, "markdown", "seed:///etc/hosts")
    index_document(db, blobs, HashEmbedder(), d, seed_root=root)
    row = db.fetch("select failure_reason from documents where id::text=:d", {"d": d})[
        0
    ]
    assert row["failure_reason"] == "Invalid source"


def test_seed_source_without_seed_root_rejected(db, blobs):
    seed_org(db)
    d = make_seed(db, "markdown", "seed://x.md")
    index_document(db, blobs, HashEmbedder(), d)
    row = db.fetch("select failure_reason from documents where id::text=:d", {"d": d})[
        0
    ]
    assert row["failure_reason"] == "Invalid source"


def test_owned_row_cannot_use_seed_source(db, blobs, tmp_path):
    seed_org(db)
    root = tmp_path / "seed"
    root.mkdir()
    (root / "h.md").write_text("# Handbook\ncontent\n")
    d = create_document(db, "s1", new_doc(source_uri="seed://h.md"))
    index_document(db, blobs, HashEmbedder(), d, seed_root=root)
    doc = get_document(db, "s1", d)
    assert doc and doc.failure_reason == "Invalid source"
    assert chunk_count(db, d) == 0


def test_seed_missing_file(db, blobs, tmp_path):
    seed_org(db)
    root = tmp_path / "seed"
    root.mkdir()
    d = make_seed(db, "markdown", "seed://nope.md")
    index_document(db, blobs, HashEmbedder(), d, seed_root=root)
    row = db.fetch("select failure_reason from documents where id::text=:d", {"d": d})[
        0
    ]
    assert row["failure_reason"] == "Source file missing"


def test_failure_log_has_no_exception_message(db, blobs, caplog):
    seed_org(db)
    d = create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/x"))
    blobs.put("uploads/s1/x", b"# A\ntext\n")

    class Broken(HashEmbedder):
        def embed(self, texts):
            raise RuntimeError("secret internal detail")

    with caplog.at_level("DEBUG"), pytest.raises(RuntimeError):
        index_document(db, blobs, Broken(), d)
    assert caplog.records
    for rec in caplog.records:
        assert "secret internal detail" not in rec.getMessage()
        assert "secret internal detail" not in (rec.exc_text or "")
        assert rec.exc_info is None


def test_seed_valueerror_is_invalid_source(db, blobs, tmp_path, monkeypatch):
    seed_org(db)
    root = tmp_path / "seed"
    root.mkdir()
    (root / "a.md").write_text("# A\ntext\n")
    d = make_seed(db, "markdown", "seed://a.md")

    def nul(self):
        raise ValueError("embedded null byte")

    monkeypatch.setattr(Path, "read_bytes", nul)
    index_document(db, blobs, HashEmbedder(), d, seed_root=root)
    row = db.fetch("select failure_reason from documents where id::text=:d", {"d": d})[
        0
    ]
    assert row["failure_reason"] == "Invalid source"


def test_blob_store_valueerror_is_invalid_source(db, blobs):
    seed_org(db)
    d = create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/x"))

    class BadStore:
        def put(self, key, data): ...
        def delete(self, key): ...
        def get(self, key):
            raise ValueError("bad key")

    index_document(db, BadStore(), HashEmbedder(), d)
    doc = get_document(db, "s1", d)
    assert doc and doc.failure_reason == "Invalid source"


def test_mark_failed_error_does_not_mask_original(db, blobs, monkeypatch):
    seed_org(db)
    d = create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/x"))
    blobs.put("uploads/s1/x", b"# A\ntext\n")

    class Broken(HashEmbedder):
        def embed(self, texts):
            raise RuntimeError("original")

    def boom(*a, **k):
        raise OSError("db down")

    monkeypatch.setattr("phoebe.ingest.pipeline.mark_failed", boom)
    with pytest.raises(RuntimeError, match="original"):
        index_document(db, blobs, Broken(), d)
