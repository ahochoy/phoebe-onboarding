import json
from enum import StrEnum
from typing import Any

from phoebe.db import Database


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
