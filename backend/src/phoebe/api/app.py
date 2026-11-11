import logging
import re
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from phoebe.config import Settings
from phoebe.db import Database, PsycopgDatabase
from phoebe.embed import Embedder, HashEmbedder
from phoebe.ingest.pipeline import index_document
from phoebe.jobs import InlineJobQueue, JobQueue
from phoebe.sessions import (
    DynamoDBSessionStore,
    InMemorySessionStore,
    SessionStore,
    session_hash,
)
from phoebe.storage import BlobStore, LocalBlobStore

_log = logging.getLogger("phoebe.api")


def utc_today() -> date:
    return datetime.now(UTC).date()


@dataclass
class Deps:
    db: Database
    sessions: SessionStore
    blobs: BlobStore
    embedder: Embedder
    jobs: JobQueue
    settings: Settings
    today: Callable[[], date] = field(default=utc_today)


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"detail": code}, status_code=status)


_CODE_RE = re.compile(r"^[a-z_]+$")


def _code(status: int, detail: Any) -> str | None:
    """A snake_case code, or None if `detail` isn't one (never echo free text)."""
    if isinstance(detail, str):
        if _CODE_RE.fullmatch(detail):
            return detail
        try:
            if detail == HTTPStatus(status).phrase:  # Starlette's own 404/405
                return detail.lower().replace(" ", "_")
        except ValueError:
            pass
    return None


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        code = _code(exc.status_code, exc.detail)
        if code is None:
            route = getattr(request.scope.get("route"), "path", None) or "-"
            _log.error("non-code HTTPException detail route=%s", route)
            return _error(500, "internal_error")
        resp = _error(exc.status_code, code)
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> Response:
        return _error(422, "invalid_request")


def _install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _meta(request: Request, call_next: Callable[..., Any]) -> Response:
        rid = uuid.uuid4().hex
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - last-resort 500, logs type only
            _log.error("unhandled %s request_id=%s", type(exc).__name__, rid)
            response = _error(500, "internal_error")
        route = request.scope.get("route")
        template = getattr(route, "path", None) or "-"
        sid = getattr(request.state, "session_id", None)
        _log.info(
            "%s %s %d %.1fms %s",
            request.method,
            template,
            response.status_code,
            (time.perf_counter() - start) * 1000,
            session_hash(sid) if sid else "-",
        )
        response.headers["X-Request-Id"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def create_app(
    deps: Deps,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    """Build the app. The default lifespan does not close `deps.db` (callers own it)."""
    from phoebe.api.routes_auth import routers as auth_routers

    @asynccontextmanager
    async def _noop(_: FastAPI):
        yield

    app = FastAPI(
        lifespan=lifespan or _noop,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # CORS is deliberately NOT configured. The X-Phoebe-Csrf header is a custom
    # header, so a cross-origin page can only send it after a successful CORS
    # preflight. With no CORS middleware the preflight fails and the browser
    # blocks the request; adding permissive CORS would disable this CSRF defence.
    app.state.deps = deps
    _install_error_handlers(app)
    _install_middleware(app)
    for r in auth_routers:
        app.include_router(r)
    return app


def create_configured_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]  # values come from PHOEBE_* env
    db = PsycopgDatabase(settings.database_url)
    sessions: SessionStore
    if settings.session_backend == "dynamodb":
        if not settings.sessions_table:
            raise RuntimeError("PHOEBE_SESSIONS_TABLE is required for dynamodb")
        sessions = DynamoDBSessionStore(settings.sessions_table)
    else:
        sessions = InMemorySessionStore()
    blobs = LocalBlobStore(Path(settings.blob_dir))
    embedder = HashEmbedder()
    jobs = InlineJobQueue(
        lambda doc_id: index_document(
            db, blobs, embedder, doc_id, seed_root=settings.seed_dir
        )
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            db.close()

    return create_app(
        Deps(db, sessions, blobs, embedder, jobs, settings), lifespan=lifespan
    )
