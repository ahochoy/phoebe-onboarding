"""AWS Budgets -> SNS -> Lambda: pause chat when a budget alert fires.

Logs only SNS message ids, never the message body. Never sets `open`, and never
downgrades an operator's `closed`.
"""

import logging
import os
from typing import Any

from phoebe.control import DynamoDBControlStore

logger = logging.getLogger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    for record in event.get("Records", []):
        message_id = record.get("Sns", {}).get("MessageId")
        if message_id:
            logger.info("budget alert message_id=%s", message_id)
    store = DynamoDBControlStore(os.environ["PHOEBE_STATE_TABLE"])
    if store.get() == "closed":
        return {"state": "closed"}
    store.set("chat_paused")
    return {"state": "chat_paused"}
