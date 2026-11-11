import uuid
from typing import Any

from pydantic import BaseModel

from phoebe.db import Database
from phoebe.overlay_sql import (
    EFFECTIVE_DOCUMENTS_SQL,
    EFFECTIVE_GROUPS_SQL,
    EFFECTIVE_TASKS_SQL,
)
from phoebe.sandbox import EntityKind, hide, patch


class GroupInUse(Exception):
    """The group still has child groups, tasks or documents."""


class GroupNode(BaseModel):
    id: str
    name: str
    kind: str
    parent_id: str | None
    owned: bool
    children: list[GroupNode] = []


def _effective(db: Database, session_id: str) -> list[dict[str, Any]]:
    return db.fetch(
        f"with eff_groups as ({EFFECTIVE_GROUPS_SQL}) "
        "select id, name, kind, parent_id, owned from eff_groups order by name, id",
        {"sid": session_id},
    )


def effective_group_ids(db: Database, session_id: str) -> set[str]:
    """Ids of every group effective for this session."""
    return {r["id"] for r in _effective(db, session_id)}


def visible_group_ids(db: Database, session_id: str, team_id: str) -> list[str]:
    """The team and its ancestors, over this session's effective groups."""
    rows = db.fetch(
        f"""
        with recursive eff_groups as ({EFFECTIVE_GROUPS_SQL}),
        chain as (
          select id, parent_id from eff_groups where id = :team
          union
          select g.id, g.parent_id from eff_groups g join chain c on g.id = c.parent_id
        )
        select id from chain
        """,
        {"sid": session_id, "team": team_id},
    )
    return [r["id"] for r in rows]


def group_tree(db: Database, session_id: str) -> list[GroupNode]:
    nodes = {r["id"]: GroupNode(**r) for r in _effective(db, session_id)}
    roots: list[GroupNode] = []
    for node in nodes.values():
        parent = nodes.get(node.parent_id) if node.parent_id else None
        if parent:
            parent.children.append(node)
        elif node.parent_id is None:
            roots.append(node)
    return roots


def create_group(
    db: Database, session_id: str, name: str, kind: str, parent_id: str
) -> str:
    if parent_id not in {r["id"] for r in _effective(db, session_id)}:
        raise ValueError(f"unknown parent group {parent_id}")
    group_id = "s-" + uuid.uuid4().hex[:10]
    db.execute(
        """
        insert into groups (id, name, kind, parent_id, session_id)
        values (:id, :name, :kind, :parent, :sid)
        """,
        {
            "id": group_id,
            "name": name,
            "kind": kind,
            "parent": parent_id,
            "sid": session_id,
        },
    )
    return group_id


def _find(db: Database, session_id: str, group_id: str) -> dict[str, Any] | None:
    return next((r for r in _effective(db, session_id) if r["id"] == group_id), None)


def rename_group(db: Database, session_id: str, group_id: str, name: str) -> bool:
    group = _find(db, session_id, group_id)
    if group is None:
        return False
    if group["owned"]:
        return (
            db.execute(
                "update groups set name = :name where id = :id and session_id = :sid",
                {"name": name, "id": group_id, "sid": session_id},
            )
            > 0
        )
    patch(db, session_id, EntityKind.GROUP, group_id, {"name": name})
    return True


# Built on the canonical overlay CTEs, so a seed doc or task patched into the
# group blocks the delete and one patched out of it does not.
_IN_USE_SQL = f"""
with eff_groups as ({EFFECTIVE_GROUPS_SQL}),
eff_docs as ({EFFECTIVE_DOCUMENTS_SQL}),
eff_tasks as ({EFFECTIVE_TASKS_SQL})
select
  exists (select 1 from eff_groups where parent_id = :gid)
  or exists (select 1 from people where team_id = :gid)
  or exists (select 1 from eff_docs where group_id = :gid)
  or exists (select 1 from eff_tasks where group_id = :gid) as in_use
"""


def delete_group(db: Database, session_id: str, group_id: str) -> bool:
    group = _find(db, session_id, group_id)
    if group is None:
        return False
    rows = db.fetch(_IN_USE_SQL, {"sid": session_id, "gid": group_id})
    if rows[0]["in_use"]:
        raise GroupInUse(group_id)
    if group["owned"]:
        db.execute(
            "delete from groups where id = :id and session_id = :sid",
            {"id": group_id, "sid": session_id},
        )
    else:
        hide(db, session_id, EntityKind.GROUP, group_id)
    return True
