from pathlib import Path

from phoebe.db import Database
from phoebe.documents import list_documents
from phoebe.embed import HashEmbedder
from phoebe.groups import visible_group_ids
from phoebe.retrieve import search
from phoebe.seed import load_seed
from phoebe.tasks import PersonProgress, progress

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"


def by_id(rows: list[PersonProgress], person_id: str) -> PersonProgress:
    return next(r for r in rows if r.person_id == person_id)


def alex_groups(db: Database) -> list[str]:
    return visible_group_ids(db, "s1", "platform")


def test_seed_loads_and_is_idempotent(db: Database) -> None:
    r1 = load_seed(db, HashEmbedder(), SEED_DIR)
    r2 = load_seed(db, HashEmbedder(), SEED_DIR)
    assert r1 == r2 and r1.documents == 12 and r1.chunks > 12
    assert (r1.groups, r1.people, r1.tasks) == (6, 3, 21)


def test_alex_progress_seeded(db: Database) -> None:
    load_seed(db, HashEmbedder(), SEED_DIR)
    rows = progress(db, "s1")
    alex = by_id(rows, "alex-rivera")
    assert (alex.done, alex.total) == (6, 14)
    sam = by_id(rows, "sam-chen")
    assert (sam.done, sam.total) == (12, 13)
    priya = by_id(rows, "priya-n")
    assert (priya.done, priya.total) == (0, 10)


def test_all_seed_docs_indexed(db: Database) -> None:
    load_seed(db, HashEmbedder(), SEED_DIR)
    assert {d.status for d in list_documents(db, "s1")} == {"indexed"}


def test_every_seed_doc_has_chunks(db: Database) -> None:
    load_seed(db, HashEmbedder(), SEED_DIR)
    rows = db.fetch(
        """
        select d.title from documents d
        where d.session_id is null
          and not exists (select 1 from chunks c where c.document_id = d.id)
        """
    )
    assert rows == []


def test_alex_sees_nine_documents(db: Database) -> None:
    load_seed(db, HashEmbedder(), SEED_DIR)
    docs = list_documents(db, "s1", group_ids=alex_groups(db))
    by_group: dict[str, int] = {}
    for d in docs:
        by_group[d.group_id] = by_group.get(d.group_id, 0) + 1
    assert by_group == {"larkspur": 4, "engineering": 2, "platform": 3}
    assert len(docs) == 9


def test_public_url_on_web_and_google_docs(db: Database) -> None:
    load_seed(db, HashEmbedder(), SEED_DIR)
    docs = {d.doc_type: d for d in list_documents(db, "s1")}
    assert docs["web"].public_url and docs["google_doc"].public_url
    assert docs["markdown"].public_url is None


def test_pto_answerable_for_alex(db: Database) -> None:
    load_seed(db, HashEmbedder(), SEED_DIR)
    hits = search(db, HashEmbedder(), "s1", alex_groups(db), "PTO days per year")
    assert any("20 days" in p.text for p in hits)


def test_payments_runbook_not_visible_to_alex(db: Database) -> None:
    load_seed(db, HashEmbedder(), SEED_DIR)
    hits = search(
        db, HashEmbedder(), "s1", alex_groups(db), "payments runbook settlement"
    )
    assert all("Payments Runbook" != p.document_title for p in hits)
