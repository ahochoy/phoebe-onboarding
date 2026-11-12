"""Chat orchestration: guardrail, history, rewrite, search, refusal gate,
streamed answer, citation verification, visibility re-check, output guardrail,
persistence.

`run_chat` is a generator of `ChatEvent`s: `meta`, zero or more `delta`, then
one terminal `done` or `error`. Closing it early closes the model stream and
persists nothing. Logs carry metadata only, never question or answer text.
"""

import json
import logging
import time
from collections.abc import Callable, Generator, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from phoebe.chat.history import recent, visible_chunk_ids
from phoebe.chat.models import (
    NO_ANSWER,
    AnswerModel,
    Guardrail,
    ModelUnavailable,
    Rewriter,
)
from phoebe.chat.prompt import build_messages
from phoebe.chat.verify import Citation, verify
from phoebe.config import Settings
from phoebe.db import Database
from phoebe.embed import Embedder
from phoebe.groups import visible_group_ids
from phoebe.persona import get_persona
from phoebe.retrieve import Passage, search
from phoebe.sessions import log_id as default_log_id

log = logging.getLogger(__name__)

REFUSAL_TEXT = "I couldn't find that in your onboarding documents."
SEARCH_K = 5
SEARCH_CANDIDATES = 20
CLOSEST_MAX = 3
# Starting values, re-tuned on the eval set in Plan 5.
_DEFAULT_MIN_SIMILARITY = {"hash-v1-1024": 0.05, "titan-v2-1024": 0.25}
_FALLBACK_MIN_SIMILARITY = 0.25

Reason = Literal["no_support", "verification_failed", "blocked", "model_unavailable"]


@dataclass
class ChatEvent:
    name: Literal["meta", "delta", "done", "error"]
    data: dict[str, Any]


@dataclass
class ChatContext:
    db: Database
    embedder: Embedder
    answer: AnswerModel
    rewriter: Rewriter
    guardrail: Guardrail
    settings: Settings
    log_id: Callable[[str], str] = default_log_id


@dataclass
class _Outcome:
    text: str
    reason: Reason | None = None
    citations: list[Citation] = field(default_factory=list)
    closest: list[dict[str, str]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "refused": self.reason is not None,
            "reason": self.reason,
            "citations": [c.model_dump() for c in self.citations],
            "closest": self.closest,
        }


@dataclass
class _Stats:
    passages: list[str] = field(default_factory=list)
    top_sim: float = 0.0
    model_ms: int = 0
    out_chars: int = 0


def min_similarity(settings: Settings, embedder: Embedder) -> float:
    if settings.refusal_min_similarity is not None:
        return settings.refusal_min_similarity
    return _DEFAULT_MIN_SIMILARITY.get(embedder.id, _FALLBACK_MIN_SIMILARITY)


def _closest(passages: Sequence[Passage]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for p in passages:
        if p.document_id not in seen:
            seen.add(p.document_id)
            out.append({"document_id": p.document_id, "title": p.document_title})
            if len(out) == CLOSEST_MAX:
                break
    return out


def _refuse(reason: Reason, passages: Sequence[Passage] = ()) -> _Outcome:
    return _Outcome(text=REFUSAL_TEXT, reason=reason, closest=_closest(passages))


def _held(text: str) -> bool:
    """True while `text` could still be, or already is, a NO_ANSWER reply.

    Once an answer starts with NO_ANSWER none of it is ever streamed.
    """
    head = text.lstrip()
    return NO_ANSWER.startswith(head) or head.startswith(NO_ANSWER)


def _answer(
    ctx: ChatContext, sandbox: str, question: str, st: _Stats
) -> Generator[ChatEvent, None, _Outcome]:
    db, settings = ctx.db, ctx.settings
    try:
        if not ctx.guardrail.check(question, "INPUT"):
            return _refuse("blocked")
    except ModelUnavailable:
        return _refuse("model_unavailable")

    groups = visible_group_ids(db, sandbox, get_persona(db).team_id)
    history = recent(
        db,
        sandbox,
        n=settings.history_exchanges,
        group_ids=groups,
        max_chars=settings.history_turn_max_chars,
    )
    query = ctx.rewriter.rewrite(history, question).strip() or question.strip()
    if not query:
        return _refuse("no_support")
    passages = search(
        db,
        ctx.embedder,
        sandbox,
        groups,
        query,
        k=SEARCH_K,
        candidates=SEARCH_CANDIDATES,
    )
    st.passages = [p.chunk_id for p in passages]
    st.top_sim = max((p.similarity for p in passages), default=0.0)
    if not passages or (
        st.top_sim < min_similarity(settings, ctx.embedder)
        and all(p.text_rank is None for p in passages)
    ):
        return _refuse("no_support", passages)

    cap = settings.answer_max_chars
    answer = ""
    holding = True
    overflow = False
    started = time.monotonic()
    messages = build_messages(history, passages, question)
    stream: Iterator[str] | None = None
    try:
        stream = ctx.answer.stream(messages)
        for delta in stream:
            if len(answer) + len(delta) > cap:
                overflow = True
                break
            answer += delta
            if holding:
                if _held(answer):
                    continue
                holding = False
                delta = answer  # flush what was held back
            if delta:
                yield ChatEvent("delta", {"text": delta})
    except ModelUnavailable:
        return _refuse("model_unavailable", passages)
    finally:
        close = getattr(stream, "close", None) if stream is not None else None
        if close is not None:
            close()
        st.model_ms = int((time.monotonic() - started) * 1000)
        st.out_chars = len(answer)
    if overflow:
        return _refuse("verification_failed", passages)
    if answer.strip().startswith(NO_ANSWER):
        return _refuse("no_support", passages)

    verified = verify(answer, passages)
    if verified is None:
        return _refuse("verification_failed", passages)
    cited = {c.chunk_id for c in verified.citations}
    if visible_chunk_ids(db, sandbox, groups, sorted(cited)) != cited:
        return _refuse("verification_failed", passages)
    try:
        if not ctx.guardrail.check(verified.text, "OUTPUT"):
            return _refuse("blocked", passages)
    except ModelUnavailable:
        return _refuse("model_unavailable", passages)
    return _Outcome(text=verified.text, citations=verified.citations)


def _persist(
    db: Database, sandbox: str, turn_id: str, question: str, out: _Outcome
) -> None:
    with db.transaction() as tx:
        tx.execute(
            """
            insert into chat_turns (session_id, role, text, created_at)
            values (:sid, 'user', :text, clock_timestamp())
            """,
            {"sid": sandbox, "text": question},
        )
        tx.execute(
            """
            insert into chat_turns (id, session_id, role, text, citations, refused,
                                    created_at)
            values (:id, :sid, 'assistant', :text, :citations::jsonb, :refused,
                    clock_timestamp())
            """,
            {
                "id": turn_id,
                "sid": sandbox,
                "text": out.text,
                "citations": json.dumps([c.model_dump() for c in out.citations]),
                "refused": out.reason is not None,
            },
        )


def run_chat(ctx: ChatContext, sandbox: str, question: str) -> Generator[ChatEvent]:
    turn_id = str(uuid4())
    yield ChatEvent("meta", {"turn_id": turn_id})
    st = _Stats()
    try:
        outcome = yield from _answer(ctx, sandbox, question, st)
        _persist(ctx.db, sandbox, turn_id, question, outcome)
    except Exception as exc:  # noqa: BLE001 - type name only; may carry text
        log.warning(
            "chat error sandbox=%s turn=%s error=%s",
            ctx.log_id(sandbox),
            turn_id,
            type(exc).__name__,
        )
        yield ChatEvent("error", {"code": "internal_error"})
        return
    log.info(
        "chat sandbox=%s turn=%s passages=%s top_sim=%.3f refused=%s model_ms=%d"
        " out_chars=%d",
        ctx.log_id(sandbox),
        turn_id,
        st.passages,
        st.top_sim,
        outcome.reason or "-",
        st.model_ms,
        st.out_chars,
    )
    yield ChatEvent("done", outcome.payload())
