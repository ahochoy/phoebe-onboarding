import pytest

from conftest import ALEX, index_seed_text, seed_org
from phoebe.documents import DocumentPatch, mark_failed, update_document
from phoebe.embed import HashEmbedder
from phoebe.retrieve import search


def test_finds_pto(db):
    seed_org(db)
    index_seed_text(db, "acme", b"# Leave\nPTO is 20 days per year.\n")
    r = search(db, HashEmbedder(), "s1", ALEX, "how many PTO days")
    assert r and "20 days" in r[0].text
    assert r[0].score > 0 and (r[0].vector_rank or r[0].text_rank)


def test_special_chars_query(db):
    seed_org(db)
    index_seed_text(db, "acme", b"# 401k\nMatch is 4%.\n")
    search(db, HashEmbedder(), "s1", ["acme"], "401(k) & PTO!")
    search(db, HashEmbedder(), "s1", ["acme"], "'; drop table chunks; --")
    assert db.fetch("select count(*) n from chunks")[0]["n"] > 0


def test_moved_seed_doc_leaves_search(db):
    seed_org(db)
    d = index_seed_text(db, "platform", b"# Oncall\nPager rotation weekly.\n")
    update_document(db, "s1", d, DocumentPatch(group_id="sales-east"))
    assert search(db, HashEmbedder(), "s1", ALEX, "pager rotation") == []
    assert search(db, HashEmbedder(), "s2", ALEX, "pager rotation")


def test_failed_document_chunks_not_served(db):
    seed_org(db)
    d = index_seed_text(db, "acme", b"# Leave\nPTO is 20 days per year.\n")
    assert search(db, HashEmbedder(), "s1", ALEX, "PTO days")
    mark_failed(db, d, "Indexing error")
    assert db.fetch("select count(*) n from chunks")[0]["n"] > 0
    assert search(db, HashEmbedder(), "s1", ALEX, "PTO days") == []


def test_empty_group_ids_returns_empty(db):
    seed_org(db)
    index_seed_text(db, "acme", b"# Leave\nPTO is 20 days.\n")
    assert search(db, HashEmbedder(), "s1", [], "PTO") == []


@pytest.mark.parametrize("query", ["", "   \n"])
def test_empty_query_raises(db, query):
    with pytest.raises(ValueError):
        search(db, HashEmbedder(), "s1", ALEX, query)


@pytest.mark.parametrize(
    "kw", [{"k": 0}, {"k": 21}, {"candidates": 0}, {"candidates": 101}]
)
def test_bounds_validated(db, kw):
    with pytest.raises(ValueError):
        search(db, HashEmbedder(), "s1", ALEX, "pto", **kw)


def test_k_limits_results_and_order_is_deterministic(db):
    seed_org(db)
    for i in range(8):
        index_seed_text(db, "acme", f"# Doc{i}\nshared handbook words {i}\n".encode())
    r1 = search(db, HashEmbedder(), "s1", ALEX, "shared handbook", k=3)
    r2 = search(db, HashEmbedder(), "s1", ALEX, "shared handbook", k=3)
    assert len(r1) == 3
    assert [p.chunk_id for p in r1] == [p.chunk_id for p in r2]
    assert [p.score for p in r1] == sorted((p.score for p in r1), reverse=True)


def test_logs_do_not_contain_query(db, caplog):
    seed_org(db)
    index_seed_text(db, "acme", b"# Leave\nPTO is 20 days.\n")
    with caplog.at_level("DEBUG"):
        search(db, HashEmbedder(), "s1", ALEX, "secretquerytext")
    assert "secretquerytext" not in caplog.text
