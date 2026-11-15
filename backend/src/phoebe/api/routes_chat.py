"""Chat API: `POST /api/chat` (Server-Sent Events) and `GET /api/chat/history`.

Every check (session, kill switch, validation, caps) runs before the stream
opens, so failures are ordinary JSON errors. Once streaming, the wire format is
`event: <name>\\ndata: <json>\\n\\n` per `ChatEvent`.

Streamed `delta` text carries the model's raw citation labels (for example
`[P3]`). Verification renumbers labels and citations in order of first use, so
`done.text` and `citations[].n` differ from the streamed text. The client must
ALWAYS replace the streamed text with `done.text` on `done`, refused or not.

`run_chat` is a sync generator that may hold a Bedrock stream open. Starlette
would iterate it in a threadpool and never close it on disconnect, so it is
wrapped in an async generator that pulls each event via the threadpool and
closes it (shielded from cancellation) the moment the response ends.
"""

import json
from collections.abc import AsyncIterator, Generator
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from phoebe.api.limits import charge_chat, require_ai_open
from phoebe.api.routes_portal import alex_groups
from phoebe.api.security import Sandbox, require_csrf
from phoebe.chat.history import TurnOut, list_turns
from phoebe.chat.service import ChatContext, ChatEvent, run_chat

router = APIRouter(prefix="/api")
post_router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf)])
routers = (router, post_router)

# A static ceiling so oversized bodies fail parsing; the real limit is the
# `question_max_chars` setting, checked in the route.
_QUESTION_HARD_CAP = 4000


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(max_length=_QUESTION_HARD_CAP)


def _open_sandbox(request: Request, sid: Sandbox) -> str:
    """Session first, then the kill switch; both before the body is validated."""
    require_ai_open(request)
    return sid


OpenSandbox = Annotated[str, Depends(_open_sandbox)]


def sse_frame(event: ChatEvent) -> str:
    # json.dumps never emits raw newlines, so each frame is one data line.
    data = json.dumps(event.data, separators=(",", ":"))
    return f"event: {event.name}\ndata: {data}\n\n"


async def _sse(gen: Generator[ChatEvent]) -> AsyncIterator[str]:
    try:
        while True:
            event: ChatEvent | None = await run_in_threadpool(next, gen, None)
            if event is None:
                return
            yield sse_frame(event)
    finally:
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(gen.close)


class _EventStream(StreamingResponse):
    """Closes the event iterator as soon as the response ends, however it ends."""

    def __init__(self, events: AsyncIterator[str]) -> None:
        super().__init__(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
        self._events = events

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            aclose = getattr(self._events, "aclose", None)
            if aclose is not None:
                with anyio.CancelScope(shield=True):
                    await aclose()


@post_router.post("/chat")
def chat(body: ChatBody, request: Request, sid: OpenSandbox) -> StreamingResponse:
    deps = request.app.state.deps
    question = body.question.strip()
    if not question or len(question) > deps.settings.question_max_chars:
        raise HTTPException(422, "invalid_request")
    charge_chat(request, sid)
    ctx = ChatContext(
        db=deps.db,
        embedder=deps.embedder,
        answer=deps.answer,
        rewriter=deps.rewriter,
        guardrail=deps.guardrail,
        settings=deps.settings,
    )
    return _EventStream(_sse(run_chat(ctx, sid, question)))


@router.get("/chat/history")
def chat_history(request: Request, sid: Sandbox) -> list[TurnOut]:
    return list_turns(request.app.state.deps.db, sid, alex_groups(request, sid))
