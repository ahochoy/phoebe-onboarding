"""Dead-letter handler: a job that exhausted its retries is marked failed."""

import logging
from typing import Any

from phoebe.db import DatabaseUnavailable
from phoebe.lambdas import runtime
from phoebe.lambdas.records import document_id, message_id
from phoebe.sandbox import is_uuid

log = logging.getLogger(__name__)

REASON = "Indexing timed out"


def handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    d = runtime.deps()
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        mid = message_id(record)
        doc_id = document_id(record)
        if doc_id is None or not is_uuid(doc_id):
            log.warning("skipped message=%s reason=malformed", mid)
            continue
        try:
            # One atomic statement: never overwrites an indexed/failed document.
            changed = d.db.execute(
                """
                update documents set status = 'failed', failure_reason = :r
                where id = :id::uuid and status = 'processing'
                """,
                {"r": REASON, "id": doc_id},
            )
            if changed:
                log.info("dead-lettered document=%s", doc_id)
            else:
                log.info("skipped message=%s reason=not_processing", mid)
        except DatabaseUnavailable:
            log.warning("retry message=%s document=%s", mid, doc_id)
            failures.append({"itemIdentifier": mid})
    return {"batchItemFailures": failures}
