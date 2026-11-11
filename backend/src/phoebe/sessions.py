import hashlib
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

IDLE_TIMEOUT = timedelta(hours=2)
ABSOLUTE_TIMEOUT = timedelta(hours=24)
MAX_ID_LENGTH = 128


def utcnow() -> datetime:
    return datetime.now(UTC)


def session_hash(session_id: str) -> str:
    """Short, non-reversible session label for logs."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:12]


def sandbox_id(session_id: str) -> str:
    """Non-secret sandbox key derived from the session token. The raw token is a
    bearer secret and must never reach the DB, blob keys or API responses."""
    return hashlib.sha256(session_id.encode()).hexdigest()


def _store_key(session_id: str) -> str:
    """Sessions are stored under sha256(token) so a leaked dump can't be replayed."""
    return hashlib.sha256(session_id.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    id: str
    created_at: datetime
    last_seen: datetime


class SessionStore(Protocol):
    def create(self) -> Session: ...

    def get(self, session_id: str) -> Session | None:
        """Return the session (touching last_seen) or None if absent/expired."""
        ...

    def delete(self, session_id: str) -> None: ...


def _valid_id(session_id: str) -> bool:
    return 0 < len(session_id) <= MAX_ID_LENGTH


def _expired(session: Session, now: datetime) -> bool:
    return (
        now - session.last_seen > IDLE_TIMEOUT
        or now - session.created_at > ABSOLUTE_TIMEOUT
    )


def _expires_at(session: Session) -> datetime:
    return min(session.last_seen + IDLE_TIMEOUT, session.created_at + ABSOLUTE_TIMEOUT)


class InMemorySessionStore:
    def __init__(self, clock: Callable[[], datetime] = utcnow) -> None:
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        now = self._clock()
        session = Session(secrets.token_urlsafe(32), now, now)
        with self._lock:
            expired = [k for k, v in self._sessions.items() if _expired(v, now)]
            for k in expired:
                del self._sessions[k]
            self._sessions[_store_key(session.id)] = session
        return session

    def get(self, session_id: str) -> Session | None:
        if not _valid_id(session_id):
            return None
        now = self._clock()
        key = _store_key(session_id)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if _expired(session, now):
                del self._sessions[key]
                return None
            session = replace(session, last_seen=now)
            self._sessions[key] = session
            return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(_store_key(session_id), None)


class DynamoDBSessionStore:
    """Sessions in DynamoDB. Expiry is enforced in code; the TTL attribute
    `expires_at` only garbage-collects."""

    def __init__(
        self,
        table_name: str,
        client: Any = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client("dynamodb")
        self._client = client
        self._table = table_name
        self._clock = clock

    @staticmethod
    def _key(session_id: str) -> dict[str, Any]:
        return {"pk": {"S": f"session#{_store_key(session_id)}"}}

    def create(self) -> Session:
        now = self._clock()
        session = Session(secrets.token_urlsafe(32), now, now)
        self._client.put_item(
            TableName=self._table,
            Item={
                **self._key(session.id),
                "created_at": {"S": now.isoformat()},
                "last_seen": {"S": now.isoformat()},
                "expires_at": {"N": str(int(_expires_at(session).timestamp()))},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return session

    def get(self, session_id: str) -> Session | None:
        if not _valid_id(session_id):
            return None
        resp = self._client.get_item(
            TableName=self._table, Key=self._key(session_id), ConsistentRead=True
        )
        item = resp.get("Item")
        if item is None:
            return None
        now = self._clock()
        try:
            session = Session(
                session_id,
                datetime.fromisoformat(item["created_at"]["S"]),
                datetime.fromisoformat(item["last_seen"]["S"]),
            )
            _expired(session, now)  # naive/aware mismatch raises TypeError
        except KeyError, ValueError, TypeError:
            self.delete(session_id)
            return None
        if _expired(session, now):
            self.delete(session_id)
            return None
        session = replace(session, last_seen=now)
        try:
            self._client.update_item(
                TableName=self._table,
                Key=self._key(session_id),
                UpdateExpression="SET last_seen = :ls, expires_at = :ea",
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeValues={
                    ":ls": {"S": now.isoformat()},
                    ":ea": {"N": str(int(_expires_at(session).timestamp()))},
                },
            )
        except self._client.exceptions.ConditionalCheckFailedException:
            return None  # deleted concurrently
        return session

    def delete(self, session_id: str) -> None:
        if not _valid_id(session_id):
            return
        self._client.delete_item(TableName=self._table, Key=self._key(session_id))
