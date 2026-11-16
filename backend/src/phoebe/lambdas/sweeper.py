"""Hourly sweep: expired sandboxes and stuck indexing jobs.

Skipped without touching the database while the site is idle (no activity
since the last completed sweep), so a paused Aurora stays paused.

Reuses `reset_session` / `forget_sandbox` so there is one definition of what a
sandbox owns. Seed rows (session_id is null) are never touched. Logs counts only.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from phoebe.activity import ACTIVITY_KEY, SWEEP_KEY, ActivityStore
from phoebe.db import Database
from phoebe.lambdas import runtime
from phoebe.lambdas.timings import STALE_PROCESSING
from phoebe.sandbox import forget_sandbox, reset_session
from phoebe.sessions import ABSOLUTE_TIMEOUT
from phoebe.storage import BlobStore, BlobUnavailable

log = logging.getLogger(__name__)

TIMED_OUT = "Indexing timed out"


@dataclass(frozen=True)
class SweepReport:
    sandboxes: int
    chunks: int
    blobs: int
    stale_docs: int


def sweep(db: Database, blobs: BlobStore, now: datetime) -> SweepReport:
    expired = db.fetch(
        "select id from sandboxes where last_seen < :cutoff",
        {"cutoff": now - ABSOLUTE_TIMEOUT},
    )
    chunks = deleted_blobs = 0
    for row in expired:
        sid: str = row["id"]
        chunks += db.fetch(
            """
            select count(*) as n from chunks c
            join documents d on d.id = c.document_id where d.session_id = :sid
            """,
            {"sid": sid},
        )[0]["n"]
        for key in reset_session(db, sid):
            try:
                blobs.delete(key)
                deleted_blobs += 1
            except (BlobUnavailable, ValueError) as exc:
                log.warning("blob delete failed error=%s", type(exc).__name__)
        forget_sandbox(db, sid)
    stale = db.execute(
        """
        update documents set status = 'failed', failure_reason = :reason
        where status = 'processing' and session_id is not null
          and created_at < :cutoff
        """,
        {"reason": TIMED_OUT, "cutoff": now - STALE_PROCESSING},
    )
    return SweepReport(len(expired), chunks, deleted_blobs, stale)


def is_idle(store: ActivityStore) -> bool:
    """True when nothing has happened since the last completed sweep, so the DB
    (which may be paused) has no work. An unreadable store is not idle: sweep."""
    try:
        last_activity = store.read(ACTIVITY_KEY)
        last_complete = store.read(SWEEP_KEY)
    except Exception as exc:  # noqa: BLE001 - fail toward correctness
        log.warning("activity read failed error=%s", type(exc).__name__)
        return False
    if last_complete is None:
        return False
    return last_activity is None or last_activity < last_complete


def handler(event: Any, context: Any) -> dict[str, int | bool]:
    d = runtime.deps()
    store = d.activity.store
    if is_idle(store):
        log.info("sweep skipped idle")
        return {"skipped": True}
    started = datetime.now(UTC)
    report = sweep(d.db, d.blobs, started)
    try:
        # The start time: activity during the sweep still triggers the next one.
        store.write(SWEEP_KEY, int(started.timestamp()))
    except Exception as exc:  # noqa: BLE001 - the next run just sweeps again
        log.warning("sweep mark failed error=%s", type(exc).__name__)
    log.info(
        "sweep sandboxes=%d chunks=%d blobs=%d stale_docs=%d",
        report.sandboxes,
        report.chunks,
        report.blobs,
        report.stale_docs,
    )
    return asdict(report)
