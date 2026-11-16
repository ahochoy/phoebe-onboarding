from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from phoebe.api.limits import DAY, HOUR
from phoebe.api.security import COOKIE_NAME, require_csrf, require_session
from phoebe.control import KillState
from phoebe.db import wake_database
from phoebe.limits import LimitsUnavailable
from phoebe.sessions import Session, sandbox_id

router = APIRouter(prefix="/api")
post_router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf)])
routers = (router, post_router)


StatusReason = Literal[
    "chat_paused",
    "demo_closed",
    "session_chat_limit",
    "global_chat_limit",
    "session_upload_limit",
    "global_upload_limit",
]


class StatusOut(BaseModel):
    state: KillState
    chat_available: bool
    upload_available: bool
    reasons: list[StatusReason]


def _unavailable(state: KillState) -> StatusOut:
    return StatusOut(
        state=state,
        chat_available=False,
        upload_available=False,
        reasons=["chat_paused"],
    )


@router.get("/status")
def status(request: Request) -> StatusOut:
    """Public, read-only: uses `peek` only, never `hit`."""
    deps = request.app.state.deps
    s = deps.settings
    try:
        state = deps.control.get()
    except LimitsUnavailable:
        return _unavailable("chat_paused")
    if state == "closed":
        return StatusOut(
            state=state,
            chat_available=False,
            upload_available=False,
            reasons=["demo_closed"],
        )
    if state == "chat_paused":
        return _unavailable(state)
    sid = request.cookies.get(COOKIE_NAME)
    session = deps.sessions.get(sid) if sid else None
    chat: list[StatusReason] = []
    upload: list[StatusReason] = []
    try:
        if session is not None:
            sb = sandbox_id(session.id)
            if deps.counters.peek(f"chat#{sb}", HOUR) >= s.chat_per_session_hour:
                chat.append("session_chat_limit")
            if deps.counters.peek(f"upload#{sb}", DAY) >= s.uploads_per_session_day:
                upload.append("session_upload_limit")
        if deps.counters.peek("chat#global", DAY) >= s.chat_global_day:
            chat.append("global_chat_limit")
        if deps.counters.peek("upload#global", DAY) >= s.uploads_global_day:
            upload.append("global_upload_limit")
    except LimitsUnavailable:
        return _unavailable(state)
    return StatusOut(
        state=state,
        chat_available=not chat,
        upload_available=not upload,
        reasons=[*chat, *upload],
    )


class WakeOut(BaseModel):
    database: Literal["awake", "waking"]


@post_router.post(
    "/wake",
    response_model=WakeOut,
    responses={202: {"model": WakeOut, "description": "The database is resuming."}},
)
def wake(
    request: Request, _session: Annotated[Session, Depends(require_session)]
) -> JSONResponse:
    """Signed-in only, so crawlers on the public landing page never wake the
    database. Uses the session (not the sandbox, whose registration writes to the
    database and would wait out the resume) and returns at once either way."""
    deps = request.app.state.deps
    deps.activity.touch()  # a visitor is here: the sweeper should expect work
    if wake_database(deps.db):
        return JSONResponse(WakeOut(database="awake").model_dump(), status_code=200)
    return JSONResponse(WakeOut(database="waking").model_dump(), status_code=202)
