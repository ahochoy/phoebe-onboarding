import pytest

from phoebe.embed import EMBED_DIM, HashEmbedder
from phoebe.jobs import InlineJobQueue
from phoebe.storage import LocalBlobStore


def test_hash_embedder_deterministic_and_normalized():
    a, b = HashEmbedder().embed(["PTO policy", "PTO policy"])
    assert a == b
    assert abs(sum(x * x for x in a) - 1) < 1e-9
    assert len(a) == EMBED_DIM


def test_hash_embedder_empty_text_gets_unit_vector():
    (v,) = HashEmbedder().embed(["!!! ???"])
    assert v[0] == 1.0 and sum(x * x for x in v) == 1.0


def test_hash_embedder_similar_texts_closer_than_unrelated():
    a, b, c = HashEmbedder().embed(
        ["vacation policy days", "vacation days policy", "kubernetes cluster upgrade"]
    )

    def dot(x: list[float], y: list[float]) -> float:
        return sum(i * j for i, j in zip(x, y, strict=True))

    assert dot(a, b) > dot(a, c)


def test_blob_key_traversal_rejected(tmp_path):
    with pytest.raises(ValueError):
        LocalBlobStore(tmp_path).put("../x", b"")


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a\\b", "..", "a/.."])
def test_blob_bad_keys_rejected(tmp_path, key):
    store = LocalBlobStore(tmp_path)
    with pytest.raises(ValueError):
        store.put(key, b"x")
    with pytest.raises(ValueError):
        store.get(key)
    with pytest.raises(ValueError):
        store.delete(key)


def test_blob_roundtrip_and_delete(tmp_path):
    store = LocalBlobStore(tmp_path / "root")
    store.put("uploads/s1/x", b"hello")
    assert store.get("uploads/s1/x") == b"hello"
    store.delete("uploads/s1/x")
    with pytest.raises(KeyError):
        store.get("uploads/s1/x")
    store.delete("uploads/s1/x")  # idempotent


def test_blob_get_missing_raises_keyerror(tmp_path):
    with pytest.raises(KeyError):
        LocalBlobStore(tmp_path).get("nope/x")


def test_inline_job_queue_calls_handler():
    seen: list[str] = []
    InlineJobQueue(seen.append).enqueue("d1")
    assert seen == ["d1"]
