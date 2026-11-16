"""Shared parsing of SQS records. Never logs or returns record bodies."""

import json
from typing import Any


def document_id(record: dict[str, Any]) -> str | None:
    """The document id of a `{"document_id": ...}` body, or None if malformed."""
    try:
        value = json.loads(record["body"]).get("document_id")
    except KeyError, TypeError, ValueError, AttributeError:
        return None
    return value if isinstance(value, str) and value else None


def message_id(record: dict[str, Any]) -> str:
    return str(record.get("messageId", "-"))
