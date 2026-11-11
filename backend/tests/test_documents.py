import json
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from conftest import make_seed_doc, seed_org
from phoebe.documents import (
    EFFECTIVE_DOCUMENTS_SQL,
    DocumentPatch,
    DocumentSummary,
    NewDocument,
    SandboxFull,
    blob_key_for,
    create_document,
    delete_document,
    get_document,
    list_documents,
    mark_failed,
    mark_indexed,
    update_document,
)
from phoebe.groups import EFFECTIVE_GROUPS_SQL, create_group, delete_group


def new_doc(**overrides: Any) -> NewDocument:
    fields: dict[str, Any] = {
        "title": "Upload",
        "purpose": "",
        "last_updated": None,
        "doc_type": "markdown",
        "group_id": "platform",
        "source_uri": "seed://placeholder",
    }
    return NewDocument(**(fields | overrides))


def ids(docs: list[DocumentSummary]) -> list[str]:
    return [d.id for d in docs]


def test_visitor_doc_private(db):
    seed_org(db)
    d = create_document(db, "s1", new_doc(group_id="platform"))
    assert d in ids(list_documents(db, "s1"))
    assert d not in ids(list_documents(db, "s2"))


def test_move_seed_doc_per_session(db):
    seed_org(db)
    d = make_seed_doc(db, group_id="platform")
    update_document(db, "s1", d, DocumentPatch(group_id="sales-east"))
    visible = ["acme", "eng", "platform"]
    assert d not in ids(list_documents(db, "s1", group_ids=visible))
    assert d in ids(list_documents(db, "s2", group_ids=visible))
    moved = get_document(db, "s1", d)
    assert moved is not None
    assert (moved.group_id, moved.group_name) == ("sales-east", "Sales East")


def test_delete_seed_doc_hides(db):
    seed_org(db)
    d = make_seed_doc(db)
    result = delete_document(db, "s1", d)
    assert result.deleted and result.blob_key is None
    assert get_document(db, "s1", d) is None
    assert get_document(db, "s2", d) is not None


def test_cannot_touch_other_sessions_doc(db):
    seed_org(db)
    d = create_document(db, "s1", new_doc())
    assert update_document(db, "s2", d, DocumentPatch(title="x")) is False
    assert delete_document(db, "s2", d).deleted is False
    assert get_document(db, "s2", d) is None


def test_sandbox_cap(db):
    seed_org(db)
    for _ in range(20):
        create_document(db, "s1", new_doc())
    with pytest.raises(SandboxFull):
        create_document(db, "s1", new_doc())
    # Another session is unaffected.
    create_document(db, "s2", new_doc())


def test_mark_indexed_on_deleted_row_returns_false(db):
    seed_org(db)
    d = create_document(db, "s1", new_doc())
    delete_document(db, "s1", d)
    assert mark_indexed(db, d, "text", []) is False
    assert mark_failed(db, d, "boom") is False


def test_mark_indexed_and_failed(db):
    seed_org(db)
    d = create_document(db, "s1", new_doc())
    doc = get_document(db, "s1", d)
    assert doc is not None and doc.status == "processing" and doc.sections == []
    assert mark_failed(db, d, "bad pdf") is True
    failed = get_document(db, "s1", d)
    assert failed is not None
    assert (failed.status, failed.failure_reason) == ("failed", "bad pdf")
    sections = [{"heading": "Intro", "start": 0, "end": 4}]
    assert mark_indexed(db, d, "text", json.dumps(sections)) is True
    ok = get_document(db, "s1", d)
    assert ok is not None
    assert ok.status == "indexed" and ok.failure_reason is None
    assert ok.full_text == "text" and ok.sections == sections


def test_update_owned_in_place_and_patch_seed_fields(db):
    seed_org(db)
    owned = create_document(db, "s1", new_doc(title="Mine"))
    assert update_document(
        db,
        "s1",
        owned,
        DocumentPatch(title="Renamed", last_updated=date(2026, 1, 2), group_id="eng"),
    )
    got = get_document(db, "s1", owned)
    assert got is not None and got.owned
    assert (got.title, got.last_updated, got.group_id) == (
        "Renamed",
        date(2026, 1, 2),
        "eng",
    )
    seed = make_seed_doc(db, title="Seed")
    assert update_document(
        db, "s1", seed, DocumentPatch(title="Patched", last_updated=date(2026, 3, 4))
    )
    mine = get_document(db, "s1", seed)
    theirs = get_document(db, "s2", seed)
    assert mine is not None and theirs is not None
    assert (mine.title, mine.last_updated, mine.owned) == (
        "Patched",
        date(2026, 3, 4),
        False,
    )
    assert theirs.title == "Seed" and theirs.last_updated is None


def test_unknown_group_rejected(db):
    seed_org(db)
    with pytest.raises(ValueError):
        create_document(db, "s1", new_doc(group_id="nope"))
    d = create_document(db, "s1", new_doc())
    with pytest.raises(ValueError):
        update_document(db, "s1", d, DocumentPatch(group_id="nope"))
    seed = make_seed_doc(db)
    with pytest.raises(ValueError):
        update_document(db, "s1", seed, DocumentPatch(group_id="nope"))
    # a group hidden by this session is not effective
    delete_group(db, "s1", "payments")
    with pytest.raises(ValueError):
        create_document(db, "s1", new_doc(group_id="payments"))
    create_document(db, "s2", new_doc(group_id="payments"))


def test_session_owned_group_usable(db):
    seed_org(db)
    g = create_group(db, "s1", "Pod", "team", "eng")
    d = create_document(db, "s1", new_doc(group_id=g))
    got = get_document(db, "s1", d)
    assert got is not None and got.group_name == "Pod"


def test_non_uuid_ids_return_false_or_none(db):
    seed_org(db)
    assert get_document(db, "s1", "not-a-uuid") is None
    assert update_document(db, "s1", "not-a-uuid", DocumentPatch(title="x")) is False
    result = delete_document(db, "s1", "not-a-uuid")
    assert result.deleted is False and result.blob_key is None
    assert mark_indexed(db, "not-a-uuid", "t", []) is False
    assert mark_failed(db, "not-a-uuid", "r") is False


def test_blob_key_only_for_owned_blob_uploads(db):
    seed_org(db)
    up = create_document(db, "s1", new_doc())
    uri = f"blob://uploads/s1/{up}"
    db.execute(
        "update documents set source_uri = :u where id::text = :id",
        {"u": uri, "id": up},
    )
    result = delete_document(db, "s1", up)
    assert result.deleted and result.blob_key == f"uploads/s1/{up}"
    link = create_document(
        db, "s1", new_doc(doc_type="web", source_uri="https://example.com/x")
    )
    result = delete_document(db, "s1", link)
    assert result.deleted and result.blob_key is None


def test_moved_doc_visible_only_in_patching_session(db):
    seed_org(db)
    d = make_seed_doc(db, group_id="sales-east")
    update_document(db, "s1", d, DocumentPatch(group_id="eng"))
    assert get_document(db, "s1", d) is not None
    assert get_document(db, "s3", d) is not None


def test_effective_sql_embeddable_and_columns(db):
    seed_org(db)
    d = make_seed_doc(db)
    rows = db.fetch(
        f"""
        with eff_groups as ({EFFECTIVE_GROUPS_SQL}),
        eff_docs as ({EFFECTIVE_DOCUMENTS_SQL})
        select * from eff_docs where id::text = :id
        """,
        {"sid": "s1", "id": d},
    )
    assert len(rows) == 1
    assert set(rows[0]) == {
        "id", "session_id", "title", "purpose", "last_updated", "doc_type",
        "group_id", "status", "failure_reason", "source_uri", "public_url",
        "full_text", "sections", "owned",
    }  # fmt: skip


def test_validation():
    with pytest.raises(ValidationError):
        new_doc(title="")
    with pytest.raises(ValidationError):
        new_doc(title="x" * 201)
    with pytest.raises(ValidationError):
        new_doc(purpose="x" * 501)
    with pytest.raises(ValidationError):
        new_doc(doc_type="exe")


def test_foreign_blob_uri_rejected_on_create(db):
    seed_org(db)
    for uri in (
        "blob://uploads/s2/x",
        "blob://uploads/s1/",
        "blob://uploads/s1/../s2/x",
        "blob:///uploads/s1/x",
        "blob://other/s1/x",
    ):
        with pytest.raises(ValueError):
            create_document(db, "s1", new_doc(source_uri=uri))
    create_document(db, "s1", new_doc(source_uri="blob://uploads/s1/ok"))
    create_document(db, "s1", new_doc(doc_type="web", source_uri="https://e.com/a"))
    create_document(db, "s1", new_doc(source_uri="seed://x"))


def _raw_owned(db, sid: str, uri: str) -> str:
    rows = db.fetch(
        """
        insert into documents (session_id, title, doc_type, group_id, source_uri)
        values (:sid, 't', 'markdown', 'platform', :uri) returning id::text as id
        """,
        {"sid": sid, "uri": uri},
    )
    return rows[0]["id"]


def test_delete_never_returns_foreign_blob_key(db):
    seed_org(db)
    d = _raw_owned(db, "s1", "blob://uploads/s2/victim")
    result = delete_document(db, "s1", d)
    assert result.deleted is True and result.blob_key is None


def test_blob_key_traversal_rejected(db):
    seed_org(db)
    assert blob_key_for("s1", "blob://uploads/s1/../s2/x") is None
    assert blob_key_for("s1", "blob:///uploads/s1/x") is None
    assert blob_key_for("s1", "blob://uploads/s1/a\\b") is None
    assert blob_key_for("s1", "blob://uploads/s10/x") is None
    assert blob_key_for("s1", "https://x") is None
    assert blob_key_for("s1", "blob://uploads/s1/x") == "uploads/s1/x"
    d = _raw_owned(db, "s1", "blob://uploads/s1/../s2/x")
    assert delete_document(db, "s1", d).blob_key is None


def test_create_document_with_explicit_id(db):
    seed_org(db)
    chosen = "11111111-2222-3333-4444-555555555555"
    got = create_document(
        db,
        "s1",
        NewDocument(
            title="t",
            doc_type="markdown",
            group_id="platform",
            source_uri="blob://uploads/s1/" + chosen,
        ),
        doc_id=chosen,
    )
    assert got == chosen
