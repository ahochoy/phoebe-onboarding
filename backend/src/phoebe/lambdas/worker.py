"""SQS indexing worker.

Transient errors go back to SQS via `batchItemFailures` and leave the document
`processing`; the DLQ handler marks it failed once retries run out. Logs carry
message and document ids only, never bodies or exception messages.
"""

import logging
from typing import Any

from phoebe.db import DatabaseUnavailable
from phoebe.embed import EmbeddingUnavailable
from phoebe.ingest.pipeline import index_document
from phoebe.lambdas import runtime
from phoebe.lambdas.records import document_id, message_id
from phoebe.storage import BlobUnavailable

log = logging.getLogger(__name__)

_TRANSIENT = (EmbeddingUnavailable, BlobUnavailable, DatabaseUnavailable)


def handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    d = runtime.deps()
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        mid = message_id(record)
        doc_id = document_id(record)
        if doc_id is None:
            log.warning("skipped message=%s reason=malformed", mid)
            continue
        try:
            index_document(
                d.db,
                d.blobs,
                d.embedder,
                doc_id,
                seed_root=d.settings.seed_dir,
                max_chunks=d.settings.max_chunks_per_document,
                retry_transient=True,
            )
        except _TRANSIENT as exc:
            log.warning(
                "retry message=%s document=%s error=%s",
                mid,
                doc_id,
                type(exc).__name__,
            )
            failures.append({"itemIdentifier": mid})
        except Exception as exc:  # noqa: BLE001 - already marked failed; don't loop
            log.error(
                "indexing error message=%s document=%s error=%s",
                mid,
                doc_id,
                type(exc).__name__,
            )
    return {"batchItemFailures": failures}
