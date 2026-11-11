from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from phoebe.sessions import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    DynamoDBSessionStore,
    InMemorySessionStore,
    session_hash,
    utcnow,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TABLE = "phoebe-sessions"


def make_store():
    now = [T0]
    return InMemorySessionStore(clock=lambda: now[0]), now


def test_constants_and_utcnow():
    assert IDLE_TIMEOUT == timedelta(hours=2)
    assert ABSOLUTE_TIMEOUT == timedelta(hours=24)
    assert utcnow().tzinfo is not None
    assert utcnow().utcoffset() == timedelta(0)


def test_session_hash_is_12_hex_and_stable():
    h = session_hash("abc")
    assert len(h) == 12 and int(h, 16) >= 0
    assert h == session_hash("abc") != session_hash("abd")


def test_create_ids_unique_and_utc():
    s, _ = make_store()
    a, b = s.create(), s.create()
    assert a.id != b.id and len(a.id) >= 43
    assert a.created_at == a.last_seen == T0


def test_idle_expiry():
    s, now = make_store()
    sess = s.create()
    now[0] = T0 + timedelta(hours=1, minutes=59)
    assert s.get(sess.id)
    now[0] += timedelta(hours=2, minutes=1)
    assert s.get(sess.id) is None


def test_get_touches_last_seen():
    s, now = make_store()
    sess = s.create()
    now[0] = T0 + timedelta(hours=1)
    got = s.get(sess.id)
    assert got is not None and got.last_seen == now[0] and got.created_at == T0


def test_idle_boundary_exactly_two_hours_valid():
    s, now = make_store()
    sess = s.create()
    now[0] = T0 + IDLE_TIMEOUT
    assert s.get(sess.id) is not None
    now[0] = T0 + IDLE_TIMEOUT + IDLE_TIMEOUT + timedelta(seconds=1)
    assert s.get(sess.id) is None


def test_idle_just_over_two_hours_expired():
    s, now = make_store()
    sess = s.create()
    now[0] = T0 + IDLE_TIMEOUT + timedelta(seconds=1)
    assert s.get(sess.id) is None


def test_absolute_expiry_despite_activity():
    s, now = make_store()
    sess = s.create()
    for _ in range(25):
        now[0] += timedelta(hours=1)
        s.get(sess.id)
    assert s.get(sess.id) is None


def test_absolute_boundary():
    s, now = make_store()
    sess = s.create()
    for _ in range(24):
        now[0] += timedelta(hours=1)
        assert s.get(sess.id) is not None
    assert now[0] - T0 == ABSOLUTE_TIMEOUT
    now[0] += timedelta(seconds=1)
    assert s.get(sess.id) is None


def test_expired_session_is_deleted():
    s, now = make_store()
    sess = s.create()
    now[0] = T0 + timedelta(hours=3)
    assert s.get(sess.id) is None
    now[0] = T0
    assert s.get(sess.id) is None


def test_delete_and_bad_ids():
    s, _ = make_store()
    sess = s.create()
    s.delete(sess.id)
    assert s.get(sess.id) is None
    s.delete("nonexistent")
    assert s.get("") is None
    assert s.get("x" * 129) is None
    assert s.get("unknown") is None


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def make_ddb():
    client = boto3.client("dynamodb")
    client.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    now = [T0]
    return client, DynamoDBSessionStore(TABLE, client=client, clock=lambda: now[0]), now


def _item(client, sid):
    return client.get_item(TableName=TABLE, Key={"pk": {"S": f"session#{sid}"}}).get(
        "Item"
    )


@mock_aws
def test_dynamodb_store_roundtrip(aws_env):
    client, s, now = make_ddb()
    sess = s.create()
    item = _item(client, sess.id)
    assert item is not None
    assert int(item["expires_at"]["N"]) == int((T0 + IDLE_TIMEOUT).timestamp())
    now[0] = T0 + timedelta(hours=1)
    got = s.get(sess.id)
    assert got is not None and got.last_seen == now[0] and got.created_at == T0
    item = _item(client, sess.id)
    assert item is not None
    assert int(item["expires_at"]["N"]) == int((now[0] + IDLE_TIMEOUT).timestamp())
    s.delete(sess.id)
    assert _item(client, sess.id) is None
    assert s.get(sess.id) is None


@mock_aws
def test_dynamodb_expires_at_capped_by_absolute(aws_env):
    client, s, now = make_ddb()
    sess = s.create()
    # keep alive hourly so idle never trips
    for h in range(1, 24):
        now[0] = T0 + timedelta(hours=h)
        assert s.get(sess.id)
    now[0] = T0 + timedelta(hours=23, minutes=30)
    assert s.get(sess.id)
    item = _item(client, sess.id)
    assert item is not None
    assert int(item["expires_at"]["N"]) == int((T0 + ABSOLUTE_TIMEOUT).timestamp())


@mock_aws
def test_dynamodb_expiry_checked_in_code(aws_env):
    client, s, now = make_ddb()
    sess = s.create()
    now[0] = T0 + IDLE_TIMEOUT
    assert s.get(sess.id) is not None
    now[0] += IDLE_TIMEOUT + timedelta(seconds=1)
    assert s.get(sess.id) is None
    assert _item(client, sess.id) is None


@mock_aws
def test_dynamodb_absolute_expiry(aws_env):
    _, s, now = make_ddb()
    sess = s.create()
    for _ in range(24):
        now[0] += timedelta(hours=1)
        assert s.get(sess.id)
    now[0] += timedelta(seconds=1)
    assert s.get(sess.id) is None


@mock_aws
def test_dynamodb_bad_ids_no_storage(aws_env):
    _, s, _ = make_ddb()
    assert s.get("") is None
    assert s.get("x" * 129) is None
    assert s.get("missing") is None
    s.delete("missing")


@mock_aws
def test_dynamodb_default_client(aws_env):
    boto3.client("dynamodb").create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    s = DynamoDBSessionStore(TABLE)
    sess = s.create()
    assert s.get(sess.id)
