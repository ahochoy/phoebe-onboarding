import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from phoebe.api.security import COOKIE_NAME, require_csrf, require_session
from phoebe.auth import verify_password
from phoebe.persona import Persona, get_persona
from phoebe.sandbox import reset_session
from phoebe.sessions import ABSOLUTE_TIMEOUT, Session, sandbox_id

# State-changing routes live on `post_router`, which carries the CSRF check by
# construction. GET-only routes live on `router`.
router = APIRouter(prefix="/api")
post_router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf)])
routers = (router, post_router)

# TODO(plan 2): per-IP rate limiting for /api/login. Until then this only caps
# concurrent scrypt work so a flood cannot pin every CPU.
_scrypt_slots = threading.BoundedSemaphore(4)

CurrentSession = Annotated[Session, Depends(require_session)]


class LoginBody(BaseModel):
    password: str = Field(max_length=256)


class Me(Persona):
    day_number: int


def _wipe_sandbox(request: Request, sandbox: str) -> None:
    deps = request.app.state.deps
    for key in reset_session(deps.db, sandbox):
        try:
            deps.blobs.delete(key)
        except KeyError:
            pass


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@post_router.post("/login", status_code=204)
def login(body: LoginBody, request: Request) -> Response:
    deps = request.app.state.deps
    if not _scrypt_slots.acquire(blocking=False):
        raise HTTPException(429, "too_many_attempts")
    try:
        ok = verify_password(body.password, deps.settings.password_hash)
    finally:
        _scrypt_slots.release()
    if not ok:
        raise HTTPException(401, "invalid_password")
    old_id = request.cookies.get(COOKIE_NAME)
    old = deps.sessions.get(old_id) if old_id else None
    if old is not None:
        _wipe_sandbox(request, sandbox_id(old.id))
        deps.sessions.delete(old.id)
    session = deps.sessions.create()
    response = Response(status_code=204)
    response.set_cookie(
        COOKIE_NAME,
        session.id,
        max_age=int(ABSOLUTE_TIMEOUT.total_seconds()),
        path="/",
        httponly=True,
        samesite="strict",
        secure=deps.settings.cookie_secure,
    )
    return response


@post_router.post("/logout", status_code=204)
def logout(request: Request, session: CurrentSession) -> Response:
    _wipe_sandbox(request, sandbox_id(session.id))
    request.app.state.deps.sessions.delete(session.id)
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
        secure=request.app.state.deps.settings.cookie_secure,
    )
    return response


@post_router.post("/reset", status_code=204)
def reset(request: Request, session: CurrentSession) -> Response:
    _wipe_sandbox(request, sandbox_id(session.id))
    return Response(status_code=204)


@router.get("/me")
def me(request: Request, _: CurrentSession) -> Me:
    deps = request.app.state.deps
    persona = get_persona(deps.db)
    day = (deps.today() - persona.start_date).days + 1
    return Me(**persona.model_dump(), day_number=day)
