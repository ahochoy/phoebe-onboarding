"""Canonical sandbox-overlay CTE bodies, shared by groups, documents, tasks and
retrieval. Kept in one SQL-only module so those modules can all embed them
without importing each other.

Every body needs the `:sid` parameter (the sandbox id). Embed them as
`with eff_groups as (EFFECTIVE_GROUPS_SQL), eff_docs as (EFFECTIVE_DOCUMENTS_SQL),
eff_tasks as (EFFECTIVE_TASKS_SQL) ...`.
"""

# Columns: id, name, kind, parent_id, owned.
# A visitor's override can rename or hide a seed group, never re-parent it.
EFFECTIVE_GROUPS_SQL = """
select g.id, coalesce(o.patch->>'name', g.name) as name, g.kind, g.parent_id,
       false as owned
from groups g
left join overrides o
  on o.session_id = :sid and o.entity_kind = 'group' and o.entity_id = g.id
where g.session_id is null and not coalesce(o.hidden, false)
union all
select g.id, g.name, g.kind, g.parent_id, true as owned
from groups g
where g.session_id = :sid
"""

# This session's effective documents: seed documents not hidden by the
# session, with patch fields applied (including the patched group_id), plus
# documents the session owns.
#
# REQUIREMENT: embed after an `eff_groups` CTE. It references `eff_groups` by
# name and drops documents whose effective group is not effective for the
# session.
# Columns: id, session_id, title, purpose, last_updated, doc_type, group_id,
# status, failure_reason, source_uri, public_url, owned.
# `full_text` and `sections` are deliberately absent (they can be large); a
# detail query joins `documents` by id for them.
EFFECTIVE_DOCUMENTS_SQL = """
select d.id, d.session_id,
       coalesce(o.patch->>'title', d.title) as title,
       coalesce(o.patch->>'purpose', d.purpose) as purpose,
       coalesce((o.patch->>'last_updated')::date, d.last_updated) as last_updated,
       d.doc_type,
       coalesce(o.patch->>'group_id', d.group_id) as group_id,
       d.status, d.failure_reason, d.source_uri, d.public_url, false as owned
from documents d
left join overrides o
  on o.session_id = :sid and o.entity_kind = 'document' and o.entity_id = d.id::text
where d.session_id is null and not coalesce(o.hidden, false)
  and coalesce(o.patch->>'group_id', d.group_id) in (select id from eff_groups)
union all
select d.id, d.session_id, d.title, d.purpose, d.last_updated, d.doc_type,
       d.group_id, d.status, d.failure_reason, d.source_uri, d.public_url, true
from documents d
where d.session_id = :sid
  and d.group_id in (select id from eff_groups)
"""

# This session's effective tasks: seed tasks not hidden by the session with
# patch fields applied, plus owned tasks. Does not filter by eff_groups.
# Columns: id, title, description, link, group_id, position, owned.
EFFECTIVE_TASKS_SQL = """
select t.id,
       coalesce(o.patch->>'title', t.title) as title,
       coalesce(o.patch->>'description', t.description) as description,
       coalesce(o.patch->>'link', t.link) as link,
       coalesce(o.patch->>'group_id', t.group_id) as group_id,
       coalesce((o.patch->>'position')::int, t.position) as position,
       false as owned
from tasks t
left join overrides o
  on o.session_id = :sid and o.entity_kind = 'task' and o.entity_id = t.id::text
where t.session_id is null and not coalesce(o.hidden, false)
union all
select t.id, t.title, t.description, t.link, t.group_id, t.position, true
from tasks t
where t.session_id = :sid
"""
