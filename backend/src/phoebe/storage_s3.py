"""S3 blob store. Keys are validated like LocalBlobStore; errors carry no details."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from phoebe.storage import BlobUnavailable

_MISSING = {"NoSuchKey", "404", "NotFound"}


def _check_key(key: str) -> None:
    if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
        raise ValueError("invalid blob key")


class S3BlobStore:
    def __init__(self, bucket: str, *, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._bucket = bucket
        self._client = client

    def put(self, key: str, data: bytes) -> None:
        _check_key(key)
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        except ClientError, BotoCoreError:
            raise BlobUnavailable from None

    def get(self, key: str) -> bytes:
        _check_key(key)
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                raise KeyError(key) from None
            raise BlobUnavailable from None
        except BotoCoreError:
            raise BlobUnavailable from None

    def delete(self, key: str) -> None:
        _check_key(key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError, BotoCoreError:
            raise BlobUnavailable from None
