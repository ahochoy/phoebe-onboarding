import io
import json
from dataclasses import dataclass

import pytest
from botocore.exceptions import ClientError

from phoebe.embed import (
    EMBED_DIM,
    EmbeddingUnavailable,
    HashEmbedder,
    TitanEmbedder,
    make_embedder,
)
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


class FakeBedrock:
    def __init__(self, dim=EMBED_DIM, error=None):
        self.calls: list[dict] = []
        self.dim = dim
        self.error = error

    def invoke_model(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        text = json.loads(kw["body"])["inputText"]
        vec = [0.0] * self.dim
        vec[0] = float(len(text))
        return {"body": io.BytesIO(json.dumps({"embedding": vec}).encode())}


def test_titan_request_shape():
    fake = FakeBedrock()
    out = TitanEmbedder(client=fake).embed(["hello"])
    assert len(out) == 1 and len(out[0]) == EMBED_DIM
    (call,) = fake.calls
    assert call["modelId"] == "amazon.titan-embed-text-v2:0"
    assert json.loads(call["body"]) == {
        "inputText": "hello",
        "dimensions": 1024,
        "normalize": True,
    }
    assert TitanEmbedder(client=fake).id == "titan-v2-1024"


def test_titan_preserves_order():
    texts = ["x" * n for n in range(1, 40)]
    out = TitanEmbedder(client=FakeBedrock(), max_workers=4).embed(texts)
    assert [v[0] for v in out] == [float(len(t)) for t in texts]


def test_titan_rejects_wrong_dimension():
    with pytest.raises(EmbeddingUnavailable):
        TitanEmbedder(client=FakeBedrock(dim=8)).embed(["a"])


def test_titan_wraps_client_errors():
    err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "secret text"}},
        "InvokeModel",
    )
    with pytest.raises(EmbeddingUnavailable) as ei:
        TitanEmbedder(client=FakeBedrock(error=err)).embed(["a"])
    assert ei.value.__cause__ is None and ei.value.__suppress_context__
    assert "secret" not in str(ei.value)


def test_titan_truncates_input_to_30000_chars():
    fake = FakeBedrock()
    TitanEmbedder(client=fake).embed(["y" * 50000])
    assert len(json.loads(fake.calls[0]["body"])["inputText"]) == 30000


@dataclass
class _S:
    embedder: str
    aws_region: str = "us-east-2"


def test_make_embedder_selects_by_setting():
    hash_e = make_embedder(_S("hash"))
    assert isinstance(hash_e, HashEmbedder)
    titan = make_embedder(_S("titan"))
    assert isinstance(titan, TitanEmbedder) and titan.id == "titan-v2-1024"
