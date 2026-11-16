import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import EndpointConnectionError
from moto import mock_aws

from phoebe.storage import BlobUnavailable, LocalBlobStore
from phoebe.storage_s3 import S3BlobStore

BUCKET = "uploads"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def make_store():
    client = boto3.client("s3")
    client.create_bucket(
        Bucket=BUCKET,
        CreateBucketConfiguration={"LocationConstraint": "us-east-2"},
    )
    return S3BlobStore(BUCKET, client=client)


@mock_aws
def test_round_trip(aws_env):
    store = make_store()
    store.put("sandbox/doc.pdf", b"hello")
    assert store.get("sandbox/doc.pdf") == b"hello"
    store.delete("sandbox/doc.pdf")
    with pytest.raises(KeyError):
        store.get("sandbox/doc.pdf")


@mock_aws
def test_delete_missing_is_a_noop(aws_env):
    make_store().delete("nope")


@mock_aws
def test_missing_key_raises_what_local_store_raises(aws_env, tmp_path):
    with pytest.raises(KeyError) as local:
        LocalBlobStore(tmp_path).get("k")
    with pytest.raises(KeyError) as remote:
        make_store().get("k")
    assert type(local.value) is type(remote.value)


@mock_aws
@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a\\b"])
def test_invalid_keys_raise_value_error(aws_env, key):
    with pytest.raises(ValueError):
        make_store().put(key, b"x")


def test_connection_errors_become_blob_unavailable(aws_env):
    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:9",
        config=Config(retries={"max_attempts": 0}, connect_timeout=1),
    )
    store = S3BlobStore(BUCKET, client=client)
    for call in (
        lambda: store.put("k", b"x"),
        lambda: store.get("k"),
        lambda: store.delete("k"),
    ):
        with pytest.raises(BlobUnavailable):
            call()


def test_endpoint_connection_error_is_wrapped(aws_env):
    class Boom:
        class exceptions:
            class NoSuchKey(Exception):
                pass

        def get_object(self, **kw):
            raise EndpointConnectionError(endpoint_url="http://secret-host")

    with pytest.raises(BlobUnavailable) as exc:
        S3BlobStore(BUCKET, client=Boom()).get("k")
    assert "secret-host" not in str(exc.value)
