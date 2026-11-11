"""Job queue abstraction; the inline queue runs the handler synchronously."""

from collections.abc import Callable
from typing import Protocol


class JobQueue(Protocol):
    def enqueue(self, document_id: str) -> None: ...


class InlineJobQueue:
    def __init__(self, handler: Callable[[str], None]) -> None:
        self._handler = handler

    def enqueue(self, document_id: str) -> None:
        self._handler(document_id)
