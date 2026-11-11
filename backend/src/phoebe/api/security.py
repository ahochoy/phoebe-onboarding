from typing import Annotated

from fastapi import Depends, HTTPException, Request

from phoebe.sandbox import touch_sandbox
from phoebe.sessions import Session, sandbox_id

COOKIE_NAME = "phoebe_session"
CSRF_HEADER = "X-Phoebe-Csrf"


def require_session(request: Request) -> Session:
    sid = request.cookies.get(COOKIE_NAME)
    session = request.app.state.deps.sessions.get(sid) if sid else None
    if session is None:
        raise HTTPException(401, "session_expired")
    request.state.session_id = session.id
    return session


def require_csrf(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "csrf_required")


def require_sandbox(
    request: Request, session: Annotated[Session, Depends(require_session)]
) -> str:
    """The non-secret sandbox id for this session (never the raw token).
    Registers the sandbox (or bumps its last_seen) for the future sweeper."""
    sid = sandbox_id(session.id)
    touch_sandbox(request.app.state.deps.db, sid)
    return sid


Sandbox = Annotated[str, Depends(require_sandbox)]
