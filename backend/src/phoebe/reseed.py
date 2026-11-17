"""Clear every visitor's sandbox data, ahead of a hand-run seed reload.

Visitor rows can reference seed groups, tasks and people by foreign key, so a
seed reload only succeeds once they are gone. Reuses `reset_session` /
`forget_sandbox` (as the sweeper does) so there is one definition of what a
sandbox owns. Logs counts and exception types only.
"""

import logging

from phoebe.db import Database
from phoebe.sandbox import forget_sandbox, reset_session
from phoebe.storage import BlobStore, BlobUnavailable

log = logging.getLogger(__name__)

# Tables that carry a visitor `session_id` (seed rows are null; the seed's
# task_completions use '').
_SESSION_TABLES = (
    "chat_turns",
    "task_completions",
    "overrides",
    "tasks",
    "documents",
    "groups",
)


def _visitor_ids(db: Database) -> list[str]:
    parts = ["select id as sid from sandboxes"] + [
        f"select session_id as sid from {t}" for t in _SESSION_TABLES
    ]
    rows = db.fetch(
        "select distinct sid from ("
        + " union ".join(parts)
        + ") v where sid is not null and sid <> '' order by sid"
    )
    return [r["sid"] for r in rows]


def clear_visitors(db: Database, blobs: BlobStore) -> int:
    """Delete every visitor's rows and uploaded blobs; return how many ids."""
    ids = _visitor_ids(db)
    deleted_blobs = 0
    for sid in ids:
        for key in reset_session(db, sid):
            try:
                blobs.delete(key)
                deleted_blobs += 1
            except (BlobUnavailable, ValueError) as exc:
                log.warning("blob delete failed error=%s", type(exc).__name__)
        forget_sandbox(db, sid)
    log.info("reseed cleared visitors=%d blobs=%d", len(ids), deleted_blobs)
    return len(ids)
