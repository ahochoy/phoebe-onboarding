import json
import re
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import CSRF, PW, SEED_DIR, _login
from phoebe.api import routes_chat
from phoebe.api.app import Deps, create_app, create_configured_app
from phoebe.auth import hash_password
from phoebe.chat.models import Message
from phoebe.config import Settings
from phoebe.control import InMemoryControlStore
from phoebe.db import PsycopgDatabase
from phoebe.embed import HashEmbedder
from phoebe.ingest.pipeline import index_document
from phoebe.jobs import InlineJobQueue
from phoebe.meta import EmbedderMismatch
from phoebe.seed import load_seed
from phoebe.sessions import InMemorySessionStore
from phoebe.storage import LocalBlobStore

PTO = "How many PTO days do I get?"
FRAME = re.compile(r"^event: (meta|delta|done|error)\ndata: \{.*\}$")


def chat(c: TestClient, body: object, headers: dict[str, str] | None = None):
    return c.post("/api/chat", json=body, headers=CSRF if headers is None else headers)


def frames(raw: str) -> list[str]:
    assert raw.endswith("\n\n"), raw
    return raw[:-2].split("\n\n")


def events(raw: str) -> list[tuple[str, dict]]:
    out = []
    for f in frames(raw):
        head, data = f.split("\n", 1)
        out.append((head.removeprefix("event: "), json.loads(data[len("data: ") :])))
    return out


def chat_turn_count(db: PsycopgDatabase) -> int:
    return db.fetch("select count(*) n from chat_turns")[0]["n"]


def make_client(db, tmp_path: Path, **kw) -> TestClient:
    blobs = LocalBlobStore(tmp_path / "blobs")
    embedder = HashEmbedder()
    settings = Settings(
        database_url="postgresql://unused",
        password_hash=hash_password(PW),
        cookie_secure=False,
        blob_dir=tmp_path / "blobs",
        seed_dir=SEED_DIR,
    )
    jobs = InlineJobQueue(
        lambda d: index_document(db, blobs, embedder, d, seed_root=settings.seed_dir)
    )
    deps = Deps(db, InMemorySessionStore(), blobs, embedder, jobs, settings, **kw)
    load_seed(db, embedder, settings.seed_dir)
    return TestClient(create_app(deps))


# ---- pre-stream checks ----------------------------------------------------


def test_chat_requires_csrf_and_session(client: TestClient) -> None:
    r = chat(client, {"question": PTO}, headers={})
    assert (r.status_code, r.json()) == (403, {"detail": "csrf_required"})
    r = chat(client, {"question": PTO})
    assert (r.status_code, r.json()) == (401, {"detail": "session_expired"})


def test_chat_rejects_extra_fields(seeded_client: TestClient) -> None:
    for body in (
        {"question": "x", "model": "y"},
        {"question": "x", "max_tokens": 5},
        {},
        {"question": 5},
        ["x"],
    ):
        r = chat(seeded_client, body)
        assert (r.status_code, r.json()) == (422, {"detail": "invalid_request"}), body


def test_chat_rejects_overlong_and_blank(seeded_client: TestClient) -> None:
    limit = seeded_client.app.state.deps.settings.question_max_chars  # type: ignore[attr-defined]
    for q in ("", "   ", "\n\t", "x" * (limit + 1), "x" * 5000):
        r = chat(seeded_client, {"question": q})
        assert (r.status_code, r.json()) == (422, {"detail": "invalid_request"}), q
        assert r.headers["content-type"].startswith("application/json")
    # Exactly at the limit is accepted (and stripped before counting).
    r = chat(seeded_client, {"question": "  " + "x" * limit + "  "})
    assert r.status_code == 200


def test_chat_rate_limited_before_stream(seeded_client: TestClient) -> None:
    for _ in range(30):
        r = chat(seeded_client, {"question": PTO})
        assert r.status_code == 200
    r = chat(seeded_client, {"question": PTO})
    assert (r.status_code, r.json()) == (429, {"detail": "session_chat_limit"})
    assert r.headers["content-type"].startswith("application/json")


def test_invalid_question_is_not_charged(seeded_client: TestClient) -> None:
    for _ in range(40):
        assert chat(seeded_client, {"question": " "}).status_code == 422
    assert chat(seeded_client, {"question": PTO}).status_code == 200


@pytest.mark.parametrize("state", ["chat_paused", "closed"])
def test_chat_paused_returns_503(db, tmp_path: Path, state) -> None:
    control = InMemoryControlStore()
    with make_client(db, tmp_path, control=control) as c:
        _login(c)
        control.set(state)  # type: ignore[arg-type]
        r = chat(c, {"question": PTO})
        code = "chat_paused" if state == "chat_paused" else "demo_closed"
        assert (r.status_code, r.json()) == (503, {"detail": code})
        assert r.headers["content-type"].startswith("application/json")
        # Paused is checked before body validation.
        r = chat(c, {"question": "x", "model": "y"})
        assert r.status_code == 503
    assert chat_turn_count(db) == 0


def test_paused_before_session_is_still_401(db, tmp_path: Path) -> None:
    with make_client(db, tmp_path, control=InMemoryControlStore("chat_paused")) as c:
        r = chat(c, {"question": PTO})
        assert (r.status_code, r.json()) == (401, {"detail": "session_expired"})


# ---- the stream -------------------------------------------------------------


def test_chat_stream_wire_format(seeded_client: TestClient) -> None:
    r = chat(seeded_client, {"question": PTO})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-accel-buffering"] == "no"
    fs = frames(r.text)
    for f in fs:
        assert FRAME.fullmatch(f), f
    evs = events(r.text)
    names = [n for n, _ in evs]
    assert names[0] == "meta"
    assert names.count("meta") == 1
    assert names[-1] in ("done", "error")
    assert sum(n in ("done", "error") for n in names) == 1
    assert set(names[1:-1]) <= {"delta"}
    assert set(evs[0][1]) == {"turn_id"}
    done = evs[-1][1]
    assert names[-1] == "done"
    assert set(done) == {"text", "refused", "reason", "citations", "closest"}
    assert done["refused"] is False and done["reason"] is None
    assert "20 days" in done["text"]
    assert done["citations"]
    assert set(done["citations"][0]) == {
        "n",
        "chunk_id",
        "document_id",
        "document_title",
        "heading_path",
        "start",
        "end",
    }
    for _, d in evs[1:-1]:
        assert set(d) == {"text"}


def test_stream_frames_never_contain_raw_newlines_in_data(db, tmp_path: Path) -> None:
    class Newlines:
        def stream(self, messages: Sequence[Message]) -> Iterator[str]:
            yield "line one\nline two\n\n"
            yield "NO_ANSWER"

    with make_client(db, tmp_path, answer=Newlines()) as c:
        _login(c)
        r = chat(c, {"question": PTO})
    for f in frames(r.text):
        assert FRAME.fullmatch(f), f
    assert "line one\nline two" in "".join(
        d["text"] for n, d in events(r.text) if n == "delta"
    )


def test_client_disconnect_persists_nothing(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_closed = threading.Event()
    chat_closed = threading.Event()

    class Endless:
        def stream(self, messages: Sequence[Message]) -> Iterator[str]:
            try:
                while True:
                    yield "word "
            finally:
                model_closed.set()

    real = routes_chat.run_chat

    def spy(*a, **k):
        gen = real(*a, **k)
        try:
            yield from gen
        finally:
            chat_closed.set()

    monkeypatch.setattr(routes_chat, "run_chat", spy)
    with make_client(db, tmp_path, answer=Endless()) as c:
        _login(c)
        with c.stream("POST", "/api/chat", json={"question": PTO}, headers=CSRF) as r:
            assert r.status_code == 200
            first = next(r.iter_text())
            assert first.startswith("event: meta\n")
        assert chat_closed.wait(5), "run_chat generator was not closed"
        assert model_closed.wait(5), "model stream was not closed"
    assert chat_turn_count(db) == 0


# ---- history ---------------------------------------------------------------


def test_history_requires_session(client: TestClient) -> None:
    r = client.get("/api/chat/history")
    assert (r.status_code, r.json()) == (401, {"detail": "session_expired"})


def test_history_after_chat(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/chat/history").json() == []
    r = chat(seeded_client, {"question": PTO})
    done = events(r.text)[-1][1]
    turn_id = events(r.text)[0][1]["turn_id"]
    h = seeded_client.get("/api/chat/history")
    assert h.status_code == 200
    turns = h.json()
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["text"] == PTO
    assert turns[1]["id"] == turn_id
    assert turns[1]["text"] == done["text"]
    assert turns[1]["refused"] is False
    assert turns[1]["citations"]
    assert all(c["removed"] is False for c in turns[1]["citations"])


def test_history_is_per_session(
    seeded_client: TestClient, second_client: TestClient
) -> None:
    chat(seeded_client, {"question": PTO})
    assert second_client.get("/api/chat/history").json() == []


def test_history_marks_removed_after_delete(seeded_client: TestClient) -> None:
    r = chat(seeded_client, {"question": PTO})
    doc_id = events(r.text)[-1][1]["citations"][0]["document_id"]
    d = seeded_client.delete(f"/api/documents/{doc_id}", headers=CSRF)
    assert d.status_code == 204
    turns = seeded_client.get("/api/chat/history").json()
    cits = turns[1]["citations"]
    assert cits and all(c["removed"] is True for c in cits)


def test_reset_clears_history(seeded_client: TestClient) -> None:
    chat(seeded_client, {"question": PTO})
    assert seeded_client.get("/api/chat/history").json()
    assert seeded_client.post("/api/reset", headers=CSRF).status_code == 204
    _login(seeded_client)
    assert seeded_client.get("/api/chat/history").json() == []


# ---- wiring ------------------------------------------------------------------


def _configured_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import os

    url = os.environ["PHOEBE_TEST_DATABASE_URL"]
    for key in list(os.environ):
        if key.startswith("PHOEBE_") and key != "PHOEBE_TEST_DATABASE_URL":
            monkeypatch.delenv(key)
    monkeypatch.setenv("PHOEBE_DATABASE_URL", url)
    monkeypatch.setenv("PHOEBE_PASSWORD_HASH", hash_password(PW))
    monkeypatch.setenv("PHOEBE_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("PHOEBE_CONTROL_FILE", str(tmp_path / "control.json"))
    monkeypatch.setenv("PHOEBE_SEED_DIR", str(SEED_DIR))


def test_configured_app_refuses_embedder_mismatch(
    db, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Lazy: the app builds; the first DB-using request returns 503.
    _configured_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PHOEBE_COOKIE_SECURE", "false")  # TestClient is plain http
    db.execute("insert into app_meta (key, value) values ('embedder', 'titan-v2-1024')")
    app = create_configured_app()
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        _login(c)
        r = c.get("/api/documents?scope=all")
        assert r.status_code == 503
        assert r.json() == {"detail": "embedder_mismatch"}
        # Not cached as a failure: fixing the index heals without a redeploy.
        db.execute("update app_meta set value = 'hash-v1-1024' where key = 'embedder'")
        assert c.get("/api/documents?scope=all").status_code == 200


def test_configured_app_wires_offline_defaults(
    db, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from phoebe.chat.models import ExtractiveAnswerModel, HeuristicRewriter, NoGuardrail

    _configured_env(monkeypatch, tmp_path)
    db.execute("insert into app_meta (key, value) values ('embedder', 'hash-v1-1024')")
    app = create_configured_app()
    with TestClient(app):
        deps: Deps = app.state.deps
        assert isinstance(deps.answer, ExtractiveAnswerModel)
        assert isinstance(deps.rewriter, HeuristicRewriter)
        assert isinstance(deps.guardrail, NoGuardrail)


def test_startup_check_tolerates_unmigrated_db() -> None:
    """`make stack` boots the API before `migrate`: no app_meta table is no mismatch."""
    from phoebe.api.app import startup_check_embedder

    class Unmigrated:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def fetch(self, sql, params=None):
            self.sql.append(sql)
            assert "to_regclass" in sql, "must not query app_meta before it exists"
            return [{"t": None}]

    fake = Unmigrated()
    startup_check_embedder(fake, HashEmbedder())  # type: ignore[arg-type]
    assert len(fake.sql) == 1


def test_startup_check_raises_on_mismatch(db) -> None:
    from phoebe.api.app import startup_check_embedder

    startup_check_embedder(db, HashEmbedder())  # nothing recorded yet
    db.execute("insert into app_meta (key, value) values ('embedder', 'titan-v2-1024')")
    with pytest.raises(EmbedderMismatch):
        startup_check_embedder(db, HashEmbedder())


# ---- visibility ----------------------------------------------------------------


def _alex_visible(c: TestClient) -> set[str]:
    from phoebe.api.routes_portal import alex_groups
    from phoebe.sessions import sandbox_id

    class _Req:
        app = c.app

    sid = sandbox_id(c.cookies["phoebe_session"])
    return set(alex_groups(_Req(), sid))  # type: ignore[arg-type]


def _done_doc_ids(raw: str) -> tuple[list[str], list[str]]:
    name, done = events(raw)[-1]
    assert name == "done"
    return (
        [c["document_id"] for c in done["citations"]],
        [d["document_id"] for d in done["closest"]],
    )


def _doc_id(db: PsycopgDatabase, title: str) -> str:
    return db.fetch(
        "select id::text id from documents where title = :t and session_id is null",
        {"t": title},
    )[0]["id"]


OUTSIDE_QUESTIONS = (
    (
        "Who is the team lead for Sales East, and which states does the East"
        " territory cover?"
    ),
    (
        "How do I handle a settlement mismatch alert from the settlement worker"
        " against the Meridian Pay processor report?"
    ),
)


@pytest.mark.parametrize("question", OUTSIDE_QUESTIONS)
def test_chat_never_cites_outside_groups(
    db: PsycopgDatabase, seeded_client: TestClient, question: str
) -> None:
    visible = _alex_visible(seeded_client)
    assert visible and not visible & {"sales", "sales-east", "payments"}
    r = chat(seeded_client, {"question": question})
    cited, closest = _done_doc_ids(r.text)
    ids = sorted(set(cited) | set(closest))
    if ids:
        rows = db.fetch(
            "select id::text id, group_id from documents where id::text = any(:ids)",
            {"ids": ids},
        )
        assert len(rows) == len(ids)
        outside = [row for row in rows if row["group_id"] not in visible]
        assert outside == []
    for title in ("East Territory Notes", "Sales Playbook", "Payments Runbook"):
        assert _doc_id(db, title) not in ids, title


def test_chat_stops_citing_doc_moved_outside_groups(
    db: PsycopgDatabase, seeded_client: TestClient
) -> None:
    q = "Who is Jordan Moore, my onboarding buddy on the Platform team?"
    doc = _doc_id(db, "Team Breakdown")
    cited, _ = _done_doc_ids(chat(seeded_client, {"question": q}).text)
    assert doc in cited  # visible: it answers the question
    r = seeded_client.patch(
        f"/api/documents/{doc}", json={"group_id": "sales"}, headers=CSRF
    )
    assert r.status_code == 204
    cited, closest = _done_doc_ids(chat(seeded_client, {"question": q}).text)
    assert doc not in cited and doc not in closest


def test_chat_stops_citing_deleted_doc(
    db: PsycopgDatabase, seeded_client: TestClient
) -> None:
    q = "How many PTO days do I get?"
    doc = _doc_id(db, "Employee Handbook")
    cited, _ = _done_doc_ids(chat(seeded_client, {"question": q}).text)
    assert doc in cited  # it answers the question before the delete
    r = seeded_client.delete(f"/api/documents/{doc}", headers=CSRF)
    assert r.status_code == 204
    # A fresh question, with no history, neither cites nor offers it.
    cited, closest = _done_doc_ids(chat(seeded_client, {"question": q}).text)
    assert doc not in cited and doc not in closest


@pytest.mark.parametrize("value", [0, 4001])
def test_question_max_chars_is_bounded(value: int) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(database_url="x", password_hash="x", question_max_chars=value)


def test_question_max_chars_within_body_cap() -> None:
    from phoebe.api.routes_chat import _QUESTION_HARD_CAP

    field = Settings.model_fields["question_max_chars"]
    le = next(m.le for m in field.metadata if getattr(m, "le", None) is not None)
    assert le <= _QUESTION_HARD_CAP
    assert Settings(database_url="x", password_hash="x", question_max_chars=4000)
