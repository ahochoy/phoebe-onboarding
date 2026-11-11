from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from phoebe.api.security import COOKIE_NAME, require_csrf, require_session
from phoebe.auth import verify_password
from phoebe.persona import Persona, get_persona
from phoebe.sandbox import reset_session
from phoebe.sessions import ABSOLUTE_TIMEOUT, Session

router = APIRouter(prefix="/api")

CurrentSession = Annotated[Session, Depends(require_session)]


class LoginBody(BaseModel):
    password: str = Field(max_length=256)


class Me(Persona):
    day_number: int


def _wipe_sandbox(request: Request, session_id: str) -> None:
    deps = request.app.state.deps
    for key in reset_session(deps.db, session_id):
        try:
            deps.blobs.delete(key)
        except KeyError:
            pass


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/login", status_code=204, dependencies=[Depends(require_csrf)])
def login(body: LoginBody, request: Request) -> Response:
    deps = request.app.state.deps
    if not verify_password(body.password, deps.settings.password_hash):
        raise HTTPException(401, "invalid_password")
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


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request, session: CurrentSession) -> Response:
    _wipe_sandbox(request, session.id)
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


@router.post("/reset", status_code=204, dependencies=[Depends(require_csrf)])
def reset(request: Request, session: CurrentSession) -> Response:
    _wipe_sandbox(request, session.id)
    return Response(status_code=204)


@router.get("/me")
def me(request: Request, _: CurrentSession) -> Me:
    deps = request.app.state.deps
    persona = get_persona(deps.db)
    day = (deps.today() - persona.start_date).days + 1
    return Me(**persona.model_dump(), day_number=day)
