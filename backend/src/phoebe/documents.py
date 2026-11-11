import json
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from phoebe.db import Database
from phoebe.groups import EFFECTIVE_GROUPS_SQL
from phoebe.sandbox import EntityKind, blob_key_for, hide, patch

DocType = Literal["pdf", "markdown", "csv", "web", "google_doc"]
DocStatus = Literal["processing", "indexed", "failed"]

MAX_OWNED_DOCUMENTS = 20
_BLOB_PREFIX = "blob://"

__all__ = ["blob_key_for"]  # defined in sandbox (shared with reset_session)


class SandboxFull(Exception):
    """The session already owns the maximum number of documents."""


class NewDocument(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(default="", max_length=500)
    last_updated: date | None = None
    doc_type: DocType
    group_id: str
    source_uri: str
    public_url: str | None = None


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = Field(default=None, max_length=500)
    last_updated: date | None = None
    group_id: str | None = None


class DocumentSummary(BaseModel):
    id: str
    title: str
    purpose: str
    last_updated: date | None
    doc_type: DocType
    group_id: str
    group_name: str
    group_kind: str
    status: DocStatus
    failure_reason: str | None
    source_uri: str
    public_url: str | None
    owned: bool


class DocumentDetail(DocumentSummary):
    full_text: str | None
    sections: list[dict[str, Any]]


class DeleteResult(BaseModel):
    deleted: bool
    blob_key: str | None = None


# CTE body (needs :sid) listing this session's effective documents: seed
# documents not hidden by the session, with patch fields applied (including the
# patched group_id), plus documents the session owns.
#
# REQUIREMENT: this must be embedded after an `eff_groups` CTE, e.g.
#   with eff_groups as (<EFFECTIVE_GROUPS_SQL>), eff_docs as (<EFFECTIVE_DOCUMENTS_SQL>)
# It references `eff_groups` by name and drops documents whose effective group
# is not an effective group for the session.
# Columns: id, session_id, title, purpose, last_updated, doc_type, group_id,
# status, failure_reason, source_uri, public_url, full_text, sections, owned.
EFFECTIVE_DOCUMENTS_SQL = """
select d.id, d.session_id,
       coalesce(o.patch->>'title', d.title) as title,
       coalesce(o.patch->>'purpose', d.purpose) as purpose,
       coalesce((o.patch->>'last_updated')::date, d.last_updated) as last_updated,
       d.doc_type,
       coalesce(o.patch->>'group_id', d.group_id) as group_id,
       d.status, d.failure_reason, d.source_uri, d.public_url, d.full_text,
       d.sections, false as owned
from documents d
left join overrides o
  on o.session_id = :sid and o.entity_kind = 'document' and o.entity_id = d.id::text
where d.session_id is null and not coalesce(o.hidden, false)
  and coalesce(o.patch->>'group_id', d.group_id) in (select id from eff_groups)
union all
select d.id, d.session_id, d.title, d.purpose, d.last_updated, d.doc_type,
       d.group_id, d.status, d.failure_reason, d.source_uri, d.public_url,
       d.full_text, d.sections, true
from documents d
where d.session_id = :sid
  and d.group_id in (select id from eff_groups)
"""

_SELECT_EFFECTIVE = f"""
with eff_groups as ({EFFECTIVE_GROUPS_SQL}),
eff_docs as ({EFFECTIVE_DOCUMENTS_SQL})
select ed.id::text as id, ed.title, ed.purpose, ed.last_updated, ed.doc_type,
       ed.group_id, g.name as group_name, g.kind as group_kind, ed.status,
       ed.failure_reason, ed.source_uri, ed.public_url, ed.owned,
       ed.full_text, coalesce(ed.sections, '[]'::jsonb) as sections
from eff_docs ed
join eff_groups g on g.id = ed.group_id
"""

_ORDER = "order by g.kind, ed.title, ed.id"


def _effective_group_ids(db: Database, session_id: str) -> set[str]:
    rows = db.fetch(
        f"with eff_groups as ({EFFECTIVE_GROUPS_SQL}) select id from eff_groups",
        {"sid": session_id},
    )
    return {r["id"] for r in rows}


def list_documents(
    db: Database, session_id: str, *, group_ids: list[str] | None = None
) -> list[DocumentSummary]:
    """Effective documents; `group_ids=None` means no group filter."""
    rows = db.fetch(
        f"""
        {_SELECT_EFFECTIVE}
        where (:gids::text[] is null or ed.group_id = any(:gids::text[]))
        {_ORDER}
        """,
        {"sid": session_id, "gids": group_ids},
    )
    return [DocumentSummary(**r) for r in rows]


def get_document(db: Database, session_id: str, doc_id: str) -> DocumentDetail | None:
    rows = db.fetch(
        f"{_SELECT_EFFECTIVE} where ed.id::text = :id",
        {"sid": session_id, "id": doc_id},
    )
    return DocumentDetail(**rows[0]) if rows else None


def _owned_count(db: Database, session_id: str) -> int:
    rows = db.fetch(
        "select count(*) as n from documents where session_id = :sid",
        {"sid": session_id},
    )
    return int(rows[0]["n"])


def create_document(
    db: Database, session_id: str, doc: NewDocument, *, doc_id: str | None = None
) -> str:
    """Insert an owned document. `doc_id` (a UUID string) lets the caller pick the
    id up front, e.g. so an upload's blob key can match it."""
    if doc.group_id not in _effective_group_ids(db, session_id):
        raise ValueError(f"unknown group {doc.group_id}")
    if doc.source_uri.startswith(_BLOB_PREFIX) and (
        blob_key_for(session_id, doc.source_uri) is None
    ):
        raise ValueError("blob source_uri must be inside this session's uploads")
    if _owned_count(db, session_id) >= MAX_OWNED_DOCUMENTS:
        raise SandboxFull(session_id)
    rows = db.fetch(
        """
        insert into documents
          (id, session_id, title, purpose, last_updated, doc_type, group_id,
           source_uri, public_url)
        values
          (coalesce(:doc_id::uuid, gen_random_uuid()), :sid, :title, :purpose,
           :last_updated, :doc_type, :group_id, :source_uri, :public_url)
        returning id::text as id
        """,
        {"sid": session_id, "doc_id": doc_id, **doc.model_dump()},
    )
    return rows[0]["id"]


def _owned_row(db: Database, session_id: str, doc_id: str) -> dict[str, Any] | None:
    rows = db.fetch(
        "select source_uri from documents where id::text = :id and session_id = :sid",
        {"sid": session_id, "id": doc_id},
    )
    return rows[0] if rows else None


def _visible_seed_document(db: Database, session_id: str, doc_id: str) -> bool:
    """True if `doc_id` is a seed document this session has not hidden."""
    return bool(
        db.fetch(
            """
            select 1 from documents d
            left join overrides o
              on o.session_id = :sid and o.entity_kind = 'document'
             and o.entity_id = d.id::text
            where d.id::text = :id and d.session_id is null
              and not coalesce(o.hidden, false)
            """,
            {"sid": session_id, "id": doc_id},
        )
    )


def update_document(
    db: Database, session_id: str, doc_id: str, changes: DocumentPatch
) -> bool:
    fields = changes.model_dump(exclude_none=True)
    owned = _owned_row(db, session_id, doc_id) is not None
    if not owned and not _visible_seed_document(db, session_id, doc_id):
        return False
    if "group_id" in fields and fields["group_id"] not in _effective_group_ids(
        db, session_id
    ):
        raise ValueError(f"unknown group {fields['group_id']}")
    if not fields:
        return True
    if owned:
        sets = ", ".join(f"{name} = :{name}" for name in fields)
        db.execute(
            f"update documents set {sets} where id::text = :id and session_id = :sid",
            {**fields, "id": doc_id, "sid": session_id},
        )
    else:
        json_fields = changes.model_dump(exclude_none=True, mode="json")
        patch(db, session_id, EntityKind.DOCUMENT, doc_id, json_fields)
    return True


def delete_document(db: Database, session_id: str, doc_id: str) -> DeleteResult:
    row = _owned_row(db, session_id, doc_id)
    if row is not None:
        db.execute(
            "delete from documents where id::text = :id and session_id = :sid",
            {"id": doc_id, "sid": session_id},
        )
        uri: str = row["source_uri"]
        return DeleteResult(deleted=True, blob_key=blob_key_for(session_id, uri))
    if _visible_seed_document(db, session_id, doc_id):
        hide(db, session_id, EntityKind.DOCUMENT, doc_id)
        return DeleteResult(deleted=True)
    return DeleteResult(deleted=False)


def mark_indexed(
    db: Database,
    doc_id: str,
    full_text: str,
    sections: str | list[dict[str, Any]],
) -> bool:
    """Indexing worker hook: no session involved. False if the row is gone."""
    payload = sections if isinstance(sections, str) else json.dumps(sections)
    return (
        db.execute(
            """
            update documents
            set status = 'indexed', full_text = :text,
                sections = :sections::jsonb, failure_reason = null
            where id::text = :id
            """,
            {"id": doc_id, "text": full_text, "sections": payload},
        )
        > 0
    )


def mark_failed(db: Database, doc_id: str, reason: str) -> bool:
    return (
        db.execute(
            """
            update documents set status = 'failed', failure_reason = :reason
            where id::text = :id
            """,
            {"id": doc_id, "reason": reason},
        )
        > 0
    )
