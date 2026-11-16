import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
)
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

import boto3
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from phoebe.activity import ActivityRecorder, InMemoryActivityStore, make_activity
from phoebe.api.origin import OriginGuard
from phoebe.chat.models import (
    AnswerModel,
    ExtractiveAnswerModel,
    Guardrail,
    HeuristicRewriter,
    NoGuardrail,
    Rewriter,
    make_models,
)
from phoebe.config import Settings, resolve_secrets
from phoebe.control import ControlStore, InMemoryControlStore, make_control
from phoebe.db import ClosableDatabase, Database, DatabaseUnavailable, PsycopgDatabase
from phoebe.db_data_api import DataApiDatabase
from phoebe.embed import Embedder, make_embedder
from phoebe.ingest.pipeline import index_document
from phoebe.jobs import InlineJobQueue, JobQueue, JobUnavailable
from phoebe.jobs_sqs import SqsJobQueue
from phoebe.limits import (
    CounterStore,
    InMemoryCounterStore,
    LimitsUnavailable,
    make_counters,
)
from phoebe.logconfig import configure_logging
from phoebe.meta import EmbedderMismatch, check_embedder
from phoebe.sessions import (
    DynamoDBSessionStore,
    InMemorySessionStore,
    SessionStore,
    session_hash,
)
from phoebe.storage import BlobStore, BlobUnavailable, LocalBlobStore
from phoebe.storage_s3 import S3BlobStore

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
    counters: CounterStore = field(default_factory=InMemoryCounterStore)
    control: ControlStore = field(default_factory=InMemoryControlStore)
    answer: AnswerModel = field(default_factory=ExtractiveAnswerModel)
    rewriter: Rewriter = field(default_factory=HeuristicRewriter)
    guardrail: Guardrail = field(default_factory=NoGuardrail)
    activity: ActivityRecorder = field(
        default_factory=lambda: ActivityRecorder(InMemoryActivityStore())
    )


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

    @app.exception_handler(DatabaseUnavailable)
    async def _db_unavailable(request: Request, _: DatabaseUnavailable) -> Response:
        route = getattr(request.scope.get("route"), "path", None) or "-"
        _log.warning("database unavailable route=%s", route)
        return _error(503, "database_unavailable")

    @app.exception_handler(EmbedderMismatch)
    async def _embedder_mismatch(request: Request, _: EmbedderMismatch) -> Response:
        route = getattr(request.scope.get("route"), "path", None) or "-"
        _log.error("stored vectors come from another embedder route=%s", route)
        return _error(503, "embedder_mismatch")

    @app.exception_handler(BlobUnavailable)
    async def _blob_unavailable(request: Request, _: BlobUnavailable) -> Response:
        route = getattr(request.scope.get("route"), "path", None) or "-"
        _log.warning("blob store unavailable route=%s", route)
        return _error(503, "storage_unavailable")

    @app.exception_handler(JobUnavailable)
    async def _job_unavailable(request: Request, _: JobUnavailable) -> Response:
        route = getattr(request.scope.get("route"), "path", None) or "-"
        _log.warning("job queue unavailable route=%s", route)
        return _error(503, "queue_unavailable")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> Response:
        return _error(422, "invalid_request")


_OPEN_WHEN_CLOSED = ("/api/status", "/api/health")


def _is_closed(request: Request) -> bool:
    path = request.url.path
    if not path.startswith("/api/") or path in _OPEN_WHEN_CLOSED:
        return False
    try:
        return request.app.state.deps.control.get() == "closed"
    except LimitsUnavailable:
        return False  # unreadable never closes the site (AI stays paused)


def _install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _meta(request: Request, call_next: Callable[..., Any]) -> Response:
        rid = uuid.uuid4().hex
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            if _is_closed(request):
                response: Response = _error(503, "demo_closed")
            else:
                response = await call_next(request)
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
    from phoebe.api.routes_chat import routers as chat_routers
    from phoebe.api.routes_documents import routers as document_routers
    from phoebe.api.routes_portal import routers as portal_routers
    from phoebe.api.routes_status import routers as status_routers

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
    if deps.settings.origin_secret:
        # Added last, so outermost: rejects before any other work happens.
        app.add_middleware(OriginGuard, secret=deps.settings.origin_secret)
    for r in (
        *auth_routers,
        *portal_routers,
        *document_routers,
        *status_routers,
        *chat_routers,
    ):
        app.include_router(r)
    return app


def startup_check_embedder(db: Database, embedder: Embedder) -> None:
    """Fail fast if stored vectors came from a different embedder.

    `make stack` starts the API before `migrate`, so a database without the
    `app_meta` table yet has nothing recorded and is not a mismatch.
    """
    rows = db.fetch("select to_regclass('public.app_meta')::text t")
    if rows and rows[0]["t"] is not None:
        check_embedder(db, embedder)


class EmbedderCheckedDatabase:
    """The API's database: runs `startup_check_embedder` lazily, once per
    container, before the first statement of the first DB-using request.

    Nothing touches the database at import (a resuming Aurora would blow the
    Lambda init limit), and DB-free routes such as /api/health never wake it.
    `DatabaseUnavailable` propagates (the normal 503) and `EmbedderMismatch`
    becomes 503 `embedder_mismatch`; either way the next request checks again.
    """

    def __init__(self, inner: ClosableDatabase, embedder: Embedder) -> None:
        self._inner = inner
        self._embedder = embedder
        self._checked = False
        self._lock = threading.Lock()

    def _ensure_checked(self) -> None:
        if self._checked:
            return
        with self._lock:
            if not self._checked:
                startup_check_embedder(self._inner, self._embedder)
                self._checked = True

    def fetch(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self._ensure_checked()
        return self._inner.fetch(sql, params)

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        self._ensure_checked()
        return self._inner.execute(sql, params)

    def transaction(self) -> AbstractContextManager[Database]:
        self._ensure_checked()
        return self._inner.transaction()

    def close(self) -> None:
        self._inner.close()

    def __getattr__(self, name: str) -> Any:
        # Backend traits such as `text_slice_chars` come from the inner database.
        return getattr(self._inner, name)


def aws_client(service: str, region: str) -> Any:
    """Module-level factory so tests can swap every AWS client at once."""
    return boto3.client(service, region_name=region)  # type: ignore[call-overload]


def make_blobs(settings: Settings) -> BlobStore:
    if settings.blob_backend == "s3":
        if not settings.uploads_bucket:
            raise RuntimeError("PHOEBE_UPLOADS_BUCKET is required for s3")
        return S3BlobStore(
            settings.uploads_bucket, client=aws_client("s3", settings.aws_region)
        )
    return LocalBlobStore(Path(settings.blob_dir))


def make_jobs(settings: Settings, inline: Callable[[str], None]) -> JobQueue:
    if settings.job_backend == "sqs":
        if not settings.jobs_queue_url:
            raise RuntimeError("PHOEBE_JOBS_QUEUE_URL is required for sqs")
        return SqsJobQueue(
            settings.jobs_queue_url, client=aws_client("sqs", settings.aws_region)
        )
    return InlineJobQueue(inline)


def make_database(settings: Settings) -> ClosableDatabase:
    if settings.db_backend == "data_api":
        if not settings.db_cluster_arn:
            raise RuntimeError("PHOEBE_DB_CLUSTER_ARN is required for data_api")
        if not settings.db_secret_arn:
            raise RuntimeError("PHOEBE_DB_SECRET_ARN is required for data_api")
        return DataApiDatabase(
            settings.db_cluster_arn,
            settings.db_secret_arn,
            settings.db_name,
            client=aws_client("rds-data", settings.aws_region),
        )
    if not settings.database_url:
        raise RuntimeError("PHOEBE_DATABASE_URL is required for psycopg")
    return PsycopgDatabase(settings.database_url)


def create_configured_app() -> FastAPI:
    settings = Settings()  # values come from PHOEBE_* env
    configure_logging(settings.log_level)
    settings = resolve_secrets(settings)
    if not settings.password_hash:
        raise RuntimeError("PHOEBE_PASSWORD_HASH (or its secret ARN) is required")
    db = make_database(settings)
    try:
        return _configure(settings, db)
    except BaseException:
        db.close()
        raise


def build_deps(
    settings: Settings, db: ClosableDatabase, *, check_embedder_lazily: bool = False
) -> Deps:
    """The one place runtime dependencies are wired (API and Lambda handlers).
    Makes no network calls."""
    sessions: SessionStore
    if settings.session_backend == "dynamodb":
        if not settings.sessions_table:
            raise RuntimeError("PHOEBE_SESSIONS_TABLE is required for dynamodb")
        sessions = DynamoDBSessionStore(settings.sessions_table)
    else:
        sessions = InMemorySessionStore()
    blobs = make_blobs(settings)
    embedder = make_embedder(settings)
    if check_embedder_lazily:
        # The API only. Lambda handlers never check (they would wake an idle
        # Aurora); the ops seed task checks explicitly.
        db = EmbedderCheckedDatabase(db, embedder)
    answer, rewriter, guardrail = make_models(settings)
    jobs = make_jobs(
        settings,
        lambda doc_id: index_document(
            db,
            blobs,
            embedder,
            doc_id,
            seed_root=settings.seed_dir,
            max_chunks=settings.max_chunks_per_document,
        ),
    )
    return Deps(
        db,
        sessions,
        blobs,
        embedder,
        jobs,
        settings,
        counters=make_counters(settings),
        control=make_control(settings),
        answer=answer,
        rewriter=rewriter,
        guardrail=guardrail,
        activity=make_activity(settings),
    )


def _configure(settings: Settings, db: ClosableDatabase) -> FastAPI:
    deps = build_deps(settings, db, check_embedder_lazily=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            db.close()

    return create_app(deps, lifespan=lifespan)
