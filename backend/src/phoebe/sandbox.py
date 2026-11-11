import json
import logging
from enum import StrEnum
from typing import Any

from phoebe.db import Database
from phoebe.sessions import session_hash


class EntityKind(StrEnum):
    DOCUMENT = "document"
    TASK = "task"
    GROUP = "group"


def hide(db: Database, session_id: str, kind: EntityKind, entity_id: str) -> None:
    """Hide a seed entity from this session's view."""
    db.execute(
        """
        insert into overrides (session_id, entity_kind, entity_id, hidden)
        values (:sid, :kind, :eid, true)
        on conflict (session_id, entity_kind, entity_id) do update set hidden = true
        """,
        {"sid": session_id, "kind": kind.value, "eid": entity_id},
    )


def patch(
    db: Database,
    session_id: str,
    kind: EntityKind,
    entity_id: str,
    fields: dict[str, Any],
) -> None:
    """Merge `fields` into this session's patch for a seed entity."""
    db.execute(
        """
        insert into overrides (session_id, entity_kind, entity_id, patch)
        values (:sid, :kind, :eid, :fields::jsonb)
        on conflict (session_id, entity_kind, entity_id)
        do update set patch = overrides.patch || :fields::jsonb
        """,
        {
            "sid": session_id,
            "kind": kind.value,
            "eid": entity_id,
            "fields": json.dumps(fields),
        },
    )


_BLOB_PREFIX = "blob://"
_log = logging.getLogger(__name__)


def blob_key_for(session_id: str, source_uri: str) -> str | None:
    """Blob key of a `blob://` URI, only if it lies inside this session's prefix.

    Returns None for non-blob URIs and for any key that is not
    `uploads/{session_id}/<something>` (leading slash, backslash and `..`
    segments are rejected). A rejected blob URI is logged by session hash only.
    """
    if not source_uri.startswith(_BLOB_PREFIX):
        return None
    key = source_uri.removeprefix(_BLOB_PREFIX)
    prefix = f"uploads/{session_id}/"
    ok = (
        key.startswith(prefix)
        and len(key) > len(prefix)
        and not key.startswith("/")
        and "\\" not in key
        and ".." not in key.split("/")
    )
    if not ok:
        _log.warning(
            "rejected foreign blob key for session %s", session_hash(session_id)
        )
        return None
    return key


def reset_session(db: Database, session_id: str) -> list[str]:
    """Delete everything this session owns or changed; return its uploaded blob keys.

    Runs in one transaction, in FK-safe order. Chunks cascade with documents.
    Groups go in a single statement: Postgres checks the parent_id FK at the
    end of the statement, so nested owned groups can be deleted together.
    """
    params = {"sid": session_id}
    with db.transaction() as tx:
        uris = tx.fetch(
            "select source_uri from documents where session_id = :sid", params
        )
        tx.execute("delete from task_completions where session_id = :sid", params)
        tx.execute("delete from overrides where session_id = :sid", params)
        tx.execute("delete from tasks where session_id = :sid", params)
        tx.execute("delete from documents where session_id = :sid", params)
        tx.execute("delete from groups where session_id = :sid", params)
    keys = (blob_key_for(session_id, r["source_uri"]) for r in uris)
    return [k for k in keys if k is not None]
