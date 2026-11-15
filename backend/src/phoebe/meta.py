"""App-level metadata: which embedder built the stored vectors.

Vectors from different embedders are not comparable, so seeding and serving
must refuse to mix them.
"""

from phoebe.db import Database
from phoebe.embed import Embedder

_KEY = "embedder"


class EmbedderMismatch(Exception):
    def __init__(self, stored: str, current: str) -> None:
        super().__init__(f"stored embedder {stored!r} differs from {current!r}")
        self.stored = stored
        self.current = current


def check_embedder(db: Database, embedder: Embedder) -> None:
    rows = db.fetch("select value from app_meta where key = :k", {"k": _KEY})
    if rows and rows[0]["value"] != embedder.id:
        raise EmbedderMismatch(rows[0]["value"], embedder.id)


def record_embedder(db: Database, embedder: Embedder) -> None:
    db.execute(
        "insert into app_meta (key, value) values (:k, :v) "
        "on conflict (key) do update set value = excluded.value",
        {"k": _KEY, "v": embedder.id},
    )
