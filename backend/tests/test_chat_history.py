import pytest

from conftest import SEED_DIR
from phoebe.chat.history import WITHDRAWN, list_turns, recent
from phoebe.chat.models import ExtractiveAnswerModel, HeuristicRewriter, NoGuardrail
from phoebe.chat.service import ChatContext, run_chat
from phoebe.config import Settings
from phoebe.documents import delete_document
from phoebe.embed import HashEmbedder
from phoebe.groups import visible_group_ids
from phoebe.persona import get_persona
from phoebe.seed import load_seed

SB = "b" * 64
OTHER = "c" * 64
PTO = "How many PTO days do I get?"
MAX = Settings(database_url="x", password_hash="x").history_turn_max_chars


@pytest.fixture
def seeded(db):
    load_seed(db, HashEmbedder(), SEED_DIR)
    return db


def chat(db, question: str = PTO, sandbox: str = SB, **kw) -> dict:
    settings = Settings(database_url="postgresql://unused", password_hash="x", **kw)
    c = ChatContext(
        db=db,
        embedder=HashEmbedder(),
        answer=ExtractiveAnswerModel(),
        rewriter=HeuristicRewriter(),
        guardrail=NoGuardrail(),
        settings=settings,
    )
    return list(run_chat(c, sandbox, question))[-1].data


def groups(db, sandbox: str = SB) -> list[str]:
    return visible_group_ids(db, sandbox, get_persona(db).team_id)


def handbook_id(db) -> str:
    return db.fetch(
        "select id::text id from documents where title = 'Employee Handbook'"
    )[0]["id"]


def test_recent_returns_pairs_oldest_first(seeded):
    first = chat(seeded)
    chat(seeded, "What about sick days?")
    msgs = recent(seeded, SB, n=3, max_chars=MAX)
    assert [m["role"] for m in msgs] == ["user", "assistant"] * 2
    assert msgs[0]["text"] == PTO
    assert msgs[1]["text"] == first["text"]
    assert msgs[2]["text"] == "What about sick days?"
    last = recent(seeded, SB, n=1, max_chars=MAX)
    assert [m["text"] for m in last] == [msgs[2]["text"], msgs[3]["text"]]


def test_recent_truncates_turn_text(seeded):
    chat(seeded)
    msgs = recent(seeded, SB, n=3, max_chars=10)
    assert all(len(m["text"]) <= 10 for m in msgs)
    assert msgs[0]["text"] == PTO[:10]


def test_recent_drops_refused_pairs(seeded):
    chat(seeded, "zzqx vbnmw plokij", refusal_min_similarity=0.99)
    assert recent(seeded, SB, n=3, max_chars=MAX) == []
    assert len(list_turns(seeded, SB, groups(seeded))) == 2


def test_recent_returns_last_n_non_refused_pairs(seeded):
    chat(seeded, PTO)
    chat(seeded, "zzqx vbnmw plokij", refusal_min_similarity=0.99)
    chat(seeded, "zzqx again", refusal_min_similarity=0.99)
    msgs = recent(seeded, SB, n=1, max_chars=MAX)
    assert msgs[0]["text"] == PTO and len(msgs) == 2


def test_recent_withdraws_answer_with_removed_source(seeded):
    done = chat(seeded)
    assert done["refused"] is False
    assert recent(seeded, SB, n=3, max_chars=MAX)[1]["text"] == done["text"]
    delete_document(seeded, SB, handbook_id(seeded))
    msgs = recent(seeded, SB, n=3, max_chars=MAX)
    assert msgs[0]["text"] == PTO
    assert msgs[1]["text"] == WITHDRAWN
    assert WITHDRAWN == "(Earlier answer withdrawn: its source is no longer available.)"


def test_list_turns_marks_removed(seeded):
    done = chat(seeded)
    out = list_turns(seeded, SB, groups(seeded))
    assert [t.role for t in out] == ["user", "assistant"]
    assert out[1].text == done["text"] and out[1].refused is False
    assert out[1].citations and not any(c.removed for c in out[1].citations)
    assert out[1].citations[0].chunk_id == done["citations"][0]["chunk_id"]
    assert out[0].citations == []
    delete_document(seeded, SB, handbook_id(seeded))
    out = list_turns(seeded, SB, groups(seeded))
    assert all(c.removed for c in out[1].citations)
    dumped = out[1].model_dump(mode="json")
    assert set(dumped) == {"id", "role", "text", "refused", "created_at", "citations"}
    assert dumped["citations"][0]["removed"] is True


def test_history_is_per_sandbox(seeded):
    chat(seeded)
    assert recent(seeded, OTHER, n=3, max_chars=MAX) == []
    assert list_turns(seeded, OTHER, groups(seeded, OTHER)) == []
    # Deleting in one sandbox does not withdraw the answer in another.
    chat(seeded, sandbox=OTHER)
    delete_document(seeded, SB, handbook_id(seeded))
    assert recent(seeded, OTHER, n=3, max_chars=MAX)[1]["text"] != WITHDRAWN
    assert recent(seeded, SB, n=3, max_chars=MAX)[1]["text"] == WITHDRAWN


def test_recent_requires_max_chars(seeded):
    with pytest.raises(TypeError):
        recent(seeded, SB, n=3)  # type: ignore[call-arg]
