"""Per-sandbox chat history.

Visibility of cited chunks means exactly what retrieval means: the chunk's
document is effective for the sandbox, indexed, and in an allowed group.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from phoebe.chat.models import Message
from phoebe.chat.verify import Citation
from phoebe.db import Database
from phoebe.groups import visible_group_ids
from phoebe.overlay_sql import EFFECTIVE_DOCUMENTS_SQL, EFFECTIVE_GROUPS_SQL
from phoebe.persona import get_persona

WITHDRAWN = "(Earlier answer withdrawn: its source is no longer available.)"

_VISIBLE_CHUNKS_SQL = f"""
with eff_groups as ({EFFECTIVE_GROUPS_SQL}),
eff as ({EFFECTIVE_DOCUMENTS_SQL}),
visible as (
  select id from eff
  where status = 'indexed' and group_id = any(:groups::text[])
)
select c.id::text chunk_id
from chunks c join visible d on d.id = c.document_id
where c.id::text = any(:ids::text[])
"""

# Turns are inserted user-then-assistant; role breaks a created_at tie.
_ORDER = "created_at, case role when 'user' then 0 else 1 end, id"


class TurnCitation(Citation):
    removed: bool


class TurnOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    refused: bool
    created_at: datetime
    citations: list[TurnCitation]


def visible_chunk_ids(
    db: Database, sandbox: str, group_ids: Sequence[str], chunk_ids: Sequence[str]
) -> set[str]:
    """The subset of `chunk_ids` still visible to this sandbox (one query)."""
    if not chunk_ids or not group_ids:
        return set()
    rows = db.fetch(
        _VISIBLE_CHUNKS_SQL,
        {"sid": sandbox, "groups": list(group_ids), "ids": list(chunk_ids)},
    )
    return {r["chunk_id"] for r in rows}


def _cited(rows: Sequence[dict[str, Any]]) -> list[str]:
    return sorted({c["chunk_id"] for r in rows for c in r["citations"]})


def recent(
    db: Database,
    sandbox: str,
    n: int,
    *,
    group_ids: Sequence[str] | None = None,
    max_chars: int,
) -> list[Message]:
    """The last `n` user/assistant pairs, oldest first, each text truncated."""
    if n <= 0:
        return []
    rows = db.fetch(
        f"""
        select * from (
          select id, role, text, citations, refused, created_at from chat_turns
          where session_id = :sid
          order by created_at desc, case role when 'user' then 0 else 1 end desc,
                   id desc
          limit :lim
        ) t order by {_ORDER}
        """,
        {"sid": sandbox, "lim": n * 2},
    )
    if rows and rows[0]["role"] == "assistant":
        rows = rows[1:]
    if group_ids is None:
        group_ids = visible_group_ids(db, sandbox, get_persona(db).team_id)
    visible = visible_chunk_ids(db, sandbox, group_ids, _cited(rows))
    out: list[Message] = []
    for r in rows:
        text: str = r["text"]
        if r["role"] == "assistant" and any(
            c["chunk_id"] not in visible for c in r["citations"]
        ):
            text = WITHDRAWN
        out.append({"role": r["role"], "text": text[:max_chars]})
    return out


def list_turns(db: Database, sandbox: str, group_ids: Sequence[str]) -> list[TurnOut]:
    """Every turn for the sandbox, oldest first, citations marked `removed`."""
    rows = db.fetch(
        "select id::text id, role, text, citations, refused, created_at"
        f" from chat_turns where session_id = :sid order by {_ORDER}",
        {"sid": sandbox},
    )
    visible = visible_chunk_ids(db, sandbox, group_ids, _cited(rows))
    return [
        TurnOut(
            id=r["id"],
            role=r["role"],
            text=r["text"],
            refused=r["refused"],
            created_at=r["created_at"],
            citations=[
                TurnCitation(**c, removed=c["chunk_id"] not in visible)
                for c in r["citations"]
            ],
        )
        for r in rows
    ]
