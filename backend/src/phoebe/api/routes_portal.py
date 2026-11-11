import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, StringConstraints

from phoebe.api.security import Sandbox, require_csrf
from phoebe.groups import (
    GroupInUse,
    GroupNode,
    create_group,
    delete_group,
    group_tree,
    rename_group,
    visible_group_ids,
)
from phoebe.persona import PERSONA_ID, get_persona
from phoebe.tasks import (
    NewTask,
    PersonProgress,
    TaskPatch,
    TaskView,
    create_task,
    delete_task,
    list_tasks,
    progress,
    set_completion,
    update_task,
)

# State-changing routes live on `post_router` (CSRF by construction).
router = APIRouter(prefix="/api")
post_router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf)])
routers = (router, post_router)

Scope = Literal["mine", "all"]
GroupName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]

# A department hangs off the company, a team off a department.
_PARENT_KIND = {"department": "company", "team": "department"}


def parse_uuid(ident: str) -> str:
    """Canonical UUID string, or 404 `not_found` (unknown and malformed look alike)."""
    try:
        return str(uuid.UUID(ident))
    except ValueError:
        raise HTTPException(404, "not_found") from None


def _task_uuid(task_id: str) -> str:
    return parse_uuid(task_id)


def _doc_uuid(doc_id: str) -> str:
    return parse_uuid(doc_id)


TaskUuid = Annotated[str, Depends(_task_uuid)]
DocUuid = Annotated[str, Depends(_doc_uuid)]


def alex_groups(request: Request, session_id: str) -> list[str]:
    deps = request.app.state.deps
    return visible_group_ids(deps.db, session_id, get_persona(deps.db).team_id)


# ---- groups --------------------------------------------------------------


class NewGroup(BaseModel):
    name: GroupName
    kind: str
    parent_id: str


class GroupRename(BaseModel):
    name: GroupName


def _flatten(nodes: list[GroupNode]) -> dict[str, GroupNode]:
    out: dict[str, GroupNode] = {}
    for n in nodes:
        out[n.id] = n
        out.update(_flatten(n.children))
    return out


@router.get("/groups")
def get_groups(request: Request, sid: Sandbox) -> list[GroupNode]:
    return group_tree(request.app.state.deps.db, sid)


@post_router.post("/groups", status_code=201)
def post_group(body: NewGroup, request: Request, sid: Sandbox) -> dict[str, str]:
    db = request.app.state.deps.db
    want_parent = _PARENT_KIND.get(body.kind)
    parent = _flatten(group_tree(db, sid)).get(body.parent_id)
    if want_parent is None or parent is None or parent.kind != want_parent:
        raise HTTPException(422, "invalid_group")
    try:
        gid = create_group(db, sid, body.name, body.kind, body.parent_id)
    except ValueError:
        raise HTTPException(422, "invalid_group") from None
    return {"id": gid}


@post_router.patch("/groups/{group_id}", status_code=204)
def patch_group(
    group_id: str, body: GroupRename, request: Request, sid: Sandbox
) -> Response:
    if not rename_group(request.app.state.deps.db, sid, group_id, body.name):
        raise HTTPException(404, "not_found")
    return Response(status_code=204)


@post_router.delete("/groups/{group_id}", status_code=204)
def remove_group(group_id: str, request: Request, sid: Sandbox) -> Response:
    try:
        found = delete_group(request.app.state.deps.db, sid, group_id)
    except GroupInUse:
        raise HTTPException(409, "group_in_use") from None
    if not found:
        raise HTTPException(404, "not_found")
    return Response(status_code=204)


# ---- tasks ---------------------------------------------------------------


class Completion(BaseModel):
    done: bool


@router.get("/tasks")
def get_tasks(request: Request, sid: Sandbox, scope: Scope = "mine") -> list[TaskView]:
    db = request.app.state.deps.db
    gids = alex_groups(request, sid) if scope == "mine" else None
    return list_tasks(db, sid, group_ids=gids, person_id=PERSONA_ID)


@post_router.post("/tasks", status_code=201)
def post_task(body: NewTask, request: Request, sid: Sandbox) -> dict[str, str]:
    try:
        tid = create_task(request.app.state.deps.db, sid, body)
    except ValueError:
        raise HTTPException(422, "invalid_group") from None
    return {"id": tid}


@post_router.patch("/tasks/{task_id}", status_code=204)
def patch_task(
    task_id: TaskUuid, body: TaskPatch, request: Request, sid: Sandbox
) -> Response:
    try:
        found = update_task(request.app.state.deps.db, sid, task_id, body)
    except ValueError:
        raise HTTPException(422, "invalid_group") from None
    if not found:
        raise HTTPException(404, "not_found")
    return Response(status_code=204)


@post_router.delete("/tasks/{task_id}", status_code=204)
def remove_task(task_id: TaskUuid, request: Request, sid: Sandbox) -> Response:
    if not delete_task(request.app.state.deps.db, sid, task_id):
        raise HTTPException(404, "not_found")
    return Response(status_code=204)


@post_router.put("/tasks/{task_id}/completion", status_code=204)
def put_completion(
    task_id: TaskUuid, body: Completion, request: Request, sid: Sandbox
) -> Response:
    ok = set_completion(request.app.state.deps.db, sid, PERSONA_ID, task_id, body.done)
    if not ok:
        raise HTTPException(404, "not_found")
    return Response(status_code=204)


# ---- people --------------------------------------------------------------


@router.get("/people")
def get_people(request: Request, sid: Sandbox) -> list[PersonProgress]:
    return progress(request.app.state.deps.db, sid)


@router.get("/people/{person_id}/tasks")
def get_person_tasks(person_id: str, request: Request, sid: Sandbox) -> list[TaskView]:
    db = request.app.state.deps.db
    rows = db.fetch("select team_id from people where id = :id", {"id": person_id})
    if not rows:
        raise HTTPException(404, "not_found")
    gids = visible_group_ids(db, sid, rows[0]["team_id"])
    return list_tasks(db, sid, group_ids=gids, person_id=person_id)
