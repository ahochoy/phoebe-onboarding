from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from phoebe.db import Database
from phoebe.groups import EFFECTIVE_GROUPS_SQL, visible_group_ids
from phoebe.sandbox import EntityKind, hide, patch


def _check_https(value: str | None) -> str | None:
    if value is not None and not (
        value.startswith("https://") and len(value) > len("https://")
    ):
        raise ValueError("link must be an https URL")
    return value


class NewTask(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    link: str | None = None
    group_id: str
    position: int = 0

    _link = field_validator("link")(_check_https)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    link: str | None = None
    group_id: str | None = None
    position: int | None = None

    _link = field_validator("link")(_check_https)

    def changes(self) -> dict[str, Any]:
        """Fields the caller actually set (None means "leave unchanged")."""
        return self.model_dump(exclude_none=True)


class TaskView(BaseModel):
    id: str
    title: str
    description: str
    link: str | None
    group_id: str
    group_name: str
    group_kind: str
    position: int
    done: bool
    owned: bool


class PersonProgress(BaseModel):
    person_id: str
    name: str
    team_name: str
    department_name: str | None
    start_date: date
    done: int
    total: int


# CTE body (needs :sid) listing this session's effective tasks:
# seed tasks not hidden by the session with patch fields applied, plus owned tasks.
_EFFECTIVE_TASKS_SQL = """
select t.id,
       coalesce(o.patch->>'title', t.title) as title,
       coalesce(o.patch->>'description', t.description) as description,
       coalesce(o.patch->>'link', t.link) as link,
       coalesce(o.patch->>'group_id', t.group_id) as group_id,
       coalesce((o.patch->>'position')::int, t.position) as position,
       false as owned
from tasks t
left join overrides o
  on o.session_id = :sid and o.entity_kind = 'task' and o.entity_id = t.id::text
where t.session_id is null and not coalesce(o.hidden, false)
union all
select t.id, t.title, t.description, t.link, t.group_id, t.position, true
from tasks t
where t.session_id = :sid
"""


def _effective_group_ids(db: Database, session_id: str) -> set[str]:
    rows = db.fetch(
        f"with eff_groups as ({EFFECTIVE_GROUPS_SQL}) select id from eff_groups",
        {"sid": session_id},
    )
    return {r["id"] for r in rows}


def list_tasks(
    db: Database,
    session_id: str,
    *,
    group_ids: list[str] | None = None,
    person_id: str | None = None,
) -> list[TaskView]:
    """Effective tasks, ordered company, department, team, then position, title.

    `group_ids=None` means no group filter. `done` is resolved for `person_id`
    (a session completion row beats the seed row); False when no person is given.
    """
    rows = db.fetch(
        f"""
        with eff_groups as ({EFFECTIVE_GROUPS_SQL}),
        eff_tasks as ({_EFFECTIVE_TASKS_SQL})
        select et.id::text as id, et.title, et.description, et.link, et.group_id,
               g.name as group_name, g.kind as group_kind, et.position, et.owned,
               coalesce(
                 (select c.done from task_completions c
                   where c.person_id = :pid and c.task_id = et.id and c.session_id = :sid),
                 (select c.done from task_completions c
                   where c.person_id = :pid and c.task_id = et.id and c.session_id = ''),
                 false) as done
        from eff_tasks et
        join eff_groups g on g.id = et.group_id
        where (:gids::text[] is null or et.group_id = any(:gids::text[]))
        order by case g.kind when 'company' then 0 when 'department' then 1 else 2 end,
                 et.position, et.title, et.id
        """,
        {"sid": session_id, "pid": person_id, "gids": group_ids},
    )
    return [TaskView(**r) for r in rows]


def create_task(db: Database, session_id: str, task: NewTask) -> str:
    if task.group_id not in _effective_group_ids(db, session_id):
        raise ValueError(f"unknown group {task.group_id}")
    rows = db.fetch(
        """
        insert into tasks (session_id, title, description, link, group_id, position)
        values (:sid, :title, :description, :link, :group_id, :position)
        returning id::text as id
        """,
        {"sid": session_id, **task.model_dump()},
    )
    return rows[0]["id"]


def _visible_seed_task(db: Database, session_id: str, task_id: str) -> bool:
    """True if `task_id` is a seed task this session has not hidden."""
    rows = db.fetch(
        """
        select 1 from tasks t
        left join overrides o
          on o.session_id = :sid and o.entity_kind = 'task' and o.entity_id = t.id::text
        where t.id::text = :id and t.session_id is null
          and not coalesce(o.hidden, false)
        """,
        {"sid": session_id, "id": task_id},
    )
    return bool(rows)


def _owns(db: Database, session_id: str, task_id: str) -> bool:
    return bool(
        db.fetch(
            "select 1 from tasks where id::text = :id and session_id = :sid",
            {"sid": session_id, "id": task_id},
        )
    )


def update_task(
    db: Database, session_id: str, task_id: str, changes: TaskPatch
) -> bool:
    fields = changes.changes()
    owned = _owns(db, session_id, task_id)
    if not owned and not _visible_seed_task(db, session_id, task_id):
        return False
    if "group_id" in fields and fields["group_id"] not in _effective_group_ids(
        db, session_id
    ):
        raise ValueError(f"unknown group {fields['group_id']}")
    if not fields:
        return True
    if owned:
        sets = ", ".join(f"{name} = :{name}" for name in fields)
        db.execute(
            f"update tasks set {sets} where id::text = :id and session_id = :sid",
            {**fields, "id": task_id, "sid": session_id},
        )
    else:
        patch(db, session_id, EntityKind.TASK, task_id, fields)
    return True


def delete_task(db: Database, session_id: str, task_id: str) -> bool:
    if _owns(db, session_id, task_id):
        db.execute(
            "delete from tasks where id::text = :id and session_id = :sid",
            {"id": task_id, "sid": session_id},
        )
        return True
    if _visible_seed_task(db, session_id, task_id):
        hide(db, session_id, EntityKind.TASK, task_id)
        return True
    return False


def set_completion(
    db: Database, session_id: str, person_id: str, task_id: str, done: bool
) -> bool:
    """Upsert this session's completion row. False (nothing written) when the
    task is not effective for this session or the person does not exist."""
    if not (
        _owns(db, session_id, task_id) or _visible_seed_task(db, session_id, task_id)
    ):
        return False
    if not db.fetch("select 1 from people where id = :pid", {"pid": person_id}):
        return False
    db.execute(
        """
        insert into task_completions (person_id, task_id, session_id, done)
        values (:pid, :tid::uuid, :sid, :done)
        on conflict (person_id, task_id, session_id)
        do update set done = excluded.done, at = now()
        """,
        {"pid": person_id, "tid": task_id, "sid": session_id, "done": done},
    )
    return True


def progress(db: Database, session_id: str) -> list[PersonProgress]:
    """Per-person done/total over effective tasks in the person's visible groups."""
    people = db.fetch(
        """
        select p.id, p.name, p.team_id, p.start_date, g.name as seed_team_name
        from people p join groups g on g.id = p.team_id
        order by p.name, p.id
        """
    )
    groups = {
        r["id"]: r
        for r in db.fetch(
            f"with eff_groups as ({EFFECTIVE_GROUPS_SQL}) "
            "select id, name, kind from eff_groups",
            {"sid": session_id},
        )
    }
    out: list[PersonProgress] = []
    for person in people:
        visible = visible_group_ids(db, session_id, person["team_id"])
        tasks = list_tasks(db, session_id, group_ids=visible, person_id=person["id"])
        team = groups.get(person["team_id"])
        department = next(
            (
                groups[g]["name"]
                for g in visible
                if g in groups and groups[g]["kind"] == "department"
            ),
            None,
        )
        out.append(
            PersonProgress(
                person_id=person["id"],
                name=person["name"],
                team_name=team["name"] if team else person["seed_team_name"],
                department_name=department,
                start_date=person["start_date"],
                done=sum(t.done for t in tasks),
                total=len(tasks),
            )
        )
    return out
