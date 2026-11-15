from typing import Any

from fastapi import APIRouter, Request

from phoebe.api.limits import DAY, HOUR
from phoebe.api.security import COOKIE_NAME
from phoebe.limits import LimitsUnavailable
from phoebe.sessions import sandbox_id

router = APIRouter(prefix="/api")
routers = (router,)


def _unavailable(state: str) -> dict[str, Any]:
    return {
        "state": state,
        "chat_available": False,
        "upload_available": False,
        "reasons": ["chat_paused"],
    }


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    """Public, read-only: uses `peek` only, never `hit`."""
    deps = request.app.state.deps
    s = deps.settings
    try:
        state = deps.control.get()
    except LimitsUnavailable:
        return _unavailable("chat_paused")
    if state == "closed":
        return {
            "state": state,
            "chat_available": False,
            "upload_available": False,
            "reasons": ["demo_closed"],
        }
    if state == "chat_paused":
        return _unavailable(state) | {"reasons": ["chat_paused"]}
    sid = request.cookies.get(COOKIE_NAME)
    session = deps.sessions.get(sid) if sid else None
    chat: list[str] = []
    upload: list[str] = []
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
    return {
        "state": state,
        "chat_available": not chat,
        "upload_available": not upload,
        "reasons": [*chat, *upload],
    }
