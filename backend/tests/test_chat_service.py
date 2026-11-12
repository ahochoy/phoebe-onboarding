import json
import logging
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Literal

import pytest

from conftest import SEED_DIR
from phoebe.chat import service
from phoebe.chat.models import (
    NO_ANSWER,
    ExtractiveAnswerModel,
    HeuristicRewriter,
    Message,
    ModelUnavailable,
    NoGuardrail,
)
from phoebe.chat.service import REFUSAL_TEXT, ChatContext, ChatEvent, run_chat
from phoebe.config import Settings
from phoebe.documents import delete_document
from phoebe.embed import HashEmbedder
from phoebe.retrieve import Passage
from phoebe.seed import load_seed

SB = "a" * 64
PTO = "How many PTO days do I get?"


class ScriptedAnswerModel:
    def __init__(
        self,
        deltas: Sequence[str],
        *,
        on_delta: Callable[[int], None] | None = None,
        fail_after: int | None = None,
    ) -> None:
        self.deltas = list(deltas)
        self.on_delta = on_delta
        self.fail_after = fail_after
        self.calls = 0
        self.closed = False
        self.consumed = 0

    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        self.calls += 1
        try:
            for i, d in enumerate(self.deltas):
                if self.fail_after is not None and i >= self.fail_after:
                    raise ModelUnavailable("model stream failed")
                if self.on_delta:
                    self.on_delta(i)
                self.consumed += 1
                yield d
        finally:
            self.closed = True


class NeverCalledModel:
    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        raise AssertionError("model must not be called")


class ScriptedGuardrail:
    def __init__(self, *, block: str | None = None, fail: str | None = None):
        self.block = block
        self.fail = fail
        self.seen: list[str] = []

    def check(self, text: str, source: Literal["INPUT", "OUTPUT"]) -> bool:
        self.seen.append(source)
        if source == self.fail:
            raise ModelUnavailable("guardrail request failed")
        return source != self.block


class SpyEmbedder(HashEmbedder):
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return super().embed(texts)


@pytest.fixture
def seeded(db):
    load_seed(db, HashEmbedder(), SEED_DIR)
    return db


def ctx(db, *, answer=None, guardrail=None, rewriter=None, embedder=None, **kw):
    settings = Settings(database_url="postgresql://unused", password_hash="x", **kw)
    return ChatContext(
        db=db,
        embedder=embedder or HashEmbedder(),
        answer=answer or ExtractiveAnswerModel(),
        rewriter=rewriter or HeuristicRewriter(),
        guardrail=guardrail or NoGuardrail(),
        settings=settings,
    )


def run(c: ChatContext, question: str = PTO, sandbox: str = SB) -> list[ChatEvent]:
    return list(run_chat(c, sandbox, question))


def turns(db, sandbox: str = SB) -> list[dict[str, Any]]:
    return db.fetch(
        "select role, text, citations, refused from chat_turns where session_id = :s"
        " order by created_at, role desc",
        {"s": sandbox},
    )


def assert_refused(events: list[ChatEvent], reason: str) -> dict[str, Any]:
    assert events[0].name == "meta"
    done = events[-1]
    assert done.name == "done", done
    assert done.data["refused"] is True
    assert done.data["reason"] == reason
    assert done.data["text"] == REFUSAL_TEXT
    assert done.data["citations"] == []
    return done.data


def handbook_id(db) -> str:
    return db.fetch(
        "select id::text id from documents where title = 'Employee Handbook'"
    )[0]["id"]


def test_happy_path_events(seeded, caplog):
    caplog.set_level(logging.INFO)
    events = run(ctx(seeded))
    names = [e.name for e in events]
    assert names[0] == "meta" and names[-1] == "done"
    assert "delta" in names
    assert set(names[1:-1]) == {"delta"}
    meta, done = events[0].data, events[-1].data
    assert meta["turn_id"]
    assert done["refused"] is False and done["reason"] is None
    assert done["closest"] == []
    assert done["citations"]
    assert done["citations"][0]["document_title"] == "Employee Handbook"
    assert done["citations"][0]["document_id"] == handbook_id(seeded)
    assert "20 days" in done["text"]
    rows = turns(seeded)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["text"] == PTO
    assert rows[1]["text"] == done["text"]
    assert rows[1]["citations"] == done["citations"]
    assert rows[1]["refused"] is False
    ids = seeded.fetch("select id::text id from chat_turns where role = 'assistant'")
    assert ids[0]["id"] == meta["turn_id"]
    lines = [r.getMessage() for r in caplog.records if r.name == service.__name__]
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith(f"chat sandbox={SB[:12]} turn={meta['turn_id']} ")
    assert "refused=- " in line and "top_sim=" in line and "model_ms=" in line
    assert "PTO" not in line and "20 days" not in line


def test_no_passages_refuses_no_support(seeded):
    c = ctx(seeded, answer=NeverCalledModel(), refusal_min_similarity=0.99)
    data = assert_refused(run(c, "zzqx vbnmw plokij"), "no_support")
    assert isinstance(data["closest"], list) and len(data["closest"]) <= 3
    rows = turns(seeded)
    assert [r["refused"] for r in rows] == [False, True]
    assert rows[1]["text"] == REFUSAL_TEXT


def test_closest_is_distinct_documents_in_rank_order(seeded, monkeypatch):
    def fake_search(*a, **kw):
        def p(doc: str, title: str, chunk: str) -> Passage:
            return Passage(
                chunk_id=chunk, document_id=doc, document_title=title,
                heading_path="", text="x", start=0, end=1, similarity=0.0,
                score=0.1, vector_rank=1, text_rank=None,
            )  # fmt: skip

        return [p("d1", "One", "c1"), p("d1", "One", "c2"), p("d2", "Two", "c3"),
                p("d3", "Three", "c4"), p("d4", "Four", "c5")]  # fmt: skip

    monkeypatch.setattr(service, "search", fake_search)
    c = ctx(seeded, answer=NeverCalledModel(), refusal_min_similarity=0.5)
    data = assert_refused(run(c), "no_support")
    assert data["closest"] == [
        {"document_id": "d1", "title": "One"},
        {"document_id": "d2", "title": "Two"},
        {"document_id": "d3", "title": "Three"},
    ]


def test_unknown_label_refuses_verification_failed(seeded):
    c = ctx(seeded, answer=ScriptedAnswerModel(["PTO is 20 days ", "[P9]"]))
    data = assert_refused(run(c), "verification_failed")
    assert data["closest"]
    assert data["closest"][0]["title"] == "Employee Handbook"


def test_no_answer_not_streamed(seeded):
    c = ctx(seeded, answer=ScriptedAnswerModel(["NO_", "ANS", "WER"]))
    events = run(c)
    assert [e.name for e in events if e.name == "delta"] == []
    assert_refused(events, "no_support")


def test_no_answer_prefix_then_text_is_flushed(seeded):
    model = ScriptedAnswerModel(["N", "O", "pe, 20 days ", "[P1]"])
    events = run(ctx(seeded, answer=model))
    deltas = [e.data["text"] for e in events if e.name == "delta"]
    assert deltas[0] == "NOpe, 20 days "
    assert "".join(deltas) == "NOpe, 20 days [P1]"
    assert events[-1].data["refused"] is False
    assert len(NO_ANSWER) == 9


def test_doc_deleted_during_stream_refuses(seeded):
    doc = handbook_id(seeded)

    def delete(i: int) -> None:
        if i == 1:
            assert delete_document(seeded, SB, doc).deleted

    model = ScriptedAnswerModel(
        ["PTO is 20 days ", "per year ", "[P1]"], on_delta=delete
    )
    events = run(ctx(seeded, answer=model))
    assert any(e.name == "delta" for e in events)
    assert_refused(events, "verification_failed")


def test_output_guardrail_block_refuses_blocked(seeded):
    g = ScriptedGuardrail(block="OUTPUT")
    assert_refused(run(ctx(seeded, guardrail=g)), "blocked")
    assert g.seen == ["INPUT", "OUTPUT"]
    assert [r["refused"] for r in turns(seeded)] == [False, True]


def test_input_guardrail_block_skips_model(seeded):
    g = ScriptedGuardrail(block="INPUT")
    emb = SpyEmbedder()
    c = ctx(seeded, guardrail=g, answer=NeverCalledModel(), embedder=emb)
    data = assert_refused(run(c), "blocked")
    assert data["closest"] == []
    assert emb.calls == 0
    assert g.seen == ["INPUT"]
    rows = turns(seeded)
    assert rows[0]["text"] == PTO and rows[1]["refused"] is True


@pytest.mark.parametrize("source", ["INPUT", "OUTPUT"])
def test_guardrail_unavailable_fails_closed(seeded, source):
    g = ScriptedGuardrail(fail=source)
    assert_refused(run(ctx(seeded, guardrail=g)), "model_unavailable")


def test_model_unavailable_refusal_is_persisted(seeded):
    model = ScriptedAnswerModel(["PTO is ", "20 days ", "[P1]"], fail_after=1)
    events = run(ctx(seeded, answer=model))
    assert_refused(events, "model_unavailable")
    rows = turns(seeded)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[1]["refused"] is True and rows[1]["text"] == REFUSAL_TEXT
    assert rows[1]["citations"] == []


def test_unexpected_exception_yields_error_and_persists_nothing(seeded, caplog):
    class Boom:
        def rewrite(self, history, question):
            raise RuntimeError("secret question text")

    caplog.set_level(logging.INFO)
    events = run(ctx(seeded, rewriter=Boom()))
    assert [e.name for e in events] == ["meta", "error"]
    assert events[-1].data == {"code": "internal_error"}
    assert turns(seeded) == []
    text = caplog.text
    assert "RuntimeError" in text
    assert "secret question text" not in text and "Traceback" not in text


def test_output_cap_stops_stream(seeded):
    model = ScriptedAnswerModel(["a" * 40, "b" * 40, "c" * 40, "[P1]"])
    events = run(ctx(seeded, answer=model, answer_max_chars=100))
    deltas = "".join(e.data["text"] for e in events if e.name == "delta")
    assert len(deltas) <= 100
    assert model.consumed == 3 and model.closed
    assert_refused(events, "verification_failed")


def test_closing_generator_closes_model_and_persists_nothing(seeded):
    model = ScriptedAnswerModel(["PTO is ", "20 days ", "per year ", "[P1]"])
    gen = run_chat(ctx(seeded, answer=model), SB, PTO)
    assert next(gen).name == "meta"
    assert next(gen).name == "delta"
    gen.close()
    assert model.closed
    assert turns(seeded) == []


def test_rewriter_receives_history_and_search_uses_rewrite(seeded, monkeypatch):
    run(ctx(seeded))
    seen: dict[str, Any] = {}

    class SpyRewriter:
        def rewrite(self, history, question):
            seen["history"] = list(history)
            seen["question"] = question
            return "rewritten PTO days query"

    real_search = service.search

    def spy_search(db, embedder, session_id, group_ids, query, **kw):
        seen["query"] = query
        seen["kw"] = kw
        seen["groups"] = list(group_ids)
        return real_search(db, embedder, session_id, group_ids, query, **kw)

    monkeypatch.setattr(service, "search", spy_search)
    run(ctx(seeded, rewriter=SpyRewriter()), "And how does it carry over?")
    assert seen["question"] == "And how does it carry over?"
    assert [m["role"] for m in seen["history"]] == ["user", "assistant"]
    assert seen["history"][0]["text"] == PTO
    assert seen["query"] == "rewritten PTO days query"
    assert seen["kw"] == {"k": 5, "candidates": 20}
    assert set(seen["groups"]) == {"larkspur", "engineering", "platform"}
    rows = turns(seeded)
    assert rows[2]["text"] == "And how does it carry over?"


def test_refusal_threshold_defaults_by_embedder():
    s = Settings(database_url="x", password_hash="x")
    assert s.refusal_min_similarity is None
    assert service.min_similarity(s, HashEmbedder()) == 0.05

    class Titan:
        id = "titan-v2-1024"

    assert service.min_similarity(s, Titan()) == 0.25  # type: ignore[arg-type]
    s2 = Settings(database_url="x", password_hash="x", refusal_min_similarity=0.4)
    assert service.min_similarity(s2, HashEmbedder()) == 0.4


def test_done_payload_is_json_serializable(seeded):
    events = run(ctx(seeded))
    json.dumps([e.data for e in events])


@pytest.mark.parametrize(
    "deltas",
    [["NO_ANSWER", "\n"], ["NO_ANSWER."], ["NO", "_ANSWER - not in docs"]],
)
def test_no_answer_with_trailing_text_never_streamed(seeded, deltas):
    events = run(ctx(seeded, answer=ScriptedAnswerModel(deltas)))
    assert [e for e in events if e.name == "delta"] == []
    assert_refused(events, "no_support")


def test_eager_model_unavailable_refuses(seeded):
    class EagerFail:
        def stream(self, messages):
            raise ModelUnavailable("model request failed")

    events = run(ctx(seeded, answer=EagerFail()))
    assert_refused(events, "model_unavailable")
    assert [r["refused"] for r in turns(seeded)] == [False, True]
