import json

import boto3
import pytest
from botocore.config import Config
from moto import mock_aws

from phoebe.jobs import JobUnavailable
from phoebe.jobs_sqs import SqsJobQueue

DOC = "0b9f0c0e-0000-4000-8000-000000000001"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@mock_aws
def test_enqueue_sends_exactly_one_message(aws_env):
    sqs = boto3.client("sqs")
    url = sqs.create_queue(QueueName="jobs")["QueueUrl"]
    SqsJobQueue(url, client=sqs).enqueue(DOC)
    msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
    assert len(msgs) == 1
    assert json.loads(msgs[0]["Body"]) == {"document_id": DOC}


def test_send_failure_raises_job_unavailable(aws_env):
    sqs = boto3.client(
        "sqs",
        endpoint_url="http://127.0.0.1:9",
        config=Config(retries={"max_attempts": 0}, connect_timeout=1),
    )
    with pytest.raises(JobUnavailable):
        SqsJobQueue("http://127.0.0.1:9/q", client=sqs).enqueue("d")
