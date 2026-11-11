import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from phoebe.limits import (
    DynamoDBCounterStore,
    InMemoryCounterStore,
    LimitsUnavailable,
)

TABLE = "phoebe-state"
T0 = 1_800_000_000.0


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def _memory():
    now = [T0]
    return None, InMemoryCounterStore(clock=lambda: now[0]), now


def _ddb():
    client = boto3.client("dynamodb")
    client.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    now = [T0]
    return client, DynamoDBCounterStore(TABLE, client=client, clock=lambda: now[0]), now


@pytest.fixture(params=["memory", "dynamodb"])
def store(request, aws_env):
    if request.param == "memory":
        yield _memory()
    else:
        with mock_aws():
            yield _ddb()


def test_hit_allows_up_to_limit_then_denies(store):
    _, s, _ = store
    assert [s.hit("chat#a", 3, 3600) for _ in range(4)] == [True, True, True, False]
    assert s.peek("chat#a", 3600) == 3


def test_peek_empty_is_zero(store):
    _, s, _ = store
    assert s.peek("chat#none", 3600) == 0


def test_window_rollover_resets(store):
    _, s, now = store
    for _ in range(3):
        assert s.hit("k", 3, 60)
    assert not s.hit("k", 3, 60)
    now[0] += 3600
    assert s.peek("k", 60) == 0
    assert s.hit("k", 3, 60)


def test_keys_are_independent(store):
    _, s, _ = store
    for _ in range(2):
        assert s.hit("a", 2, 60)
    assert not s.hit("a", 2, 60)
    assert s.hit("b", 2, 60)
    assert s.peek("b", 60) == 1


@mock_aws
def test_dynamodb_item_shape_and_conditional(aws_env):
    client, s, _ = _ddb()
    window = int(T0 // 3600)
    for _ in range(2):
        assert s.hit("chat#x", 2, 3600)
    assert not s.hit("chat#x", 2, 3600)
    item = client.get_item(
        TableName=TABLE, Key={"pk": {"S": f"counter#chat#x#{window}"}}
    )["Item"]
    assert item["n"]["N"] == "2"
    assert int(item["expires_at"]["N"]) == (window + 1) * 3600 + 3600


class _ThrottledClient:
    class exceptions:
        class ConditionalCheckFailedException(Exception):
            pass

    def update_item(self, **_):
        raise ClientError({"Error": {"Code": "ThrottlingException"}}, "UpdateItem")

    def get_item(self, **_):
        raise ClientError({"Error": {"Code": "ThrottlingException"}}, "GetItem")


def test_dynamodb_other_error_raises_limits_unavailable():
    s = DynamoDBCounterStore(TABLE, client=_ThrottledClient(), clock=lambda: T0)
    with pytest.raises(LimitsUnavailable):
        s.hit("k", 1, 60)
    with pytest.raises(LimitsUnavailable):
        s.peek("k", 60)
