"""Document row -> parsed text -> chunks -> embeddings -> pgvector rows.

Logs carry the document id, chunk count and timings only, never text.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from phoebe.db import Database
from phoebe.documents import mark_failed, mark_indexed
from phoebe.embed import Embedder, vector_literal
from phoebe.ingest.chunk import Chunk, chunk_document, embedding_text
from phoebe.ingest.fetch import (
    FetchedPage,
    FetchError,
    UnsafeUrlError,
    fetch_url,
    google_doc_export_url,
)
from phoebe.ingest.parse import (
    ParsedDocument,
    ParseError,
    parse_csv,
    parse_html,
    parse_markdown,
    parse_pdf,
    parse_plain,
)
from phoebe.sandbox import BLOB_PREFIX, blob_key_for
from phoebe.storage import BlobStore

log = logging.getLogger(__name__)

_BATCH = 32
_SEED = "seed://"


class _Fail(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _read_seed(uri: str, seed_root: Path | None) -> bytes:
    rel = uri.removeprefix(_SEED)
    if seed_root is None or not rel:
        raise _Fail("Invalid source")
    root = seed_root.resolve()
    try:
        path = (root / rel).resolve()
    except ValueError as exc:
        raise _Fail("Invalid source") from exc
    if not path.is_relative_to(root):
        raise _Fail("Invalid source")
    try:
        return path.read_bytes()
    except ValueError as exc:
        raise _Fail("Invalid source") from exc
    except OSError as exc:
        raise _Fail("Source file missing") from exc


def _read_blob(blobs: BlobStore, session_id: str | None, uri: str) -> bytes:
    key = blob_key_for(session_id, uri) if session_id is not None else None
    if key is None:
        raise _Fail("Invalid source")
    try:
        return blobs.get(key)
    except KeyError as exc:
        raise _Fail("Source file missing") from exc
    except ValueError as exc:
        raise _Fail("Invalid source") from exc


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _parse(
    row: dict[str, Any],
    blobs: BlobStore,
    fetch: Callable[[str], FetchedPage],
    seed_root: Path | None,
) -> ParsedDocument:
    doc_type: str = row["doc_type"]
    uri: str = row["source_uri"]
    session_id: str | None = row["session_id"]
    textual = doc_type in ("web", "google_doc")

    if uri.startswith(_SEED):
        if session_id is not None:  # only seed rows may read seed files
            raise _Fail("Invalid source")
        data = _read_seed(uri, seed_root)
    elif uri.startswith(BLOB_PREFIX):
        if textual:
            raise _Fail("Invalid source")
        data = _read_blob(blobs, session_id, uri)
    elif uri.startswith("https://") and textual:
        if doc_type == "google_doc":
            page = fetch(google_doc_export_url(uri) or uri)
            return parse_plain(page.text)
        page = fetch(uri)
        if page.content_type.split(";")[0].strip().lower() == "text/html":
            return parse_html(page.text)
        return parse_plain(page.text)
    else:
        raise _Fail("Invalid source")

    match doc_type:
        case "markdown":
            return parse_markdown(data)
        case "csv":
            return parse_csv(data)
        case "pdf":
            return parse_pdf(data)
        case "web":
            return parse_html(_text(data))
        case "google_doc":
            return parse_plain(_text(data))
        case _:
            raise _Fail("Invalid source")


def _embed_all(embedder: Embedder, chunks: list[Chunk]) -> list[list[float]]:
    texts = [embedding_text(c) for c in chunks]
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        out.extend(embedder.embed(texts[i : i + _BATCH]))
    return out


def _store(
    db: Database,
    document_id: str,
    parsed: ParsedDocument,
    chunks: list[Chunk],
    vectors: list[list[float]],
) -> bool:
    with db.transaction() as tx:
        locked = tx.fetch(
            "select id from documents where id::text = :id for update",
            {"id": document_id},
        )
        if not locked:
            return False
        doc_uuid = locked[0]["id"]
        tx.execute("delete from chunks where document_id = :d", {"d": doc_uuid})
        for chunk, vec in zip(chunks, vectors, strict=True):
            tx.execute(
                """
                insert into chunks
                  (document_id, ordinal, heading_path, text,
                   start_offset, end_offset, embedding)
                values (:d, :ord, :hp, :text, :s, :e, :emb::vector)
                """,
                {
                    "d": doc_uuid,
                    "ord": chunk.ordinal,
                    "hp": chunk.heading_path,
                    "text": chunk.text,
                    "s": chunk.start,
                    "e": chunk.end,
                    "emb": vector_literal(vec),
                },
            )
        sections = [
            {"heading_path": list(s.heading_path), "start": s.start, "end": s.end}
            for s in parsed.sections
        ]
        mark_indexed(tx, document_id, parsed.full_text, sections)
    return True


def index_document(
    db: Database,
    blobs: BlobStore,
    embedder: Embedder,
    document_id: str,
    *,
    fetch: Callable[[str], FetchedPage] = fetch_url,
    seed_root: Path | None = None,
) -> None:
    rows = db.fetch(
        """
        select title, doc_type, source_uri, session_id
        from documents where id::text = :id
        """,
        {"id": document_id},
    )
    if not rows:
        return
    row = rows[0]
    started = time.monotonic()
    try:
        parsed = _parse(row, blobs, fetch, seed_root)
        chunks = chunk_document(parsed, row["title"])
        if not chunks:
            mark_failed(db, document_id, "No indexable text")
            return
        vectors = _embed_all(embedder, chunks)
        if len(vectors) != len(chunks):
            raise RuntimeError("embedder returned wrong number of vectors")
        stored = _store(db, document_id, parsed, chunks, vectors)
    except _Fail as exc:
        mark_failed(db, document_id, exc.reason)
        return
    except (ParseError, UnsafeUrlError, FetchError) as exc:
        mark_failed(db, document_id, exc.reason)
        return
    except Exception as exc:
        # Metadata only: exception messages/tracebacks may carry document text.
        log.error(
            "indexing failed document=%s error=%s", document_id, type(exc).__name__
        )
        try:
            mark_failed(db, document_id, "Indexing error")
        except Exception as mark_exc:  # noqa: BLE001 - must not mask original
            log.error(
                "mark_failed failed document=%s error=%s",
                document_id,
                type(mark_exc).__name__,
            )
        raise
    log.info(
        "indexed document=%s stored=%s chunks=%d ms=%d",
        document_id,
        stored,
        len(chunks),
        int((time.monotonic() - started) * 1000),
    )
