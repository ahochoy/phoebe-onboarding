import pytest

from phoebe.db import Database
from phoebe.embed import HashEmbedder
from phoebe.meta import EmbedderMismatch, check_embedder, record_embedder


class _Titan:
    id = "titan-v2-1024"

    def embed(self, texts):
        return [[0.0] for _ in texts]


def test_hash_embedder_id() -> None:
    assert HashEmbedder().id == "hash-v1-1024"


def test_check_embedder_passes_when_unset(db: Database) -> None:
    check_embedder(db, HashEmbedder())


def test_check_embedder_passes_when_same(db: Database) -> None:
    record_embedder(db, HashEmbedder())
    record_embedder(db, HashEmbedder())  # idempotent upsert
    check_embedder(db, HashEmbedder())


def test_check_embedder_raises_on_mismatch(db: Database) -> None:
    record_embedder(db, HashEmbedder())
    with pytest.raises(EmbedderMismatch) as ei:
        check_embedder(db, _Titan())
    assert ei.value.stored == "hash-v1-1024"
    assert ei.value.current == "titan-v2-1024"
