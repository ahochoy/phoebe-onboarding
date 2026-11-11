import contextlib
import uuid
from datetime import date
from typing import Annotated, Literal

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from phoebe.api.background import run_guarded
from phoebe.api.routes_portal import DocUuid, alex_groups
from phoebe.api.security import require_csrf, require_session
from phoebe.documents import (
    DocType,
    DocumentPatch,
    DocumentSummary,
    NewDocument,
    SandboxFull,
    create_document,
    delete_document,
    get_document,
    list_documents,
    update_document,
)
from phoebe.ingest.fetch import google_doc_export_url
from phoebe.ingest.parse import ParseError, sniff_upload
from phoebe.retrieve import Passage, search
from phoebe.sessions import Session

router = APIRouter(prefix="/api")
post_router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf)])
routers = (router, post_router)

CurrentSession = Annotated[Session, Depends(require_session)]

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_CHUNK = 64 * 1024
# Multipart framing (boundaries, field parts) on top of the file itself.
_MULTIPART_SLACK = 64 * 1024
MAX_LINK_CHARS = 2000


class UploadMeta(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(default="", max_length=500)
    last_updated: date | None = None
    group_id: str = Field(min_length=1)


class LinkBody(BaseModel):
    url: str
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(default="", max_length=500)
    last_updated: date | None = None
    group_id: str = Field(min_length=1)


class SearchBody(BaseModel):
    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


def _summary(request: Request, session_id: str, doc_id: str) -> DocumentSummary:
    detail = get_document(request.app.state.deps.db, session_id, doc_id)
    if detail is None:  # raced with a reset/delete
        raise HTTPException(404, "not_found")
    return DocumentSummary(**detail.model_dump(exclude={"full_text", "sections"}))


def _enqueue(request: Request, background: BackgroundTasks, doc_id: str) -> None:
    background.add_task(
        run_guarded,
        request.app.state.deps.jobs.enqueue,
        doc_id,
        request_id=request.state.request_id,
    )


def _read_capped(file: UploadFile) -> bytes | None:
    """File bytes, or None as soon as more than MAX_UPLOAD_BYTES have been seen."""
    buf = bytearray()
    while chunk := file.file.read(_CHUNK):
        buf += chunk
        if len(buf) > MAX_UPLOAD_BYTES:
            return None
    return bytes(buf)


def _too_large() -> HTTPException:
    return HTTPException(413, "file_too_large")


@router.get("/documents")
def get_documents(
    request: Request, session: CurrentSession, scope: Literal["mine", "all"] = "mine"
) -> list[DocumentSummary]:
    gids = alex_groups(request, session.id) if scope == "mine" else None
    return list_documents(request.app.state.deps.db, session.id, group_ids=gids)


@router.get("/documents/{doc_id}")
def get_one_document(doc_id: DocUuid, request: Request, session: CurrentSession):
    detail = get_document(request.app.state.deps.db, session.id, doc_id)
    if detail is None:
        raise HTTPException(404, "not_found")
    return detail


@post_router.post("/documents/upload", status_code=202)
def upload_document(
    request: Request,
    background: BackgroundTasks,
    session: CurrentSession,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()],
    group_id: Annotated[str, Form()],
    purpose: Annotated[str, Form()] = "",
    last_updated: Annotated[str, Form()] = "",
) -> Response:
    deps = request.app.state.deps
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES + _MULTIPART_SLACK:
        raise _too_large()
    data = _read_capped(file)
    if data is None:
        raise _too_large()
    try:
        meta = UploadMeta(
            title=title,
            purpose=purpose,
            last_updated=last_updated or None,  # type: ignore[arg-type]
            group_id=group_id,
        )
    except ValidationError:
        raise HTTPException(422, "invalid_request") from None
    try:
        doc_type = sniff_upload(file.filename or "", data)
    except ParseError as exc:
        return JSONResponse(
            {"detail": "unsupported_type", "reason": exc.reason}, status_code=415
        )
    doc_id = str(uuid.uuid4())
    key = f"uploads/{session.id}/{doc_id}"
    deps.blobs.put(key, data)
    try:
        create_document(
            deps.db,
            session.id,
            NewDocument(
                title=meta.title,
                purpose=meta.purpose,
                last_updated=meta.last_updated,
                doc_type=doc_type,
                group_id=meta.group_id,
                source_uri=f"blob://{key}",
            ),
            doc_id=doc_id,
        )
    except Exception as exc:
        with contextlib.suppress(Exception):  # cleanup must not mask the real error
            deps.blobs.delete(key)
        if isinstance(exc, SandboxFull):
            raise HTTPException(409, "sandbox_full") from None
        if isinstance(exc, ValueError):
            raise HTTPException(422, "invalid_group") from None
        raise
    summary = _summary(request, session.id, doc_id)
    _enqueue(request, background, doc_id)
    return JSONResponse(summary.model_dump(mode="json"), status_code=202)


def _valid_link(url: str) -> bool:
    if len(url) > MAX_LINK_CHARS or not url.startswith("https://"):
        return False
    try:
        return bool(httpx.URL(url).host)
    except httpx.InvalidURL:
        return False


@post_router.post("/documents/link", status_code=202)
def link_document(
    body: LinkBody,
    request: Request,
    background: BackgroundTasks,
    session: CurrentSession,
) -> Response:
    if not _valid_link(body.url):
        raise HTTPException(422, "invalid_link")
    doc_type: DocType = "google_doc" if google_doc_export_url(body.url) else "web"
    try:
        doc_id = create_document(
            request.app.state.deps.db,
            session.id,
            NewDocument(
                title=body.title,
                purpose=body.purpose,
                last_updated=body.last_updated,
                doc_type=doc_type,
                group_id=body.group_id,
                source_uri=body.url,
            ),
        )
    except SandboxFull:
        raise HTTPException(409, "sandbox_full") from None
    except ValueError:
        raise HTTPException(422, "invalid_group") from None
    summary = _summary(request, session.id, doc_id)
    _enqueue(request, background, doc_id)
    return JSONResponse(summary.model_dump(mode="json"), status_code=202)


@post_router.patch("/documents/{doc_id}", status_code=204)
def patch_document(
    doc_id: DocUuid, body: DocumentPatch, request: Request, session: CurrentSession
) -> Response:
    try:
        found = update_document(request.app.state.deps.db, session.id, doc_id, body)
    except ValueError:
        raise HTTPException(422, "invalid_group") from None
    if not found:
        raise HTTPException(404, "not_found")
    return Response(status_code=204)


@post_router.delete("/documents/{doc_id}", status_code=204)
def remove_document(
    doc_id: DocUuid, request: Request, session: CurrentSession
) -> Response:
    deps = request.app.state.deps
    result = delete_document(deps.db, session.id, doc_id)
    if not result.deleted:
        raise HTTPException(404, "not_found")
    if result.blob_key:
        try:
            deps.blobs.delete(result.blob_key)
        except KeyError:
            pass
    return Response(status_code=204)


@post_router.post("/search")
def search_documents(
    body: SearchBody, request: Request, session: CurrentSession
) -> list[Passage]:
    deps = request.app.state.deps
    return search(
        deps.db, deps.embedder, session.id, alex_groups(request, session.id), body.query
    )
