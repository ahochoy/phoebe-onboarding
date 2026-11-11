"""Hybrid retrieval: vector + full-text, fused with reciprocal rank fusion.

The visibility filter (effective documents, indexed only, allowed groups) is in
the same SQL statement as the ranking. Logs carry the session hash, chunk ids,
count and timing only, never the query or any text.
"""

import logging
import time
from collections.abc import Sequence

from pydantic import BaseModel

from phoebe.db import Database
from phoebe.embed import Embedder, vector_literal
from phoebe.overlay_sql import EFFECTIVE_DOCUMENTS_SQL, EFFECTIVE_GROUPS_SQL
from phoebe.sessions import session_hash

log = logging.getLogger(__name__)

MAX_K = 20
MAX_CANDIDATES = 100

_SEARCH_SQL = f"""
with eff_groups as ({EFFECTIVE_GROUPS_SQL}),
eff as ({EFFECTIVE_DOCUMENTS_SQL}),
visible as (
  select id, title from eff
  where status = 'indexed' and group_id = any(:groups::text[])
),
v as (
  select c.id, row_number() over (order by c.embedding <=> :qvec::vector, c.id) r
  from chunks c join visible d on d.id = c.document_id
  order by c.embedding <=> :qvec::vector, c.id limit :n
),
t as (
  select c.id, row_number() over (order by ts_rank_cd(c.tsv, q) desc, c.id) r
  from chunks c join visible d on d.id = c.document_id,
       websearch_to_tsquery('english', :q) q
  where c.tsv @@ q order by ts_rank_cd(c.tsv, q) desc, c.id limit :n
),
fused as (
  select coalesce(v.id, t.id) id,
         coalesce(1.0/(60+v.r), 0) + coalesce(1.0/(60+t.r), 0) score,
         v.r vr, t.r tr
  from v full outer join t on v.id = t.id
)
select c.id::text chunk_id, c.document_id::text document_id, d.title document_title,
       c.heading_path, c.text, c.start_offset start, c.end_offset "end",
       f.score::float8 score, f.vr::int vector_rank, f.tr::int text_rank
from fused f
join chunks c on c.id = f.id
join visible d on d.id = c.document_id
order by f.score desc, c.id
limit :k
"""


class Passage(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    heading_path: str
    text: str
    start: int
    end: int
    score: float
    vector_rank: int | None
    text_rank: int | None


def search(
    db: Database,
    embedder: Embedder,
    session_id: str,
    group_ids: Sequence[str],
    query: str,
    *,
    k: int = 5,
    candidates: int = 20,
) -> list[Passage]:
    query = query.strip()
    if not query:
        raise ValueError("empty query")
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be between 1 and {MAX_K}")
    if not 1 <= candidates <= MAX_CANDIDATES:
        raise ValueError(f"candidates must be between 1 and {MAX_CANDIDATES}")
    if not group_ids:
        return []
    started = time.monotonic()
    qvec = embedder.embed([query])[0]
    rows = db.fetch(
        _SEARCH_SQL,
        {
            "sid": session_id,
            "groups": list(group_ids),
            "qvec": vector_literal(qvec),
            "q": query,
            "n": candidates,
            "k": k,
        },
    )
    passages = [Passage(**r) for r in rows]
    log.info(
        "search session=%s count=%d chunks=%s ms=%d",
        session_hash(session_id),
        len(passages),
        [p.chunk_id for p in passages],
        int((time.monotonic() - started) * 1000),
    )
    return passages
