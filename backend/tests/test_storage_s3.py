import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
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


class FailingClient:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def put_object(self, **kw):
        raise self._exc

    def get_object(self, **kw):
        raise self._exc

    def delete_object(self, **kw):
        raise self._exc


def _client_error(code: str, status: int = 500) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "detail"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "GetObject",
    )


def test_connection_errors_become_blob_unavailable():
    exc = EndpointConnectionError(endpoint_url="http://secret-host")
    store = S3BlobStore(BUCKET, client=FailingClient(exc))
    for call in (
        lambda: store.put("k", b"x"),
        lambda: store.get("k"),
        lambda: store.delete("k"),
    ):
        with pytest.raises(BlobUnavailable) as raised:
            call()
        assert "secret-host" not in str(raised.value)


@pytest.mark.parametrize("code", ["AccessDenied", "InternalError", "SlowDown"])
def test_other_client_errors_become_blob_unavailable_not_missing(code):
    store = S3BlobStore(BUCKET, client=FailingClient(_client_error(code)))
    with pytest.raises(BlobUnavailable):
        store.get("k")
    with pytest.raises(BlobUnavailable):
        store.put("k", b"x")
