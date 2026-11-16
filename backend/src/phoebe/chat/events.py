"""Wire shapes of the chat SSE events, shared by the service and the OpenAPI
export. Field order is the wire order; the JSON must not change shape."""

from typing import Literal

from pydantic import BaseModel

from phoebe.chat.verify import Citation

Reason = Literal["no_support", "verification_failed", "blocked", "model_unavailable"]


class MetaEvent(BaseModel):
    turn_id: str


class DeltaEvent(BaseModel):
    text: str


class ClosestDoc(BaseModel):
    document_id: str
    title: str


class DoneEvent(BaseModel):
    text: str
    refused: bool
    reason: Reason | None
    citations: list[Citation]
    closest: list[ClosestDoc]


class ErrorEvent(BaseModel):
    code: str
