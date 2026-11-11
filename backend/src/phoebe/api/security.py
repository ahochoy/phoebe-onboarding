from fastapi import HTTPException, Request

from phoebe.sessions import Session

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
