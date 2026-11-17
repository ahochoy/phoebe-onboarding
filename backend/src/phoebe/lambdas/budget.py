"""AWS Budgets -> SNS -> Lambda: pause chat when a budget alert fires.

EventBridge -> Lambda: close the demo when this env's Aurora cluster stops
(`RDS-EVENT-0150`, e.g. the spend limit), so nothing reaches a stopped database.

Logs only SNS message ids and RDS event ids, never a message body. Never sets
`open` (only `make db-start` reopens), and never downgrades an operator's `closed`.
"""

import logging
import os
from typing import Any

from phoebe.control import DynamoDBControlStore

logger = logging.getLogger(__name__)


DB_STOPPED = "RDS-EVENT-0150"


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    region = os.environ.get("PHOEBE_AWS_REGION", "us-east-2")
    store = DynamoDBControlStore(os.environ["PHOEBE_STATE_TABLE"], region=region)
    if event.get("source") == "aws.rds":
        detail = event.get("detail") or {}
        event_id = detail.get("EventID")
        logger.info(
            "db event id=%s source=%s", event_id, detail.get("SourceIdentifier")
        )
        if event_id == DB_STOPPED:
            store.set("closed")
        return {"state": store.get()}
    for record in event.get("Records", []):
        message_id = record.get("Sns", {}).get("MessageId")
        if message_id:
            logger.info("budget alert message_id=%s", message_id)
    return {"state": store.pause_unless_closed()}
