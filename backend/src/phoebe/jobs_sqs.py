"""SQS job queue: one message per document to index."""

import json
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from phoebe.jobs import JobUnavailable


class SqsJobQueue:
    def __init__(self, queue_url: str, *, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("sqs")
        self._url = queue_url
        self._client = client

    def enqueue(self, document_id: str) -> None:
        try:
            self._client.send_message(
                QueueUrl=self._url,
                MessageBody=json.dumps({"document_id": document_id}),
            )
        except ClientError, BotoCoreError:
            raise JobUnavailable from None
