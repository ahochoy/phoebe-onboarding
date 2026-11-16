"""Hourly sweep: expired sandboxes and stuck indexing jobs.

Skipped without touching the database unless the last activity has made a
stale-document or sandbox-expiry deadline due that no completed sweep has
covered yet (ruling R25), so a paused Aurora stays paused while idle.

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
from phoebe.lambdas.timings import STALE_PROCESSING, SWEEP_INTERVAL
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


def sweep_due(store: ActivityStore, now: datetime) -> bool:
    """Ruling R25: is there DB work that the last completed sweep did not cover?

    The last activity (any authenticated request) arms two deadlines: a
    document can first go stale at `activity + STALE_PROCESSING`, and the
    newest sandbox can first expire by `activity + ABSOLUTE_TIMEOUT` (plus one
    sweep interval of slack for the throttled activity write). A deadline is
    due once it has passed and the last completed sweep started before it.
    Missing or unreadable values sweep (fail toward correctness).
    """
    try:
        last_activity = store.read(ACTIVITY_KEY)
        last_started = store.read(SWEEP_KEY)
    except Exception as exc:  # noqa: BLE001 - fail toward correctness
        log.warning("activity read failed error=%s", type(exc).__name__)
        return True
    if last_activity is None or last_started is None:
        return True
    t = now.timestamp()
    stale_due = last_activity + STALE_PROCESSING.total_seconds()
    expiry_due = last_activity + (ABSOLUTE_TIMEOUT + SWEEP_INTERVAL).total_seconds()
    return (t >= stale_due and last_started < stale_due) or (
        t >= expiry_due and last_started < expiry_due
    )


def _now() -> datetime:
    return datetime.now(UTC)


def handler(event: Any, context: Any) -> dict[str, int | bool]:
    d = runtime.deps()
    store = d.activity.store
    started = _now()
    if not sweep_due(store, started):
        log.info("sweep skipped idle")
        return {"skipped": True}
    report = sweep(d.db, d.blobs, started)
    try:
        # Only after success, and the start time: rows the sweep's cutoffs
        # missed are still covered by a deadline later than this.
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
