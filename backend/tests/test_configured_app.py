import json
import logging

import boto3
import pytest
from moto import mock_aws

from phoebe.api import app as app_mod
from phoebe.api.app import create_configured_app
from phoebe.config import Settings, resolve_secrets
from phoebe.jobs_sqs import SqsJobQueue
from phoebe.logconfig import configure_logging
from phoebe.storage_s3 import S3BlobStore

CLUSTER = "arn:aws:rds:us-east-2:111122223333:cluster:phoebe"
SECRET = "arn:aws:secretsmanager:us-east-2:111122223333:secret:phoebe"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


class FakeClient:
    def execute_statement(self, **kw):
        return {"formattedRecords": "[]", "numberOfRecordsUpdated": 0}


def cloud_env(monkeypatch, tmp_path, **extra):
    env = {
        "PHOEBE_DB_BACKEND": "data_api",
        "PHOEBE_DB_CLUSTER_ARN": CLUSTER,
        "PHOEBE_DB_SECRET_ARN": SECRET,
        "PHOEBE_PASSWORD_HASH": "scrypt$x",
        "PHOEBE_BLOB_BACKEND": "s3",
        "PHOEBE_UPLOADS_BUCKET": "uploads",
        "PHOEBE_JOB_BACKEND": "sqs",
        "PHOEBE_JOBS_QUEUE_URL": "https://sqs.us-east-2.amazonaws.com/1/jobs",
        "PHOEBE_BLOB_DIR": str(tmp_path / "must-not-exist"),
        **extra,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_cloud_settings_build_without_touching_the_filesystem(
    monkeypatch, tmp_path, aws_env
):
    cloud_env(monkeypatch, tmp_path)
    made = []

    def factory(service, region):
        made.append((service, region))
        return FakeClient()

    monkeypatch.setattr(app_mod, "aws_client", factory)
    app = create_configured_app()
    deps = app.state.deps
    assert isinstance(deps.blobs, S3BlobStore)
    assert isinstance(deps.jobs, SqsJobQueue)
    assert not (tmp_path / "must-not-exist").exists()
    assert {s for s, _ in made} >= {"rds-data", "s3", "sqs"}
    assert {r for _, r in made} == {"us-east-2"}


def test_s3_and_sqs_require_their_settings(monkeypatch, tmp_path, aws_env):
    monkeypatch.setattr(app_mod, "aws_client", lambda s, r: FakeClient())
    cloud_env(monkeypatch, tmp_path)
    monkeypatch.delenv("PHOEBE_UPLOADS_BUCKET")
    with pytest.raises(RuntimeError, match="UPLOADS_BUCKET"):
        create_configured_app()
    cloud_env(monkeypatch, tmp_path)
    monkeypatch.delenv("PHOEBE_JOBS_QUEUE_URL")
    with pytest.raises(RuntimeError, match="JOBS_QUEUE_URL"):
        create_configured_app()


def test_harness_requires_guardrail(monkeypatch, tmp_path, aws_env):
    monkeypatch.setattr(app_mod, "aws_client", lambda s, r: FakeClient())
    cloud_env(
        monkeypatch,
        tmp_path,
        PHOEBE_ANSWER_BACKEND="harness",
        PHOEBE_HARNESS_ARN="arn:aws:bedrock:us-east-2:1:harness/h",
    )
    with pytest.raises(RuntimeError, match="GUARDRAIL"):
        create_configured_app()
    monkeypatch.setenv("PHOEBE_GUARDRAIL_ID", "gr")
    with pytest.raises(RuntimeError, match="GUARDRAIL"):
        create_configured_app()


def test_empty_password_hash_cannot_build_the_app(monkeypatch, tmp_path, aws_env):
    monkeypatch.setattr(app_mod, "aws_client", lambda s, r: FakeClient())
    cloud_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PHOEBE_PASSWORD_HASH", "")
    with pytest.raises(RuntimeError, match="PASSWORD_HASH"):
        create_configured_app()


# ---- secrets ---------------------------------------------------------------


def _settings(**kw):
    return Settings(database_url="postgresql://unused", **kw)


@mock_aws
def test_resolve_secrets_reads_both_arns(aws_env):
    sm = boto3.client("secretsmanager")
    o = sm.create_secret(Name="origin", SecretString="orig-value")["ARN"]
    p = sm.create_secret(Name="pw", SecretString="scrypt$hash")["ARN"]
    s = resolve_secrets(
        _settings(origin_secret_arn=o, password_hash_secret_arn=p), client=sm
    )
    assert (s.origin_secret, s.password_hash) == ("orig-value", "scrypt$hash")


def test_resolve_secrets_noop_without_arns():
    s = _settings(password_hash="h", origin_secret="o")
    out = resolve_secrets(s, client=object())
    assert (out.origin_secret, out.password_hash) == ("o", "h")


@mock_aws
def test_resolve_secrets_rejects_two_password_sources(aws_env):
    sm = boto3.client("secretsmanager")
    p = sm.create_secret(Name="pw", SecretString="x")["ARN"]
    with pytest.raises(RuntimeError, match="PASSWORD_HASH"):
        resolve_secrets(
            _settings(password_hash="h", password_hash_secret_arn=p), client=sm
        )


@mock_aws
def test_resolve_secrets_failure_hides_details(aws_env):
    sm = boto3.client("secretsmanager")
    with pytest.raises(RuntimeError) as exc:
        resolve_secrets(
            _settings(
                origin_secret_arn="arn:aws:secretsmanager:us-east-2:1:secret:nope"
            ),
            client=sm,
        )
    assert exc.value.__cause__ is None


# ---- logging ---------------------------------------------------------------


@pytest.fixture
def restore_logger():
    lg = logging.getLogger("phoebe")
    saved = (list(lg.handlers), lg.level, lg.propagate)
    yield
    lg.handlers[:], lg.level, lg.propagate = saved[0], saved[1], saved[2]


def test_configure_logging_emits_json_to_stdout(capsys, restore_logger):
    configure_logging("INFO")
    configure_logging("INFO")  # idempotent: one handler, one line
    logging.getLogger("phoebe.api").info("GET /api/me %d", 200)
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["level"] == "INFO"
    assert rec["logger"] == "phoebe.api"
    assert rec["msg"] == "GET /api/me 200"
    assert "ts" in rec


def test_logging_never_includes_exception_messages(capsys, restore_logger):
    configure_logging("INFO")
    try:
        raise ValueError("secret document text")
    except ValueError:
        logging.getLogger("phoebe.x").exception("boom")
    out = capsys.readouterr().out
    assert "secret document text" not in out
    assert json.loads(out)["exc_type"] == "ValueError"


def test_logging_respects_level(capsys, restore_logger):
    configure_logging("WARNING")
    logging.getLogger("phoebe.x").info("quiet")
    assert capsys.readouterr().out == ""
