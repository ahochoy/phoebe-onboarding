import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from phoebe import budget_handler
from phoebe.control import (
    CachedControlStore,
    DynamoDBControlStore,
    FileControlStore,
    KillState,
)
from phoebe.limits import LimitsUnavailable

TABLE = "phoebe-state"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def _table():
    client = boto3.client("dynamodb")
    client.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return client


def test_file_roundtrip(tmp_path: Path):
    s = FileControlStore(tmp_path / "sub" / "control.json")
    assert s.get() == "open"
    s.set("chat_paused")
    assert s.get() == "chat_paused"
    s.set("closed")
    assert FileControlStore(tmp_path / "sub" / "control.json").get() == "closed"
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["control.json"]


def test_file_garbage_raises(tmp_path: Path):
    p = tmp_path / "control.json"
    for text in ("not json", '{"state": "bogus"}', "[]", '{"x": 1}'):
        p.write_text(text)
        with pytest.raises(LimitsUnavailable):
            FileControlStore(p).get()


@mock_aws
def test_dynamodb_roundtrip(aws_env):
    _table()
    s = DynamoDBControlStore(TABLE)
    assert s.get() == "open"
    s.set("closed")
    assert s.get() == "closed"
    s.set("open")
    assert s.get() == "open"


class _Inner:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.state: KillState = "closed"

    def get(self) -> KillState:
        self.calls += 1
        if self.fail:
            raise LimitsUnavailable()
        return self.state

    def set(self, state: KillState) -> None:
        self.state = state


def test_cached_control_caches_for_ttl():
    inner, now = _Inner(), [100.0]
    c = CachedControlStore(inner, 5, lambda: now[0])
    assert c.get() == "closed" and c.get() == "closed"
    assert inner.calls == 1
    now[0] += 6
    c.get()
    assert inner.calls == 2


def test_cached_control_fails_closed_to_chat_paused():
    inner, now = _Inner(), [100.0]
    c = CachedControlStore(inner, 5, lambda: now[0])
    inner.fail = True
    assert c.get() == "chat_paused"
    assert c.get() == "chat_paused"
    assert inner.calls == 2  # error not cached
    inner.fail = False
    assert c.get() == "closed"


def test_cached_set_invalidates():
    inner, now = _Inner(), [100.0]
    c = CachedControlStore(inner, 5, lambda: now[0])
    assert c.get() == "closed"
    c.set("open")
    assert c.get() == "open"


@mock_aws
def test_budget_handler_sets_chat_paused(aws_env, monkeypatch, caplog):
    client = _table()
    monkeypatch.setenv("PHOEBE_STATE_TABLE", TABLE)
    event = {
        "Records": [
            {"Sns": {"MessageId": "mid-1", "Message": "SECRET BUDGET BODY"}},
            {"Sns": {"MessageId": "mid-2", "Message": "SECRET BUDGET BODY"}},
        ]
    }
    with caplog.at_level("INFO"):
        out = budget_handler.handler(event, None)
    assert out == {"state": "chat_paused"}
    assert DynamoDBControlStore(TABLE, client=client).get() == "chat_paused"
    assert "mid-1" in caplog.text and "mid-2" in caplog.text
    assert "SECRET" not in caplog.text


@mock_aws
def test_budget_handler_never_opens(aws_env, monkeypatch):
    client = _table()
    monkeypatch.setenv("PHOEBE_STATE_TABLE", TABLE)
    DynamoDBControlStore(TABLE, client=client).set("closed")
    out = budget_handler.handler({"Records": [{"Sns": {"MessageId": "m"}}]}, None)
    assert out == {"state": "closed"}
    assert DynamoDBControlStore(TABLE, client=client).get() == "closed"


def _cli(*args: str, control_file: Path):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("PHOEBE_") and not k.startswith("AWS_")
    }
    env["PHOEBE_CONTROL_FILE"] = str(control_file)
    return subprocess.run(
        [sys.executable, "-m", "phoebe", "control", *args],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )


def test_cli_control_sets_file_state(tmp_path: Path):
    f = tmp_path / "control.json"
    r = _cli("chat_paused", control_file=f)
    assert r.returncode == 0 and r.stdout.strip() == "chat_paused"
    assert json.loads(f.read_text()) == {"state": "chat_paused"}
    r = _cli("status", control_file=f)
    assert r.returncode == 0 and r.stdout.strip() == "chat_paused"
    r = _cli("open", control_file=f)
    assert r.stdout.strip() == "open"


def test_cli_control_rejects_bad_state(tmp_path: Path):
    r = _cli("bogus", control_file=tmp_path / "c.json")
    assert r.returncode == 2 and "usage" in r.stderr


def test_cached_error_never_downgrades_closed():
    inner, now = _Inner(), [100.0]
    c = CachedControlStore(inner, 5, lambda: now[0])
    assert c.get() == "closed"
    now[0] += 6
    inner.fail = True
    assert c.get() == "closed"
    assert c.get() == "closed"
    inner.fail = False
    inner.state = "open"
    assert c.get() == "open"


def test_cached_error_after_open_is_chat_paused():
    inner, now = _Inner(), [100.0]
    inner.state = "open"
    c = CachedControlStore(inner, 5, lambda: now[0])
    assert c.get() == "open"
    now[0] += 6
    inner.fail = True
    assert c.get() == "chat_paused"


@mock_aws
def test_budget_handler_overwrites_corrupt_state(aws_env, monkeypatch):
    client = _table()
    monkeypatch.setenv("PHOEBE_STATE_TABLE", TABLE)
    event = {"Records": [{"Sns": {"MessageId": "m"}}]}
    for corrupt in ({"state": {"N": "5"}}, {"state": {"S": "bogus"}}, {}):
        client.put_item(TableName=TABLE, Item={"pk": {"S": "control"}, **corrupt})
        assert budget_handler.handler(event, None) == {"state": "chat_paused"}
        assert DynamoDBControlStore(TABLE, client=client).get() == "chat_paused"


def _db_stopped_event(event_id="RDS-EVENT-0150"):
    return {
        "source": "aws.rds",
        "detail-type": "RDS DB Cluster Event",
        "detail": {
            "EventID": event_id,
            "SourceIdentifier": "phoebe-staging",
            "Message": "SECRET EVENT BODY",
        },
    }


@mock_aws
@pytest.mark.parametrize("start", ["open", "chat_paused", "closed"])
def test_db_stopped_event_closes_from_any_state(aws_env, monkeypatch, start):
    client = _table()
    monkeypatch.setenv("PHOEBE_STATE_TABLE", TABLE)
    DynamoDBControlStore(TABLE, client=client).set(start)
    assert budget_handler.handler(_db_stopped_event(), None) == {"state": "closed"}
    assert DynamoDBControlStore(TABLE, client=client).get() == "closed"


@mock_aws
def test_db_stopped_event_is_idempotent(aws_env, monkeypatch):
    client = _table()
    monkeypatch.setenv("PHOEBE_STATE_TABLE", TABLE)
    for _ in range(2):  # EventBridge delivers at least once
        assert budget_handler.handler(_db_stopped_event(), None) == {"state": "closed"}
    assert DynamoDBControlStore(TABLE, client=client).get() == "closed"


@mock_aws
def test_db_stopped_event_logs_metadata_only(aws_env, monkeypatch, caplog):
    _table()
    monkeypatch.setenv("PHOEBE_STATE_TABLE", TABLE)
    with caplog.at_level("INFO"):
        budget_handler.handler(_db_stopped_event(), None)
    assert "RDS-EVENT-0150" in caplog.text and "phoebe-staging" in caplog.text
    assert "SECRET" not in caplog.text


@mock_aws
def test_unrelated_rds_event_changes_nothing(aws_env, monkeypatch):
    client = _table()
    monkeypatch.setenv("PHOEBE_STATE_TABLE", TABLE)
    DynamoDBControlStore(TABLE, client=client).set("open")
    out = budget_handler.handler(_db_stopped_event("RDS-EVENT-0151"), None)
    assert out == {"state": "open"}
    assert DynamoDBControlStore(TABLE, client=client).get() == "open"


def test_cli_dynamodb_without_table_exits_cleanly(tmp_path: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PHOEBE_", "AWS_"))}
    env["PHOEBE_CONTROL_BACKEND"] = "dynamodb"
    r = subprocess.run(
        [sys.executable, "-m", "phoebe", "control", "status"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert "PHOEBE_STATE_TABLE" in r.stderr
